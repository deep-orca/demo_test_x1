import uuid
import hashlib
import json

from fastapi import APIRouter, HTTPException, Header, Response, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from typing_extensions import Any

from tst.ioc import get_db
from tst.models import PaymentModel, OutboxEventModel

router = APIRouter()


class PaymentCreate(BaseModel):
    order_id: str = Field(..., description="ID заказа")
    amount: float = Field(..., gt=0, description="Сумма платежа")
    currency: str = Field(default="RUB", description="Валюта")


# class PaymentWebhook(BaseModel):
#     payment_id: str
#     status: PaymentStatus


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


@router.post("/payments")
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
        await db.flush()
        await db.refresh(new_payment)

        event_data = {
            "event": "payment.pending",
            "payment_id": new_payment.id,
            "order_id": payment.order_id,
            "amount": payment.amount,
            "currency": payment.currency,
        }
        outbox_event = OutboxEventModel(
            id=str(uuid.uuid4()),
            event_type=event_data["event"],
            payload=json.dumps(event_data),
        )
        db.add(outbox_event)

        await db.flush()
        await db.commit()
        response.status_code = status.HTTP_201_CREATED
        return format_response(new_payment, is_duplicate=False)
    except IntegrityError:
        await db.rollback()
        existing = (await db.execute(stmt)).scalar_one()
        response.status_code = status.HTTP_200_OK
        return format_response(existing, is_duplicate=True)


# @router.get("/payments/{payment_id}")
# async def get_payment_status(payment_id: str, db: AsyncSession = Depends(get_db)):
#     stmt = select(PaymentModel).where(PaymentModel.id == payment_id)
#     payment = (await db.execute(stmt)).scalar_one_or_none()
#
#     if not payment:
#         raise HTTPException(status_code=404, detail="Платеж не найден")
#     return format_response(payment)


# @router.post("/payments/webhook")
# async def payment_webhook(
#     payload: PaymentWebhook,
#     x_webhook_secret: str = Header(None),
#     db: AsyncSession = Depends(get_db),
# ):
#     if x_webhook_secret != WEBHOOK_SECRET:
#         raise HTTPException(status_code=403, detail="Неверный секретный ключ")
#
#     async with db.begin():
#         stmt = (
#             select(PaymentModel)
#             .where(PaymentModel.id == payload.payment_id)
#             .with_for_update()
#         )
#     return {
#         "message": "Статус обновлен, событие поставлено в очередь на отправку",
#         "payment_id": payload.payment_id,
#         "new_status": payload.status.value,
#     }
