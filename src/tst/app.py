import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

# from tst.outbox_worker_pika import outbox_worker
from tst.outbox_worker_fs import outbox_worker
from tst.payment_rmq import router


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker_task = asyncio.create_task(outbox_worker())
    yield
    worker_task.cancel()


app = FastAPI(title="Платежный сервис + Outbox + Alembic", lifespan=lifespan)
app.include_router(router)
