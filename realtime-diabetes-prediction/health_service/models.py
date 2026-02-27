"""
ORM models cho health_service — bảng health_readings, predictions, alerts
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Boolean, DateTime, Text,
    Numeric, Integer
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from health_service.database import Base


class HealthReading(Base):
    """Bảng lưu chỉ số sức khỏe bệnh nhân"""
    __tablename__ = "health_readings"

    reading_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), nullable=False)   # FK → users.user_id
    timestamp = Column(DateTime, default=datetime.utcnow)

    glucose = Column(Numeric(5, 2), nullable=True)            # mg/dL
    systolic_bp = Column(Integer, nullable=True)              # mmHg
    diastolic_bp = Column(Integer, nullable=True)             # mmHg
    heart_rate = Column(Integer, nullable=True)               # bpm
    bmi = Column(Numeric(4, 1), nullable=True)
    hba1c = Column(Numeric(3, 1), nullable=True)              # %
    cholesterol = Column(Numeric(5, 2), nullable=True)        # mg/dL
    creatinine = Column(Numeric(4, 2), nullable=True)         # mg/dL
    input_method = Column(String(20), default="MANUAL")       # MANUAL/IOT/API

    # Quan hệ: một lần đo có một kết quả dự đoán
    prediction = relationship(
        "Prediction",
        back_populates="reading",
        uselist=False,
    )

    def __repr__(self):
        return f"<HealthReading patient_id={self.patient_id} ts={self.timestamp}>"


class Prediction(Base):
    """Bảng lưu kết quả dự đoán từ ML model"""
    __tablename__ = "predictions"

    prediction_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reading_id = Column(UUID(as_uuid=True), nullable=False)   # FK → health_readings

    risk_score = Column(Numeric(4, 3), nullable=True)         # 0.000 – 1.000
    risk_level = Column(String(10), nullable=True)            # LOW/MEDIUM/HIGH/CRITICAL

    nephropathy_prob = Column(Numeric(4, 3), nullable=True)   # nguy cơ bệnh thận
    retinopathy_prob = Column(Numeric(4, 3), nullable=True)   # nguy cơ bệnh mắt
    cardiac_prob = Column(Numeric(4, 3), nullable=True)       # nguy cơ tim mạch
    neuropathy_prob = Column(Numeric(4, 3), nullable=True)    # nguy cơ thần kinh

    model_version = Column(String(20), default="v1.0")
    inference_time_ms = Column(Integer, nullable=True)
    shap_values = Column(JSONB, nullable=True)                # giải thích model
    created_at = Column(DateTime, default=datetime.utcnow)

    # Quan hệ ngược về HealthReading
    reading = relationship("HealthReading", back_populates="prediction")

    # Quan hệ: một dự đoán có thể tạo nhiều cảnh báo
    alerts = relationship("Alert", back_populates="prediction")

    def __repr__(self):
        return f"<Prediction risk_score={self.risk_score} level={self.risk_level}>"


class Alert(Base):
    """Bảng lưu cảnh báo gửi cho bệnh nhân và bác sĩ"""
    __tablename__ = "alerts"

    alert_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prediction_id = Column(UUID(as_uuid=True), nullable=False)  # FK → predictions
    recipient_id = Column(UUID(as_uuid=True), nullable=False)   # FK → users

    alert_type = Column(String(20), nullable=True)    # PUSH/EMAIL/SMS
    severity = Column(String(20), nullable=True)       # WARNING/DANGER/CRITICAL
    message = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=datetime.utcnow)
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime, nullable=True)

    # Quan hệ ngược về Prediction
    prediction = relationship("Prediction", back_populates="alerts")

    def __repr__(self):
        return f"<Alert severity={self.severity} recipient={self.recipient_id}>"
