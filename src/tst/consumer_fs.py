import asyncio
from datetime import datetime, timezone
import json
import random
from typing import Annotated
import uuid

import aiohttp
from faststream import Context, Depends, Logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tst.fs import (
    MAX_RETRIES,
    PermanentError,
    TaskPayload,
    TransientError,
    app,
    broker,
    delayed_exchange,
    dlq_queue,
    main_queue,
)
from tst.ioc import get_db
from tst.models import OutboxEventModel, PaymentModel, PaymentStatus


async def process_pending(ev, payment):
    await asyncio.sleep(random.randint(2, 5))

    if random.random() < 0.1:
        raise TransientError(
            f"{ev["event"]}|{ev["payment_id"]}: Внешний сервис временно недоступен"
        )

    new_event_data = ev.copy()
    new_event_data["event"] = "payment.webhook"
    new_event_data["webhook"] = payment.webhook

    payment.status = PaymentStatus.SUCCEEDED.value
    payment.processed_at = datetime.now(timezone.utc)

    return OutboxEventModel(
        id=str(uuid.uuid4()),
        event_type=new_event_data["event"],
        payload=json.dumps(new_event_data),
    )


async def process_webhook(ev, payment):
    print("WebHook:", ev["webhook"])
    async with aiohttp.ClientSession(raise_for_status=True) as session:
        async with session.post(ev["webhook"]) as response:
            print("Status:", response.status)
            print("Content-type:", response.headers["content-type"])
            html = await response.text()
            print("Body:", html[:100], "...")


async def get_payment(db: AsyncSession, ev) -> PaymentModel:
    stmt = (
        select(PaymentModel)
        .where(PaymentModel.id == ev["payment_id"])
        .with_for_update()
    )

    payment = (await db.execute(stmt)).scalar_one_or_none()

    if not payment:
        raise PermanentError(f"Платеж {ev['payment_id']} не найден")

    return payment


@broker.subscriber(queue=main_queue, exchange=delayed_exchange)
async def handle_task(
    data: TaskPayload,
    logger: Logger,
    retry: Annotated[int | None, Context("message.headers.x-retry-count", default=0)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    ev = json.loads(data.action)  # pyright: ignore[reportAny]
    payment = await get_payment(db, ev)

    try:
        if ev["event"] == "payment.pending":
            outbox_event = await process_pending(ev, payment)
            db.add(outbox_event)
            await db.flush()
            await db.commit()
        elif ev["event"] == "payment.webhook":
            await process_webhook(ev, payment)
        logger.info(
            f"[SUCCESS] Задача #{data.task_id}|{ev["event"]}|{ev["payment_id"]} ({data.action}) успешно выполнена!"
        )

    except PermanentError:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        if retry == MAX_RETRIES:
            payment = await get_payment(db, ev)
            if payment.status == PaymentStatus.PENDING.value:
                payment.status = PaymentStatus.CANCELED.value
                await db.flush()
                await db.commit()
        raise e


@app.after_startup
async def init_app() -> None:
    _ = await broker.declare_queue(main_queue)
    _ = await broker.declare_queue(dlq_queue)


if __name__ == "__main__":
    asyncio.run(app.run())
