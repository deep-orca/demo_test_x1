import asyncio
import json
import random
import uuid

from faststream import Logger
from tst.fs import TaskPayload, app, broker, delayed_exchange, dlq_queue, main_queue


from tst.ioc import async_session
from tst.models import OutboxEventModel


@broker.subscriber(queue=main_queue, exchange=delayed_exchange)
async def handle_task(data: TaskPayload, logger: Logger) -> None:
    event_data: dict[str, str | float] = json.loads(data.action)

    await asyncio.sleep(0.2)

    if random.random() < 0.8:
        raise RuntimeError(
            f"{event_data["event"]}|{event_data["payment_id"]}: Внешний сервис временно недоступен"
        )

    if event_data["event"] == "payment.pending":
        new_event_data = event_data.copy()
        new_event_data["event"] = "payment.webhook"

        outbox_event = OutboxEventModel(
            id=str(uuid.uuid4()),
            event_type=new_event_data["event"],
            payload=json.dumps(new_event_data),
        )

        async with async_session() as db:
            db.add(outbox_event)

            await db.flush()
            await db.commit()

    logger.info(
        f"[SUCCESS] Задача #{data.task_id}|{event_data["event"]}|{event_data["payment_id"]} ({data.action}) успешно выполнена!"
    )


@app.after_startup
async def init_app() -> None:
    _ = await broker.declare_queue(main_queue)
    _ = await broker.declare_queue(dlq_queue)


if __name__ == "__main__":
    asyncio.run(app.run())
