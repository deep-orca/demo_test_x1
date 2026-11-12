import os

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/payments_db"
)
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
QUEUE_NAME = "payment_events"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "my_super_secret_key_123")
