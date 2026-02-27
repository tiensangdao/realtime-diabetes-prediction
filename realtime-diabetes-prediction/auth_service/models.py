"""
ORM models cho auth_service — bảng users và patient_profiles
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, DateTime, Date, Text,
    Numeric, Integer, CheckConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from auth_service.database import Base


class User(Base):
    """Bảng người dùng — bệnh nhân, bác sĩ, admin"""
    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(
        String(20),
        CheckConstraint("role IN ('patient','doctor','admin')"),
        nullable=False
    )
    phone = Column(String(20), nullable=True)
    date_of_birth = Column(Date, nullable=True)
    gender = Column(String(10), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Quan hệ: bệnh nhân có một hồ sơ
    patient_profile = relationship(
        "PatientProfile",
        foreign_keys="PatientProfile.patient_id",
        back_populates="patient",
        uselist=False,
    )

    def __repr__(self):
        return f"<User {self.email} role={self.role}>"


class PatientProfile(Base):
    """Hồ sơ chi tiết bệnh nhân tiểu đường"""
    __tablename__ = "patient_profiles"

    profile_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), nullable=False)   # FK → users.user_id
    doctor_id = Column(UUID(as_uuid=True), nullable=True)     # FK → users.user_id

    diabetes_type = Column(String(20), nullable=True)          # 'Type1','Type2','Gestational'
    diagnosis_date = Column(Date, nullable=True)
    target_glucose = Column(Numeric(5, 2), nullable=True)
    medications = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Quan hệ ngược về User
    patient = relationship(
        "User",
        foreign_keys=[patient_id],
        back_populates="patient_profile",
        primaryjoin="PatientProfile.patient_id == User.user_id",
    )

    def __repr__(self):
        return f"<PatientProfile patient_id={self.patient_id}>"
