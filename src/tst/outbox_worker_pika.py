import asyncio

import aio_pika
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tst.config import DATABASE_URL, QUEUE_NAME, RABBITMQ_URL
from tst.models import OutboxEventModel

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def outbox_worker():
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
                    connection = await aio_pika.connect_robust(RABBITMQ_URL)
                    async with connection:
                        channel = await connection.channel()
                        _ = await channel.declare_queue(QUEUE_NAME, durable=True)

                        for event in events:
                            message = aio_pika.Message(
                                body=event.payload.encode(),
                                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                                message_id=event.id,
                            )
                            _ = await channel.default_exchange.publish(
                                message, routing_key=QUEUE_NAME
                            )
                            event.processed = True
                            print(f"[Outbox] Событие {event.id} отправлено в RabbitMQ")

                        await db.commit()
        except Exception as e:
            print(
                f"[Outbox Error] Ошибка отправки в брокер (повторим через 3 сек): {e}"
            )

        await asyncio.sleep(3)
