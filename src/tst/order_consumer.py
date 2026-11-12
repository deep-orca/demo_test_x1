import asyncio
import json
import aio_pika

from tst.config import QUEUE_NAME, RABBITMQ_URL


async def main():
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue(QUEUE_NAME, durable=True)

        print(" [*] Основной сервис заказов ждет уведомлений об оплате...")

        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    data = json.loads(message.body.decode())
                    print(
                        f" [+] УСПЕХ: Заказ {data['order_id']} оплачен на сумму {data['amount']} {data['currency']}!"
                    )


if __name__ == "__main__":
    asyncio.run(main())
