"""
Pydantic schemas cho health_service — validate request/response
"""
from datetime import datetime
from typing import Optional, List, Any, Dict
from uuid import UUID
from pydantic import BaseModel, field_validator


# ─── Health Reading schemas ───────────────────────────────────────────────────

class LuuChiSoRequest(BaseModel):
    """Schema nhập chỉ số sức khỏe mới"""
    glucose: Optional[float] = None          # mg/dL
    systolic_bp: Optional[int] = None        # mmHg tâm thu
    diastolic_bp: Optional[int] = None       # mmHg tâm trương
    heart_rate: Optional[int] = None         # nhịp tim bpm
    bmi: Optional[float] = None
    hba1c: Optional[float] = None            # %
    cholesterol: Optional[float] = None      # mg/dL
    creatinine: Optional[float] = None       # mg/dL
    input_method: str = "MANUAL"

    @field_validator("glucose")
    @classmethod
    def validate_glucose(cls, v: Optional[float]) -> Optional[float]:
        """Kiểm tra glucose nằm trong khoảng y tế hợp lệ"""
        if v is not None and (v < 0 or v > 2000):
            raise ValueError("Glucose phải trong khoảng 0–2000 mg/dL")
        return v

    @field_validator("systolic_bp")
    @classmethod
    def validate_systolic(cls, v: Optional[int]) -> Optional[int]:
        """Kiểm tra huyết áp tâm thu hợp lệ"""
        if v is not None and (v < 0 or v > 300):
            raise ValueError("Huyết áp tâm thu phải trong khoảng 0–300 mmHg")
        return v

    @field_validator("hba1c")
    @classmethod
    def validate_hba1c(cls, v: Optional[float]) -> Optional[float]:
        """Kiểm tra HbA1c hợp lệ"""
        if v is not None and (v < 0 or v > 20):
            raise ValueError("HbA1c phải trong khoảng 0–20%")
        return v

    @field_validator("input_method")
    @classmethod
    def validate_input_method(cls, v: str) -> str:
        """Kiểm tra nguồn nhập liệu hợp lệ"""
        if v not in ("MANUAL", "IOT", "API"):
            raise ValueError("input_method phải là MANUAL, IOT hoặc API")
        return v


class HealthReadingResponse(BaseModel):
    """Schema trả về chỉ số sức khỏe"""
    reading_id: UUID
    patient_id: UUID
    timestamp: datetime
    glucose: Optional[float] = None
    systolic_bp: Optional[int] = None
    diastolic_bp: Optional[int] = None
    heart_rate: Optional[int] = None
    bmi: Optional[float] = None
    hba1c: Optional[float] = None
    cholesterol: Optional[float] = None
    creatinine: Optional[float] = None
    input_method: str

    model_config = {"from_attributes": True}


# ─── Prediction schemas ───────────────────────────────────────────────────────

class TopRiskFactor(BaseModel):
    """Schema cho một nhân tố nguy cơ"""
    feature: str
    contribution: float
    value: Optional[float] = None


class PredictionResponse(BaseModel):
    """Schema trả về kết quả dự đoán đầy đủ"""
    prediction_id: UUID
    reading_id: UUID
    risk_score: float
    risk_level: str
    complications: Dict[str, float]         # nguy cơ từng biến chứng
    top_risk_factors: List[TopRiskFactor]   # nhân tố ảnh hưởng nhất
    advice: str                             # lời khuyên cho bệnh nhân
    inference_time_ms: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ReadingWithPredictionResponse(BaseModel):
    """Schema trả về chỉ số kèm kết quả dự đoán"""
    reading: HealthReadingResponse
    prediction: Optional[PredictionResponse] = None


# ─── Alert schemas ────────────────────────────────────────────────────────────

class AlertResponse(BaseModel):
    """Schema trả về cảnh báo"""
    alert_id: UUID
    prediction_id: UUID
    recipient_id: UUID
    alert_type: Optional[str] = None
    severity: Optional[str] = None
    message: Optional[str] = None
    sent_at: datetime
    is_read: bool
    read_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DanhSachAlertResponse(BaseModel):
    """Schema trả về danh sách cảnh báo"""
    total: int
    unread_count: int
    alerts: List[AlertResponse]
