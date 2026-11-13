from collections.abc import Awaitable
import random
from typing import Any, Callable, override
from pydantic import BaseModel

from faststream import FastStream, BaseMiddleware
from faststream.rabbit import RabbitBroker, RabbitExchange, RabbitQueue, ExchangeType
from faststream.rabbit.message import RabbitMessage

from tst.config import RABBITMQ_URL


class TransientError(RuntimeError):
    pass


class PermanentError(RuntimeError):
    pass


MAX_RETRIES = 3
BASE_DELAY_MS = 1000
MAX_DELAY_MS = 60000


def calculate_backoff_with_jitter_ms(attempt: int) -> int:
    exp_delay = min(MAX_DELAY_MS, BASE_DELAY_MS * (2**attempt))
    return random.randint(0, exp_delay)


delayed_exchange = RabbitExchange(
    name="delayed_exchange",
    type=ExchangeType.X_DELAYED_MESSAGE,
    durable=True,
    arguments={"x-delayed-type": "direct"},
)

main_queue = RabbitQueue(
    name="payments.new",
    durable=True,
    routing_key="task",
)

dlq_queue = RabbitQueue(
    name="dead_letter_queue",
    durable=True,
)


async def toDLQ(msg: RabbitMessage):
    headers = dict(msg.headers or {})
    headers.pop("x-delay", None)

    await broker.publish(  # pyright: ignore[reportUnusedCallResult]
        message=msg.body,
        queue=dlq_queue,
        headers=headers,
        persist=True,
    )


class DelayedRetryMiddleware(BaseMiddleware):
    @override
    async def consume_scope(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        call_next: Callable[[Any], Awaitable[Any]],
        msg: RabbitMessage,
    ):
        try:
            return await call_next(msg)
        except PermanentError as exc:
            print(
                f"[FAILED RETRY PERMANENT ERROR] Ошибка: {exc}. [FAILED]. Отправка в DLQ."
            )
            await toDLQ(msg)
        except Exception as exc:
            headers = dict(msg.headers or {})
            retry_count = int(headers.get("x-retry-count", 0))

            if retry_count < MAX_RETRIES:  # Double check ...
                delay_ms = calculate_backoff_with_jitter_ms(retry_count)
                headers["x-retry-count"] = retry_count + 1
                headers["x-delay"] = delay_ms

                print(
                    f"[RETRY] Ошибка: {exc}. Попытка {retry_count + 1}/{MAX_RETRIES} через {delay_ms} мс..."
                )

                await broker.publish(  # pyright: ignore[reportUnusedCallResult]
                    message=msg.body,
                    exchange=delayed_exchange,
                    routing_key="task",
                    headers=headers,
                    persist=True,
                )
            else:
                print(
                    f"[FAILED] Лимит попыток исчерпан ({MAX_RETRIES}). Отправка в DLQ."
                )
                await toDLQ(msg)

            return None


broker = RabbitBroker(RABBITMQ_URL, middlewares=[DelayedRetryMiddleware])
app = FastStream(broker)


class TaskPayload(BaseModel):
    task_id: str
    action: str
