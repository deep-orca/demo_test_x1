import asyncio

from sqlalchemy import select

from tst.fs import TaskPayload, broker, delayed_exchange, dlq_queue, main_queue
from tst.ioc import async_session
from tst.models import OutboxEventModel


async def outbox_worker():
    await broker.connect()  # pyright: ignore[reportUnusedCallResult]
    await broker.declare_queue(main_queue)  # pyright: ignore[reportUnusedCallResult]
    await broker.declare_queue(dlq_queue)  # pyright: ignore[reportUnusedCallResult]

    while True:
        try:
            async with async_session() as db:
                stmt = (
                    select(OutboxEventModel)
                    .where(OutboxEventModel.processed == False)  # noqa: E712
                    .limit(10)
                    .with_for_update()
                )
                if events := (await db.execute(stmt)).scalars().all():
                    for event in events:
                        await broker.publish(  # pyright: ignore[reportUnusedCallResult]
                            message=TaskPayload(task_id=event.id, action=event.payload),
                            message_id=event.id,
                            exchange=delayed_exchange,
                            routing_key="task",
                            persist=True,
                        )
                        event.processed = True
                        print(f"[Outbox] Событие {event.id} отправлено в RabbitMQ")

                    await db.commit()
        except Exception as e:
            print(
                f"[Outbox Error] Ошибка отправки в брокер (повторим через 3 сек): {e}"
            )

        await asyncio.sleep(3)
