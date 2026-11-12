import uuid
import hashlib
import json
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header, Response, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.exc import IntegrityError
from typing_extensions import Any

from tst.config import DATABASE_URL, WEBHOOK_SECRET
from tst.models import PaymentStatus, PaymentModel, OutboxEventModel
from tst.outbox_worker import outbox_worker

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


# Таблицы больше не создаются здесь — этим занимается Alembic при старте контейнера
@asynccontextmanager
async def lifespan(_: FastAPI):
    worker_task = asyncio.create_task(outbox_worker())
    yield
    worker_task.cancel()


app = FastAPI(title="Платежный сервис + Outbox + Alembic", lifespan=lifespan)


async def get_db():
    async with async_session() as session:
        yield session


class PaymentCreate(BaseModel):
    order_id: str = Field(..., description="ID заказа")
    amount: float = Field(..., gt=0, description="Сумма платежа")
    currency: str = Field(default="RUB", description="Валюта")


class PaymentWebhook(BaseModel):
    payment_id: str
    status: PaymentStatus


def get_payload_hash(payload: PaymentCreate) -> str:
    data_str = json.dumps(payload.model_dump(), sort_keys=True)
    return hashlib.sha256(data_str.encode()).hexdigest()


def format_response(
    payment: PaymentModel, is_duplicate: bool = False
) -> dict[str, Any]:
    return {
        "payment_id": payment.id,
        "order_id": payment.order_id,
        "amount": payment.amount,
        "currency": payment.currency,
        "status": payment.status,
        "confirmation_url": f"https://fake-gateway.local{payment.id}",
        "is_duplicate": is_duplicate,
    }


@app.post("/payments")
async def create_payment(
    payment: PaymentCreate,
    response: Response,
    idempotency_key: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    current_hash = get_payload_hash(payment)
    stmt = select(PaymentModel).where(PaymentModel.idempotency_key == idempotency_key)
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        if existing.request_hash != current_hash:
            raise HTTPException(
                status_code=422, detail="Ключ уже использовался с другими параметрами"
            )
        response.status_code = status.HTTP_200_OK
        return format_response(existing, is_duplicate=True)

    new_payment = PaymentModel(
        id=str(uuid.uuid4()),
        idempotency_key=idempotency_key,
        request_hash=current_hash,
        order_id=payment.order_id,
        amount=payment.amount,
        currency=payment.currency,
    )
    db.add(new_payment)

    try:
        await db.commit()
        await db.refresh(new_payment)
        response.status_code = status.HTTP_201_CREATED
        return format_response(new_payment, is_duplicate=False)
    except IntegrityError:
        await db.rollback()
        existing = (await db.execute(stmt)).scalar_one()
        response.status_code = status.HTTP_200_OK
        return format_response(existing, is_duplicate=True)


@app.get("/payments/{payment_id}")
async def get_payment_status(payment_id: str, db: AsyncSession = Depends(get_db)):
    stmt = select(PaymentModel).where(PaymentModel.id == payment_id)
    payment = (await db.execute(stmt)).scalar_one_or_none()

    if not payment:
        raise HTTPException(status_code=404, detail="Платеж не найден")
    return format_response(payment)


@app.post("/payments/webhook")
async def payment_webhook(
    payload: PaymentWebhook,
    x_webhook_secret: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    if x_webhook_secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Неверный секретный ключ")

    async with db.begin():
        stmt = (
            select(PaymentModel)
            .where(PaymentModel.id == payload.payment_id)
            .with_for_update()
        )
        payment = (await db.execute(stmt)).scalar_one_or_none()

        if not payment:
            raise HTTPException(status_code=404, detail="Платеж не найден")

        if payment.status in [
            PaymentStatus.SUCCEEDED.value,
            PaymentStatus.CANCELED.value,
        ]:
            return {"message": "Вебхук уже обработан", "status": payment.status}

        payment.status = payload.status.value

        if payload.status == PaymentStatus.SUCCEEDED:
            event_data = {
                "event": "payment.succeeded",
                "payment_id": payment.id,
                "order_id": payment.order_id,
                "amount": payment.amount,
                "currency": payment.currency,
            }
            outbox_event = OutboxEventModel(
                id=str(uuid.uuid4()),
                event_type="payment.succeeded",
                payload=json.dumps(event_data),
            )
            db.add(outbox_event)

    return {
        "message": "Статус обновлен, событие поставлено в очередь на отправку",
        "payment_id": payload.payment_id,
        "new_status": payload.status.value,
    }
