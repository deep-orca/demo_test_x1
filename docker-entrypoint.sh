#!/bin/sh
set -e

echo "Запуск приложения..."
exec uvicorn tst.payment_rmq:app --host 0.0.0.0 --port 8000
