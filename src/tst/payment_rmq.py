from typing import Annotated
import uuid
import hashlib
import json

from fastapi import APIRouter, HTTPException, Header, Response, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from tst.ioc import get_db
from tst.key import verify_api_key
from tst.models import PaymentModel, OutboxEventModel

router = APIRouter(prefix="/api/v1", dependencies=[Depends(verify_api_key)])


class PaymentCreate(BaseModel):
    order_id: str = Field(..., description="ID заказа")
    amount: float = Field(..., gt=0, description="Сумма платежа")
    currency: str = Field(default="RUB", description="Валюта")
    metadata: str = Field("", description="Метаданные")
    description: str = Field(default="", description="Описание")
    webhook: str = Field(default="http://0.0.0.0/", description="Webhook URL")


def get_payload_hash(payload: PaymentCreate) -> str:
    data_str = json.dumps(payload.model_dump(), sort_keys=True)
    return hashlib.sha256(data_str.encode()).hexdigest()


def format_response(payment: PaymentModel):
    return {
        "payment_id": payment.id,
        "status": payment.status,
        "created_at": payment.created_at,
    }


@router.post("/payments")
async def create_payment(
    payment: PaymentCreate,
    response: Response,
    idempotency_key: Annotated[str, Header()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    current_hash = get_payload_hash(payment)
    stmt = select(PaymentModel).where(PaymentModel.idempotency_key == idempotency_key)
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        if existing.request_hash != current_hash:
            raise HTTPException(
                status_code=422, detail="Ключ уже использовался с другими параметрами"
            )
        response.status_code = status.HTTP_202_ACCEPTED
        return format_response(existing)

    new_payment = PaymentModel(
        id=str(uuid.uuid4()),
        idempotency_key=idempotency_key,
        request_hash=current_hash,
        order_id=payment.order_id,
        amount=payment.amount,
        currency=payment.currency,
        description=payment.description,
        metajson=payment.metadata,
        webhook=payment.webhook,
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
        response.status_code = status.HTTP_202_ACCEPTED
        return format_response(new_payment)
    except IntegrityError:
        await db.rollback()
        existing = (await db.execute(stmt)).scalar_one()
        response.status_code = status.HTTP_202_ACCEPTED
        return format_response(existing)


@router.get("/payments/{payment_id}")
async def get_payment_status(
    payment_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    stmt = select(PaymentModel).where(PaymentModel.id == payment_id)
    payment = (await db.execute(stmt)).scalar_one_or_none()

    if not payment:
        raise HTTPException(status_code=404, detail="Платеж не найден")

    return payment
