"""
Dependencies dùng chung cho auth_service — JWT decode, lấy user hiện tại
"""
import os
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from auth_service.database import get_db
from auth_service.models import User

# Cấu hình mã hóa mật khẩu
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Cấu hình JWT
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

# Bearer token extractor
bearer_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    """Mã hóa mật khẩu bằng bcrypt"""
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Xác minh mật khẩu"""
    return pwd_context.verify(plain, hashed)


def encode_jwt(user_id: str, email: str, role: str) -> str:
    """Tạo JWT token cho user"""
    expire = datetime.utcnow() + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict:
    """Giải mã và xác minh JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không hợp lệ hoặc đã hết hạn",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def lay_user_hien_tai(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency: lấy thông tin user từ JWT token"""
    payload = decode_jwt(credentials.credentials)
    user_id = payload.get("sub")

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token thiếu thông tin user",
        )

    # Lấy user từ database
    result = await db.execute(
        select(User).where(User.user_id == UUID(user_id))
    )
    nguoi_dung = result.scalar_one_or_none()

    if not nguoi_dung:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy user",
        )

    if not nguoi_dung.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản đã bị vô hiệu hóa",
        )

    return nguoi_dung


async def yeu_cau_bac_si(
    nguoi_dung: User = Depends(lay_user_hien_tai),
) -> User:
    """Dependency: chỉ cho phép bác sĩ hoặc admin"""
    if nguoi_dung.role not in ("doctor", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ bác sĩ hoặc admin mới có quyền này",
        )
    return nguoi_dung


async def yeu_cau_admin(
    nguoi_dung: User = Depends(lay_user_hien_tai),
) -> User:
    """Dependency: chỉ cho phép admin"""
    if nguoi_dung.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ admin mới có quyền này",
        )
    return nguoi_dung
