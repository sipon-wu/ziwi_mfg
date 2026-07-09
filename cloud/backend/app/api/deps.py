from fastapi import Header, HTTPException
from typing import Optional


async def require_token(authorization: Optional[str] = Header(None)) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail={"code": "NO_TOKEN", "message": "Missing Authorization header"})
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail={"code": "BAD_TOKEN", "message": "Invalid token format"})
    return authorization[len("Bearer "):]
