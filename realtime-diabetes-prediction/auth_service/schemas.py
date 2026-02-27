"""
Pydantic schemas cho auth_service — validate request/response
"""
from datetime import date, datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr, field_validator


# ─── Request schemas ─────────────────────────────────────────────────────────

class DangKyRequest(BaseModel):
    """Schema đăng ký tài khoản mới"""
    email: EmailStr
    password: str
    full_name: str
    role: str = "patient"                  # mặc định là bệnh nhân
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """Kiểm tra role hợp lệ"""
        if v not in ("patient", "doctor", "admin"):
            raise ValueError("role phải là patient, doctor hoặc admin")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """Kiểm tra mật khẩu đủ mạnh"""
        if len(v) < 6:
            raise ValueError("Mật khẩu phải có ít nhất 6 ký tự")
        return v


class DangNhapRequest(BaseModel):
    """Schema đăng nhập"""
    email: EmailStr
    password: str


class CapNhatHoSoRequest(BaseModel):
    """Schema cập nhật hồ sơ cá nhân"""
    full_name: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None


# ─── Response schemas ─────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    """Schema trả về thông tin user"""
    user_id: UUID
    email: str
    full_name: str
    role: str
    phone: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """Schema trả về JWT token sau đăng nhập"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int                    # giây
    user: UserResponse


class DangKyResponse(BaseModel):
    """Schema phản hồi sau đăng ký thành công"""
    message: str
    user: UserResponse


# ─── Patient profile schemas ──────────────────────────────────────────────────

class PatientProfileRequest(BaseModel):
    """Schema tạo/cập nhật hồ sơ bệnh nhân"""
    doctor_id: Optional[UUID] = None
    diabetes_type: Optional[str] = None
    diagnosis_date: Optional[date] = None
    target_glucose: Optional[float] = None
    medications: Optional[str] = None

    @field_validator("diabetes_type")
    @classmethod
    def validate_diabetes_type(cls, v: Optional[str]) -> Optional[str]:
        """Kiểm tra loại tiểu đường hợp lệ"""
        if v and v not in ("Type1", "Type2", "Gestational"):
            raise ValueError("diabetes_type phải là Type1, Type2 hoặc Gestational")
        return v


class PatientProfileResponse(BaseModel):
    """Schema trả về hồ sơ bệnh nhân"""
    profile_id: UUID
    patient_id: UUID
    doctor_id: Optional[UUID] = None
    diabetes_type: Optional[str] = None
    diagnosis_date: Optional[date] = None
    target_glucose: Optional[float] = None
    medications: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
