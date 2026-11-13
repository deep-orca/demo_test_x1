import secrets
from typing import Annotated
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

VALID_API_KEY = "xxx"


async def verify_api_key(
    api_key: Annotated[str | None, Security(api_key_header)],
) -> str:
    if not api_key or not secrets.compare_digest(api_key, VALID_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key",
        )
    return api_key
