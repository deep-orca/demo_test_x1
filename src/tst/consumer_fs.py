import asyncio
import json
import random

from faststream import Logger
from tst.fs import TaskPayload, app, broker, delayed_exchange, dlq_queue, main_queue


@broker.subscriber(queue=main_queue, exchange=delayed_exchange)
async def handle_task(data: TaskPayload, logger: Logger) -> None:
    await asyncio.sleep(0.1)

    # Имитация случайного сбоя (80% вероятность)
    if random.random() < 0.8:
        raise RuntimeError("Внешний сервис временно недоступен")

    # event_data = {
    #     "event": "payment.pending",
    #     "payment_id": new_payment.id,
    #     "order_id": payment.order_id,
    #     "amount": payment.amount,
    #     "currency": payment.currency,
    # }

    event_data = json.loads(data.action)

    logger.info(f"[SUCCESS] Задача #{data.task_id} ({data.action}) успешно выполнена!")


@app.after_startup
async def init_app() -> None:
    _ = await broker.declare_queue(main_queue)
    _ = await broker.declare_queue(dlq_queue)


if __name__ == "__main__":
    asyncio.run(app.run())
