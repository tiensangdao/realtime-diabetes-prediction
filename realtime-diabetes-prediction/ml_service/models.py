"""
ORM models cho ml_service — đọc/ghi predictions và health_readings
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, DateTime, Text,
    Numeric, Integer
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from ml_service.database import Base


class HealthReading(Base):
    """Mirror bảng health_readings để ml_service query lịch sử"""
    __tablename__ = "health_readings"

    reading_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    glucose = Column(Numeric(5, 2), nullable=True)
    systolic_bp = Column(Integer, nullable=True)
    diastolic_bp = Column(Integer, nullable=True)
    heart_rate = Column(Integer, nullable=True)
    bmi = Column(Numeric(4, 1), nullable=True)
    hba1c = Column(Numeric(3, 1), nullable=True)
    cholesterol = Column(Numeric(5, 2), nullable=True)
    creatinine = Column(Numeric(4, 2), nullable=True)
    input_method = Column(String(20), default="MANUAL")


class Prediction(Base):
    """Mirror bảng predictions để ml_service lưu kết quả"""
    __tablename__ = "predictions"

    prediction_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reading_id = Column(UUID(as_uuid=True), nullable=False)

    risk_score = Column(Numeric(4, 3), nullable=True)
    risk_level = Column(String(10), nullable=True)

    nephropathy_prob = Column(Numeric(4, 3), nullable=True)
    retinopathy_prob = Column(Numeric(4, 3), nullable=True)
    cardiac_prob = Column(Numeric(4, 3), nullable=True)
    neuropathy_prob = Column(Numeric(4, 3), nullable=True)

    model_version = Column(String(20), default="v1.0")
    inference_time_ms = Column(Integer, nullable=True)
    shap_values = Column(JSONB, nullable=True)               # giải thích SHAP
    created_at = Column(DateTime, default=datetime.utcnow)


class User(Base):
    """Mirror bảng users để ml_service lấy thông tin bệnh nhân"""
    __tablename__ = "users"

    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False)
    phone = Column(String(20), nullable=True)
    date_of_birth = Column(DateTime, nullable=True)          # dùng tính tuổi
    gender = Column(String(10), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PatientProfile(Base):
    """Mirror bảng patient_profiles để lấy diabetes_duration"""
    __tablename__ = "patient_profiles"

    profile_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), nullable=False)
    doctor_id = Column(UUID(as_uuid=True), nullable=True)
    diabetes_type = Column(String(20), nullable=True)
    diagnosis_date = Column(DateTime, nullable=True)         # tính diabetes_duration
    target_glucose = Column(Numeric(5, 2), nullable=True)
    medications = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
