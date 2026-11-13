import asyncio
from datetime import datetime, timezone
import json
import random
import uuid

import aiohttp
from faststream import Logger
from sqlalchemy import select
from tst.fs import TaskPayload, app, broker, delayed_exchange, dlq_queue, main_queue
from tst.ioc import async_session
from tst.models import OutboxEventModel, PaymentModel, PaymentStatus


@broker.subscriber(queue=main_queue, exchange=delayed_exchange)
async def handle_task(data: TaskPayload, logger: Logger) -> None:
    event_data = json.loads(data.action)

    if event_data["event"] == "payment.pending":
        async with async_session() as db:
            stmt = (
                select(PaymentModel)
                .where(PaymentModel.id == event_data["payment_id"])
                .with_for_update()
            )

            payment = (await db.execute(stmt)).scalar_one_or_none()

            if not payment:
                raise RuntimeError(f"Платеж {event_data['payment_id']} не найден")

            await asyncio.sleep(random.randint(2, 5))  # ==========================

            if random.random() < 0.1:
                raise RuntimeError(
                    f"{event_data["event"]}|{event_data["payment_id"]}: Внешний сервис временно недоступен"
                )

            new_event_data = event_data.copy()
            new_event_data["event"] = "payment.webhook"
            new_event_data["webhook"] = payment.webhook

            payment.status = PaymentStatus.SUCCEEDED.value
            payment.processed_at = datetime.now(timezone.utc)

            outbox_event = OutboxEventModel(
                id=str(uuid.uuid4()),
                event_type=new_event_data["event"],
                payload=json.dumps(new_event_data),
            )

            db.add(outbox_event)

            await db.flush()
            await db.commit()
    elif event_data["event"] == "payment.pending":
        async with aiohttp.ClientSession() as session:
            async with session.get(event_data["webhook"]) as response:
                print("Status:", response.status)
                print("Content-type:", response.headers["content-type"])

                response.raise_for_status()

                html = await response.text()
                print("Body:", html[:100], "...")

    logger.info(
        f"[SUCCESS] Задача #{data.task_id}|{event_data["event"]}|{event_data["payment_id"]} ({data.action}) успешно выполнена!"
    )


@app.after_startup
async def init_app() -> None:
    _ = await broker.declare_queue(main_queue)
    _ = await broker.declare_queue(dlq_queue)


if __name__ == "__main__":
    asyncio.run(app.run())
