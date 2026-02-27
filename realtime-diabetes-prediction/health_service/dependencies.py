"""
Dependencies dùng chung cho health_service — JWT verify
"""
import os
from uuid import UUID

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt

JWT_SECRET = os.getenv("JWT_SECRET", "change-this-in-production")
JWT_ALGORITHM = "HS256"


def decode_jwt(token: str) -> dict:
    """Giải mã JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ hoặc đã hết hạn",
            headers={"WWW-Authenticate": "Bearer"},
        )


def lay_patient_id_tu_token(request: Request) -> UUID:
    """Lấy patient_id từ JWT token trong header"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiếu token xác thực",
        )
    token = auth[7:]
    payload = decode_jwt(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token thiếu thông tin user",
        )
    return UUID(user_id)
