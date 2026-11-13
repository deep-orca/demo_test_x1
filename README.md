## First run
```bash
docker compose up -d postgres
alembic upgrade head
docker compose up --build
```

## Regular
```bash
docker compose up --build
```

## Info
API Key: xxx

