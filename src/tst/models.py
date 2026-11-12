from enum import Enum
from datetime import datetime, timezone
from typing import final
from sqlalchemy import String, Float, Boolean, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PaymentStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    CANCELED = "canceled"


@final
class PaymentModel(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(
        String, unique=True, index=True, nullable=False
    )
    request_hash: Mapped[str] = mapped_column(String, nullable=False)
    order_id: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String, default="RUB")
    description: Mapped[str] = mapped_column(String, default="")
    metajson: Mapped[str] = mapped_column(String, default="")
    webhook: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default=PaymentStatus.PENDING.value)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=True,
    )


@final
class OutboxEventModel(Base):
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[str] = mapped_column(String, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
