"""
Router xử lý đăng ký, đăng nhập, hồ sơ người dùng
"""
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from auth_service.database import get_db
from auth_service.models import User, PatientProfile
from auth_service.schemas import (
    DangKyRequest, DangKyResponse,
    DangNhapRequest, TokenResponse,
    CapNhatHoSoRequest, UserResponse,
    PatientProfileRequest, PatientProfileResponse,
)
from auth_service.dependencies import (
    hash_password, verify_password, encode_jwt,
    lay_user_hien_tai, JWT_EXPIRE_MINUTES,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=DangKyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def dang_ky(payload: DangKyRequest, db: AsyncSession = Depends(get_db)):
    """Đăng ký tài khoản mới"""
    # Kiểm tra email đã tồn tại chưa
    ket_qua = await db.execute(
        select(User).where(User.email == payload.email)
    )
    if ket_qua.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email đã được sử dụng",
        )

    # Tạo user mới
    nguoi_dung = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        phone=payload.phone,
        date_of_birth=payload.date_of_birth,
        gender=payload.gender,
    )
    db.add(nguoi_dung)
    await db.commit()
    await db.refresh(nguoi_dung)

    logger.info(f"Đăng ký thành công: {nguoi_dung.email} role={nguoi_dung.role}")

    return DangKyResponse(
        message="Đăng ký thành công",
        user=UserResponse.model_validate(nguoi_dung),
    )


@router.post("/login", response_model=TokenResponse)
async def dang_nhap(payload: DangNhapRequest, db: AsyncSession = Depends(get_db)):
    """Đăng nhập và nhận JWT token"""
    # Tìm user theo email
    ket_qua = await db.execute(
        select(User).where(User.email == payload.email)
    )
    nguoi_dung = ket_qua.scalar_one_or_none()

    # Xác minh mật khẩu
    if not nguoi_dung or not verify_password(payload.password, nguoi_dung.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email hoặc mật khẩu không đúng",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not nguoi_dung.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản đã bị vô hiệu hóa",
        )

    # Tạo JWT token
    token = encode_jwt(
        user_id=str(nguoi_dung.user_id),
        email=nguoi_dung.email,
        role=nguoi_dung.role,
    )

    logger.info(f"Đăng nhập: {nguoi_dung.email}")

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=JWT_EXPIRE_MINUTES * 60,
        user=UserResponse.model_validate(nguoi_dung),
    )


@router.post("/logout", status_code=status.HTTP_200_OK)
async def dang_xuat(nguoi_dung: User = Depends(lay_user_hien_tai)):
    """Đăng xuất — client tự xóa token"""
    logger.info(f"Đăng xuất: {nguoi_dung.email}")
    return {"message": "Đăng xuất thành công"}


@router.get("/me", response_model=UserResponse)
async def lay_thong_tin_ca_nhan(nguoi_dung: User = Depends(lay_user_hien_tai)):
    """Lấy thông tin user hiện tại"""
    return UserResponse.model_validate(nguoi_dung)


@router.put("/me", response_model=UserResponse)
async def cap_nhat_ho_so(
    payload: CapNhatHoSoRequest,
    nguoi_dung: User = Depends(lay_user_hien_tai),
    db: AsyncSession = Depends(get_db),
):
    """Cập nhật hồ sơ cá nhân"""
    # Chỉ cập nhật các trường được gửi lên
    du_lieu_cap_nhat = payload.model_dump(exclude_none=True)

    if not du_lieu_cap_nhat:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không có dữ liệu nào để cập nhật",
        )

    await db.execute(
        update(User)
        .where(User.user_id == nguoi_dung.user_id)
        .values(**du_lieu_cap_nhat)
    )
    await db.commit()
    await db.refresh(nguoi_dung)

    logger.info(f"Cập nhật hồ sơ: {nguoi_dung.email}")

    return UserResponse.model_validate(nguoi_dung)


@router.post(
    "/profile",
    response_model=PatientProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def tao_ho_so_benh_nhan(
    payload: PatientProfileRequest,
    nguoi_dung: User = Depends(lay_user_hien_tai),
    db: AsyncSession = Depends(get_db),
):
    """Tạo hoặc cập nhật hồ sơ bệnh nhân"""
    if nguoi_dung.role != "patient":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chỉ bệnh nhân mới có hồ sơ bệnh án",
        )

    # Kiểm tra đã có hồ sơ chưa
    ket_qua = await db.execute(
        select(PatientProfile).where(PatientProfile.patient_id == nguoi_dung.user_id)
    )
    ho_so_cu = ket_qua.scalar_one_or_none()

    if ho_so_cu:
        # Cập nhật hồ sơ hiện có
        du_lieu = payload.model_dump(exclude_none=True)
        for key, value in du_lieu.items():
            setattr(ho_so_cu, key, value)
        await db.commit()
        await db.refresh(ho_so_cu)
        return PatientProfileResponse.model_validate(ho_so_cu)

    # Tạo hồ sơ mới
    ho_so = PatientProfile(
        patient_id=nguoi_dung.user_id,
        doctor_id=payload.doctor_id,
        diabetes_type=payload.diabetes_type,
        diagnosis_date=payload.diagnosis_date,
        target_glucose=payload.target_glucose,
        medications=payload.medications,
    )
    db.add(ho_so)
    await db.commit()
    await db.refresh(ho_so)

    return PatientProfileResponse.model_validate(ho_so)
