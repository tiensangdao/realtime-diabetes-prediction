"""
Router quản lý chỉ số sức khỏe — lưu, đọc, tự động trigger dự đoán
"""
import logging
import os
from datetime import datetime
from typing import List
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from health_service.database import get_db
from health_service.models import HealthReading, Prediction, Alert
from health_service.schemas import (
    LuuChiSoRequest, HealthReadingResponse,
    ReadingWithPredictionResponse, PredictionResponse,
    TopRiskFactor,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["readings"])

# URL của ml_service
ML_SERVICE_URL = os.getenv("ML_SERVICE_URL", "http://ml-service:8002")


def _lay_jwt_tu_request(request) -> str:
    """Lấy JWT token từ Authorization header"""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return ""


async def _goi_ml_du_doan(
    chi_so: HealthReading,
    token: str,
    db: AsyncSession,
) -> dict:
    """Gọi ml_service để dự đoán nguy cơ"""
    # Lấy lịch sử 7 ngày gần nhất cho tính rolling features
    lich_su = await db.execute(
        select(HealthReading)
        .where(HealthReading.patient_id == chi_so.patient_id)
        .order_by(desc(HealthReading.timestamp))
        .limit(7)
    )
    danh_sach_lich_su = lich_su.scalars().all()

    # Tính rolling features từ lịch sử
    glucose_values = [
        float(r.glucose) for r in danh_sach_lich_su if r.glucose is not None
    ]
    bp_values = [
        float(r.systolic_bp) for r in danh_sach_lich_su if r.systolic_bp is not None
    ]
    hba1c_values = [
        float(r.hba1c) for r in danh_sach_lich_su if r.hba1c is not None
    ]

    glucose_7d_mean = sum(glucose_values) / len(glucose_values) if glucose_values else None
    bp_7d_mean = sum(bp_values) / len(bp_values) if bp_values else None

    # Xu hướng HbA1c: dương nghĩa là đang xấu hơn
    hba1c_trend = None
    if len(hba1c_values) >= 2:
        hba1c_trend = hba1c_values[0] - hba1c_values[-1]

    # Độ biến động glucose
    glucose_variability = None
    if len(glucose_values) > 1:
        mean_g = sum(glucose_values) / len(glucose_values)
        variance = sum((x - mean_g) ** 2 for x in glucose_values) / len(glucose_values)
        glucose_variability = variance ** 0.5

    # % glucose trong khoảng 70-180 mg/dL
    time_in_range = None
    if glucose_values:
        trong_khoang = sum(1 for g in glucose_values if 70 <= g <= 180)
        time_in_range = trong_khoang / len(glucose_values)

    # Payload gửi đến ml_service
    request_payload = {
        "patient_id": str(chi_so.patient_id),
        "reading_id": str(chi_so.reading_id),
        "glucose": float(chi_so.glucose) if chi_so.glucose else None,
        "systolic_bp": float(chi_so.systolic_bp) if chi_so.systolic_bp else None,
        "diastolic_bp": float(chi_so.diastolic_bp) if chi_so.diastolic_bp else None,
        "heart_rate": float(chi_so.heart_rate) if chi_so.heart_rate else None,
        "bmi": float(chi_so.bmi) if chi_so.bmi else None,
        "hba1c": float(chi_so.hba1c) if chi_so.hba1c else None,
        "cholesterol": float(chi_so.cholesterol) if chi_so.cholesterol else None,
        "creatinine": float(chi_so.creatinine) if chi_so.creatinine else None,
        "glucose_7d_mean": glucose_7d_mean,
        "bp_7d_mean": bp_7d_mean,
        "hba1c_trend": hba1c_trend,
        "glucose_variability": glucose_variability,
        "time_in_range": time_in_range,
    }

    # Gọi ml_service
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{ML_SERVICE_URL}/ml/predict",
            json=request_payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        response.raise_for_status()
        return response.json()


def _xay_dung_loi_khuyen(risk_level: str, risk_score: float) -> str:
    """Tạo lời khuyên dựa trên mức độ nguy cơ"""
    if risk_level == "CRITICAL":
        return (
            "NGUY HIỂM NGHIÊM TRỌNG! Liên hệ bác sĩ hoặc cấp cứu ngay lập tức. "
            "Không tự ý dùng thuốc."
        )
    elif risk_level == "HIGH":
        return (
            "Nguy cơ cao. Liên hệ bác sĩ ngay hôm nay. "
            "Kiểm tra chức năng thận, theo dõi huyết áp chặt chẽ."
        )
    elif risk_level == "MEDIUM":
        return (
            "Nguy cơ trung bình. Theo dõi chỉ số mỗi ngày. "
            "Giảm carbohydrate, tăng vận động, uống đủ nước."
        )
    else:
        return (
            "Nguy cơ thấp. Tiếp tục duy trì lối sống lành mạnh, "
            "kiểm tra định kỳ theo lịch hẹn với bác sĩ."
        )


@router.post(
    "/readings",
    response_model=ReadingWithPredictionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def luu_chi_so(
    request: Request,
    payload: LuuChiSoRequest,
    db: AsyncSession = Depends(get_db),
):
    """Lưu chỉ số sức khỏe mới và tự động trigger dự đoán ML"""
    # Lấy patient_id từ JWT token
    from health_service.dependencies import decode_jwt
    token = _lay_jwt_tu_request(request)
    jwt_payload = decode_jwt(token)
    patient_id = UUID(jwt_payload["sub"])

    # Tạo bản ghi chỉ số mới
    chi_so = HealthReading(
        patient_id=patient_id,
        glucose=payload.glucose,
        systolic_bp=payload.systolic_bp,
        diastolic_bp=payload.diastolic_bp,
        heart_rate=payload.heart_rate,
        bmi=payload.bmi,
        hba1c=payload.hba1c,
        cholesterol=payload.cholesterol,
        creatinine=payload.creatinine,
        input_method=payload.input_method,
    )
    db.add(chi_so)
    await db.commit()
    await db.refresh(chi_so)

    logger.info(f"Lưu chỉ số mới: reading_id={chi_so.reading_id} patient={patient_id}")

    # Kiểm tra cảnh báo khẩn cấp không cần model
    ket_qua_canh_bao_khan = None
    if chi_so.glucose:
        glucose_val = float(chi_so.glucose)
        if glucose_val > 300 or glucose_val < 60:
            logger.warning(
                f"Cảnh báo khẩn: glucose={glucose_val} patient={patient_id}"
            )
            # Gửi cảnh báo khẩn qua Celery task
            try:
                from health_service.tasks import gui_canh_bao_khan_cap
                gui_canh_bao_khan_cap.delay(
                    str(patient_id),
                    str(chi_so.reading_id),
                    glucose_val,
                )
            except Exception as e:
                logger.error(f"Lỗi gửi cảnh báo khẩn: {e}")

    # Gọi ML service để dự đoán
    du_doan_response = None
    try:
        ket_qua = await _goi_ml_du_doan(chi_so, token, db)

        # Lưu kết quả dự đoán vào database
        du_doan = Prediction(
            reading_id=chi_so.reading_id,
            risk_score=ket_qua["risk_score"],
            risk_level=ket_qua["risk_level"],
            nephropathy_prob=ket_qua["complications"].get("nephropathy"),
            retinopathy_prob=ket_qua["complications"].get("retinopathy"),
            cardiac_prob=ket_qua["complications"].get("cardiac"),
            neuropathy_prob=ket_qua["complications"].get("neuropathy"),
            model_version=ket_qua.get("model_version", "v1.0"),
            inference_time_ms=ket_qua.get("inference_time_ms"),
            shap_values=ket_qua.get("top_risk_factors"),
        )
        db.add(du_doan)
        await db.commit()
        await db.refresh(du_doan)

        # Gửi cảnh báo nếu nguy cơ cao
        if ket_qua["risk_score"] > 0.7:
            try:
                from health_service.tasks import gui_canh_bao_nguy_co_cao
                gui_canh_bao_nguy_co_cao.delay(
                    str(patient_id),
                    str(du_doan.prediction_id),
                    ket_qua["risk_score"],
                    ket_qua["risk_level"],
                )
            except Exception as e:
                logger.error(f"Lỗi gửi cảnh báo nguy cơ cao: {e}")

        # Xây dựng response
        top_factors = [
            TopRiskFactor(
                feature=f.get("feature", ""),
                contribution=f.get("contribution", 0.0),
                value=f.get("value"),
            )
            for f in (ket_qua.get("top_risk_factors") or [])
        ]

        du_doan_response = PredictionResponse(
            prediction_id=du_doan.prediction_id,
            reading_id=du_doan.reading_id,
            risk_score=float(du_doan.risk_score),
            risk_level=du_doan.risk_level,
            complications={
                "nephropathy": float(du_doan.nephropathy_prob or 0),
                "retinopathy": float(du_doan.retinopathy_prob or 0),
                "cardiac": float(du_doan.cardiac_prob or 0),
                "neuropathy": float(du_doan.neuropathy_prob or 0),
            },
            top_risk_factors=top_factors,
            advice=_xay_dung_loi_khuyen(du_doan.risk_level, float(du_doan.risk_score)),
            inference_time_ms=du_doan.inference_time_ms,
            created_at=du_doan.created_at,
        )

    except Exception as e:
        logger.error(f"Lỗi khi gọi ML service: {e}")
        # Tiếp tục trả về chỉ số dù dự đoán thất bại

    return ReadingWithPredictionResponse(
        reading=HealthReadingResponse.model_validate(chi_so),
        prediction=du_doan_response,
    )


@router.get("/readings/{patient_id}", response_model=List[HealthReadingResponse])
async def lay_lich_su_chi_so(
    patient_id: UUID,
    skip: int = 0,
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
):
    """Lấy lịch sử chỉ số sức khỏe của bệnh nhân"""
    ket_qua = await db.execute(
        select(HealthReading)
        .where(HealthReading.patient_id == patient_id)
        .order_by(desc(HealthReading.timestamp))
        .offset(skip)
        .limit(limit)
    )
    danh_sach = ket_qua.scalars().all()

    if not danh_sach:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lịch sử cho bệnh nhân {patient_id}",
        )

    return [HealthReadingResponse.model_validate(r) for r in danh_sach]


@router.get(
    "/readings/{patient_id}/latest",
    response_model=ReadingWithPredictionResponse,
)
async def lay_chi_so_moi_nhat(
    patient_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Lấy lần đo mới nhất kèm kết quả dự đoán"""
    # Lấy bản ghi mới nhất
    ket_qua = await db.execute(
        select(HealthReading)
        .where(HealthReading.patient_id == patient_id)
        .order_by(desc(HealthReading.timestamp))
        .limit(1)
    )
    chi_so = ket_qua.scalar_one_or_none()

    if not chi_so:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chưa có lần đo nào cho bệnh nhân {patient_id}",
        )

    # Lấy dự đoán tương ứng
    ket_qua_du_doan = await db.execute(
        select(Prediction)
        .where(Prediction.reading_id == chi_so.reading_id)
    )
    du_doan = ket_qua_du_doan.scalar_one_or_none()

    du_doan_response = None
    if du_doan:
        du_doan_response = PredictionResponse(
            prediction_id=du_doan.prediction_id,
            reading_id=du_doan.reading_id,
            risk_score=float(du_doan.risk_score or 0),
            risk_level=du_doan.risk_level or "UNKNOWN",
            complications={
                "nephropathy": float(du_doan.nephropathy_prob or 0),
                "retinopathy": float(du_doan.retinopathy_prob or 0),
                "cardiac": float(du_doan.cardiac_prob or 0),
                "neuropathy": float(du_doan.neuropathy_prob or 0),
            },
            top_risk_factors=[],
            advice=_xay_dung_loi_khuyen(
                du_doan.risk_level or "LOW",
                float(du_doan.risk_score or 0),
            ),
            inference_time_ms=du_doan.inference_time_ms,
            created_at=du_doan.created_at,
        )

    return ReadingWithPredictionResponse(
        reading=HealthReadingResponse.model_validate(chi_so),
        prediction=du_doan_response,
    )
