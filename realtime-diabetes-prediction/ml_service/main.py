"""
FastAPI app chính cho ml_service — cổng 8002
"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import List
from uuid import UUID

from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ml_service.database import get_db
from ml_service.models import HealthReading, Prediction, User, PatientProfile
from ml_service.predictor import bo_du_doan
from ml_service.explainer import bo_giai_thich
from ml_service.schemas import (
    DuDoanRequest, KetQuaDuDoan,
    LichSuDuDoan, XuHuong30Ngay, MLHealthResponse,
    TopRiskFactor,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Tải models khi khởi động service"""
    logger.info("ML Service đang tải models...")
    ok = bo_du_doan.tai_models()

    if ok:
        # Khởi tạo SHAP explainer với RF model
        rf = bo_du_doan.model_manager.rf_model
        if rf is not None:
            bo_giai_thich.khoi_tao(rf)
        logger.info("ML Service đã sẵn sàng")
    else:
        logger.warning("Models chưa được train — chạy ml_service/train.py trước")

    yield
    logger.info("ML Service đã tắt")


app = FastAPI(
    title="ML Service",
    description="Dịch vụ dự đoán nguy cơ biến chứng tiểu đường",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def xu_ly_loi(request: Request, exc: Exception):
    """Bắt tất cả lỗi không xử lý"""
    logger.error(f"Lỗi không xử lý: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Lỗi ML service nội bộ"},
    )


def _xay_dung_loi_khuyen(risk_level: str) -> str:
    """Tạo lời khuyên từ mức nguy cơ"""
    loi_khuyen = {
        "CRITICAL": (
            "NGUY HIỂM NGHIÊM TRỌNG! Gọi cấp cứu hoặc đến bệnh viện ngay. "
            "Không tự ý thay đổi thuốc."
        ),
        "HIGH": (
            "Nguy cơ cao. Liên hệ bác sĩ ngay hôm nay. "
            "Kiểm tra chức năng thận, theo dõi huyết áp chặt chẽ."
        ),
        "MEDIUM": (
            "Nguy cơ trung bình. Theo dõi hàng ngày. "
            "Điều chỉnh chế độ ăn, tăng hoạt động thể chất."
        ),
        "LOW": (
            "Nguy cơ thấp. Duy trì lối sống lành mạnh. "
            "Kiểm tra định kỳ theo lịch bác sĩ."
        ),
    }
    return loi_khuyen.get(risk_level, "Theo dõi sức khỏe đều đặn.")


async def _lay_lich_su_7_ngay(
    patient_id: UUID, db: AsyncSession
) -> List[dict]:
    """Lấy lịch sử 7 ngày gần nhất của bệnh nhân"""
    ket_qua = await db.execute(
        select(HealthReading)
        .where(HealthReading.patient_id == patient_id)
        .order_by(desc(HealthReading.timestamp))
        .limit(7)
    )
    danh_sach = ket_qua.scalars().all()
    return [
        {
            "glucose": float(r.glucose) if r.glucose else None,
            "systolic_bp": float(r.systolic_bp) if r.systolic_bp else None,
            "diastolic_bp": float(r.diastolic_bp) if r.diastolic_bp else None,
            "heart_rate": float(r.heart_rate) if r.heart_rate else None,
            "bmi": float(r.bmi) if r.bmi else None,
            "hba1c": float(r.hba1c) if r.hba1c else None,
            "cholesterol": float(r.cholesterol) if r.cholesterol else None,
            "creatinine": float(r.creatinine) if r.creatinine else None,
        }
        for r in danh_sach
    ]


async def _lay_thong_tin_benh_nhan(
    patient_id: UUID, db: AsyncSession
) -> dict:
    """Lấy tuổi và thời gian mắc bệnh từ profile"""
    # Lấy thông tin user
    user_result = await db.execute(
        select(User).where(User.user_id == patient_id)
    )
    user = user_result.scalar_one_or_none()

    # Lấy hồ sơ bệnh nhân
    profile_result = await db.execute(
        select(PatientProfile).where(PatientProfile.patient_id == patient_id)
    )
    profile = profile_result.scalar_one_or_none()

    age = None
    if user and user.date_of_birth:
        age = (datetime.utcnow().date() - user.date_of_birth).days / 365.25

    diabetes_duration = None
    if profile and profile.diagnosis_date:
        diag_date = profile.diagnosis_date
        if hasattr(diag_date, 'date'):
            diag_date = diag_date.date()
        diabetes_duration = (datetime.utcnow().date() - diag_date).days / 365.25

    return {"age": age, "diabetes_duration": diabetes_duration}


@app.post("/ml/predict", response_model=KetQuaDuDoan)
async def du_doan_nguy_co(
    payload: DuDoanRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Dự đoán nguy cơ biến chứng từ chỉ số sức khỏe"""
    if not bo_du_doan.da_san_sang:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ML models chưa sẵn sàng — vui lòng train models trước",
        )

    # Lấy thông tin bệnh nhân từ database
    thong_tin_bn = await _lay_thong_tin_benh_nhan(payload.patient_id, db)

    # Lấy lịch sử 7 ngày
    lich_su = await _lay_lich_su_7_ngay(payload.patient_id, db)

    # Xây dựng dict features đầy đủ 15 chiều
    features = {
        "glucose": payload.glucose,
        "systolic_bp": payload.systolic_bp,
        "diastolic_bp": payload.diastolic_bp,
        "heart_rate": payload.heart_rate,
        "bmi": payload.bmi,
        "hba1c": payload.hba1c,
        "cholesterol": payload.cholesterol,
        "creatinine": payload.creatinine,
        "age": payload.age or thong_tin_bn.get("age"),
        "diabetes_duration": payload.diabetes_duration or thong_tin_bn.get("diabetes_duration"),
        "glucose_7d_mean": payload.glucose_7d_mean,
        "bp_7d_mean": payload.bp_7d_mean,
        "hba1c_trend": payload.hba1c_trend,
        "glucose_variability": payload.glucose_variability,
        "time_in_range": payload.time_in_range,
    }

    # Thêm lịch sử 7 ngày vào features để tính rolling nếu thiếu
    if lich_su and not features["glucose_7d_mean"]:
        glucose_vals = [r["glucose"] for r in lich_su if r.get("glucose")]
        if glucose_vals:
            features["glucose_7d_mean"] = sum(glucose_vals) / len(glucose_vals)

    try:
        # Chạy dự đoán ensemble
        ket_qua = bo_du_doan.du_doan_nguy_co(features, lich_su)

        # Tính SHAP explanation
        features_scaled = bo_du_doan.model_manager.preprocessor.chuan_bi_inference(features)
        top_factors_raw = bo_giai_thich.giai_thich(features_scaled, features)

        top_factors = [
            TopRiskFactor(
                feature=f["feature"],
                contribution=f["contribution"],
                value=f.get("value"),
            )
            for f in top_factors_raw
        ]

        return KetQuaDuDoan(
            prediction_id=ket_qua["prediction_id"],
            risk_score=ket_qua["risk_score"],
            risk_level=ket_qua["risk_level"],
            complications=ket_qua["complications"],
            top_risk_factors=top_factors,
            advice=_xay_dung_loi_khuyen(ket_qua["risk_level"]),
            inference_time_ms=ket_qua["inference_time_ms"],
            model_version=ket_qua["model_version"],
        )

    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except Exception as e:
        logger.error(f"Lỗi dự đoán: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Lỗi trong quá trình dự đoán",
        )


@app.get("/ml/predictions/{patient_id}", response_model=List[LichSuDuDoan])
async def lay_lich_su_du_doan(
    patient_id: UUID,
    skip: int = 0,
    limit: int = 30,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Lấy lịch sử dự đoán của bệnh nhân"""
    # Lấy tất cả readings của bệnh nhân
    readings_result = await db.execute(
        select(HealthReading.reading_id)
        .where(HealthReading.patient_id == patient_id)
        .order_by(desc(HealthReading.timestamp))
        .offset(skip)
        .limit(limit)
    )
    reading_ids = [r[0] for r in readings_result.fetchall()]

    if not reading_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy lịch sử dự đoán cho bệnh nhân {patient_id}",
        )

    # Lấy predictions tương ứng
    pred_result = await db.execute(
        select(Prediction)
        .where(Prediction.reading_id.in_(reading_ids))
        .order_by(desc(Prediction.created_at))
    )
    predictions = pred_result.scalars().all()

    return [LichSuDuDoan.model_validate(p) for p in predictions]


@app.get("/ml/predictions/{patient_id}/trend", response_model=XuHuong30Ngay)
async def lay_xu_huong_30_ngay(
    patient_id: UUID,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
):
    """Lấy xu hướng nguy cơ 30 ngày gần nhất"""
    # Thời điểm 30 ngày trước
    ngay_bat_dau = datetime.utcnow() - timedelta(days=30)

    # Lấy readings trong 30 ngày
    readings_result = await db.execute(
        select(HealthReading)
        .where(
            HealthReading.patient_id == patient_id,
            HealthReading.timestamp >= ngay_bat_dau,
        )
        .order_by(HealthReading.timestamp)
    )
    readings = readings_result.scalars().all()

    if not readings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không có dữ liệu 30 ngày cho bệnh nhân {patient_id}",
        )

    # Lấy predictions tương ứng
    reading_ids = [r.reading_id for r in readings]
    pred_result = await db.execute(
        select(Prediction)
        .where(Prediction.reading_id.in_(reading_ids))
        .order_by(Prediction.created_at)
    )
    predictions = pred_result.scalars().all()

    if not predictions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chưa có kết quả dự đoán trong 30 ngày",
        )

    # Tính toán xu hướng
    scores = [float(p.risk_score) for p in predictions]
    avg_score = sum(scores) / len(scores)
    max_score = max(scores)
    min_score = min(scores)

    # Xác định chiều xu hướng
    if len(scores) >= 2:
        dau_ky = sum(scores[:len(scores) // 2]) / (len(scores) // 2)
        cuoi_ky = sum(scores[len(scores) // 2:]) / (len(scores) - len(scores) // 2)
        if cuoi_ky - dau_ky > 0.05:
            xu_huong = "INCREASING"
        elif dau_ky - cuoi_ky > 0.05:
            xu_huong = "DECREASING"
        else:
            xu_huong = "STABLE"
    else:
        xu_huong = "STABLE"

    # Xây dựng data points
    data_points = [
        {
            "date": p.created_at.isoformat(),
            "risk_score": float(p.risk_score),
            "risk_level": p.risk_level,
        }
        for p in predictions
    ]

    return XuHuong30Ngay(
        patient_id=str(patient_id),
        period_days=30,
        avg_risk_score=round(avg_score, 3),
        max_risk_score=round(max_score, 3),
        min_risk_score=round(min_score, 3),
        trend_direction=xu_huong,
        data_points=data_points,
    )


@app.get("/ml/health", response_model=MLHealthResponse)
async def kiem_tra_model():
    """Kiểm tra trạng thái ML models"""
    mm = bo_du_doan.model_manager
    return MLHealthResponse(
        status="ok" if mm._rf_loaded else "not_ready",
        rf_model_loaded=mm._rf_loaded,
        lstm_model_loaded=mm._lstm_loaded,
        scaler_loaded=mm.preprocessor._da_fit,
        model_version=mm.model_version,
        feature_count=len(__import__("ml_service.preprocessor", fromlist=["FEATURE_NAMES"]).FEATURE_NAMES),
    )


@app.get("/health")
async def kiem_tra_service():
    """Kiểm tra service đang chạy"""
    return {"status": "ok", "service": "ml_service"}
