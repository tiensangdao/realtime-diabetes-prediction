"""
Pydantic schemas cho ml_service — validate request/response ML
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, field_validator


# ─── Request schema ───────────────────────────────────────────────────────────

class DuDoanRequest(BaseModel):
    """Schema yêu cầu dự đoán nguy cơ"""
    patient_id: UUID
    reading_id: UUID

    # 8 chỉ số trực tiếp từ lần đo hiện tại
    glucose: Optional[float] = None
    systolic_bp: Optional[float] = None
    diastolic_bp: Optional[float] = None
    heart_rate: Optional[float] = None
    bmi: Optional[float] = None
    hba1c: Optional[float] = None
    cholesterol: Optional[float] = None
    creatinine: Optional[float] = None

    # Thông tin bệnh nhân (tính từ profile)
    age: Optional[float] = None
    diabetes_duration: Optional[float] = None  # số năm mắc bệnh

    # 5 đặc trưng lịch sử (tính từ 7 ngày gần nhất)
    glucose_7d_mean: Optional[float] = None
    bp_7d_mean: Optional[float] = None
    hba1c_trend: Optional[float] = None        # dương = đang xấu hơn
    glucose_variability: Optional[float] = None
    time_in_range: Optional[float] = None      # % glucose trong 70-180


# ─── Response schemas ─────────────────────────────────────────────────────────

class TopRiskFactor(BaseModel):
    """Một nhân tố nguy cơ có đóng góp SHAP"""
    feature: str
    contribution: float
    value: Optional[float] = None


class KetQuaDuDoan(BaseModel):
    """Schema kết quả dự đoán đầy đủ trả về"""
    prediction_id: str
    risk_score: float
    risk_level: str                          # LOW/MEDIUM/HIGH/CRITICAL
    complications: Dict[str, float]         # nguy cơ từng biến chứng
    top_risk_factors: List[TopRiskFactor]   # nhân tố quan trọng nhất
    advice: str
    inference_time_ms: int
    model_version: str = "v1.0"


class LichSuDuDoan(BaseModel):
    """Schema một bản ghi lịch sử dự đoán"""
    prediction_id: UUID
    reading_id: UUID
    risk_score: float
    risk_level: str
    nephropathy_prob: Optional[float] = None
    retinopathy_prob: Optional[float] = None
    cardiac_prob: Optional[float] = None
    neuropathy_prob: Optional[float] = None
    model_version: str
    inference_time_ms: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class XuHuong30Ngay(BaseModel):
    """Schema xu hướng nguy cơ 30 ngày gần nhất"""
    patient_id: str
    period_days: int = 30
    avg_risk_score: float
    max_risk_score: float
    min_risk_score: float
    trend_direction: str                     # INCREASING/DECREASING/STABLE
    data_points: List[Dict[str, Any]]        # chuỗi thời gian


class MLHealthResponse(BaseModel):
    """Schema kiểm tra trạng thái ML models"""
    status: str
    rf_model_loaded: bool
    lstm_model_loaded: bool
    scaler_loaded: bool
    model_version: str
    feature_count: int
