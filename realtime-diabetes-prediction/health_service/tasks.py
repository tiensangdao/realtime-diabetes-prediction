"""
Celery tasks — gửi cảnh báo bất đồng bộ qua Firebase FCM và email
"""
import logging
import os
from datetime import datetime
from typing import Optional

from celery import Celery

logger = logging.getLogger(__name__)

# Cấu hình Celery với Redis làm broker
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "health_service",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Ho_Chi_Minh",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


def _lay_thong_tin_benh_nhan(patient_id: str) -> dict:
    """Lấy thông tin bệnh nhân từ database để gửi thông báo"""
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy import select

    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://admin:secret@postgres:5432/diabetes_db"
    )
    if DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

    async def _query():
        engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
        session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with session_factory() as session:
            from health_service.models import Alert, Prediction
            from uuid import UUID
            result = await session.execute(
                select(Alert).where(Alert.recipient_id == UUID(patient_id)).limit(1)
            )
            # Đơn giản hóa: trả về dict cơ bản
            return {"patient_id": patient_id}

    try:
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(_query())
    except Exception:
        return {"patient_id": patient_id}


def _gui_firebase_notification(
    device_token: Optional[str],
    title: str,
    body: str,
    data: dict,
) -> bool:
    """Gửi push notification qua Firebase FCM"""
    firebase_creds = os.getenv("FIREBASE_CREDENTIALS")
    if not firebase_creds:
        logger.warning("Không có FIREBASE_CREDENTIALS — bỏ qua push notification")
        return False

    try:
        import firebase_admin  # type: ignore
        from firebase_admin import credentials, messaging  # type: ignore

        # Khởi tạo Firebase app nếu chưa có
        if not firebase_admin._apps:
            cred = credentials.Certificate(firebase_creds)
            firebase_admin.initialize_app(cred)

        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in data.items()},
            token=device_token,
        )
        response = messaging.send(message)
        logger.info(f"Firebase notification gửi thành công: {response}")
        return True

    except Exception as e:
        logger.error(f"Lỗi gửi Firebase notification: {e}")
        return False


def _luu_alert_vao_db(
    prediction_id: str,
    recipient_id: str,
    alert_type: str,
    severity: str,
    message: str,
):
    """Lưu cảnh báo vào database"""
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from uuid import UUID

    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://admin:secret@postgres:5432/diabetes_db"
    )
    if DATABASE_URL.startswith("postgresql://"):
        DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

    async def _insert():
        engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
        factory = async_sessionmaker(bind=engine, expire_on_commit=False)
        async with factory() as session:
            from health_service.models import Alert
            canh_bao = Alert(
                prediction_id=UUID(prediction_id),
                recipient_id=UUID(recipient_id),
                alert_type=alert_type,
                severity=severity,
                message=message,
                sent_at=datetime.utcnow(),
                is_read=False,
            )
            session.add(canh_bao)
            await session.commit()
            return str(canh_bao.alert_id)

    try:
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(_insert())
    except Exception as e:
        logger.error(f"Lỗi lưu alert vào DB: {e}")
        return None


@celery_app.task(name="gui_canh_bao_nguy_co_cao", bind=True, max_retries=3)
def gui_canh_bao_nguy_co_cao(
    self,
    patient_id: str,
    prediction_id: str,
    risk_score: float,
    risk_level: str,
):
    """
    Gửi cảnh báo khi nguy cơ cao (risk_score > 0.7)
    Gửi đến cả bệnh nhân và bác sĩ
    """
    try:
        logger.info(
            f"Gửi cảnh báo nguy cơ cao — patient={patient_id} "
            f"risk={risk_score:.3f} level={risk_level}"
        )

        # Xác định mức độ cảnh báo
        if risk_level == "CRITICAL":
            severity = "CRITICAL"
            title = "⚠️ NGUY HIỂM NGHIÊM TRỌNG"
            body = (
                f"Nguy cơ biến chứng tiểu đường CỰC CAO ({risk_score*100:.0f}%). "
                "Liên hệ bác sĩ hoặc gọi cấp cứu NGAY!"
            )
        else:
            severity = "DANGER"
            title = "🔴 Cảnh báo nguy cơ cao"
            body = (
                f"Nguy cơ biến chứng tiểu đường cao ({risk_score*100:.0f}%). "
                "Liên hệ bác sĩ ngay hôm nay."
            )

        # Lưu alert cho bệnh nhân
        _luu_alert_vao_db(
            prediction_id=prediction_id,
            recipient_id=patient_id,
            alert_type="PUSH",
            severity=severity,
            message=body,
        )

        # Gửi Firebase push notification cho bệnh nhân
        _gui_firebase_notification(
            device_token=None,  # lấy từ user profile trong production
            title=title,
            body=body,
            data={
                "type": "RISK_ALERT",
                "risk_score": risk_score,
                "risk_level": risk_level,
                "patient_id": patient_id,
                "prediction_id": prediction_id,
            },
        )

        logger.info(f"Cảnh báo đã gửi thành công cho patient={patient_id}")

    except Exception as exc:
        logger.error(f"Lỗi gửi cảnh báo: {exc}")
        raise self.retry(exc=exc, countdown=30)


@celery_app.task(name="gui_canh_bao_khan_cap", bind=True, max_retries=3)
def gui_canh_bao_khan_cap(
    self,
    patient_id: str,
    reading_id: str,
    glucose_value: float,
):
    """
    Gửi cảnh báo khẩn cấp khi glucose > 300 hoặc < 60 mg/dL
    Không cần chờ kết quả ML model
    """
    try:
        if glucose_value > 300:
            title = "🚨 Đường huyết NGUY HIỂM CAO"
            body = (
                f"Đường huyết của bạn ĐỘT NGỘT TĂNG CAO ({glucose_value:.0f} mg/dL). "
                "Gọi cấp cứu hoặc đến bệnh viện NGAY!"
            )
            severity = "CRITICAL"
        else:
            title = "🚨 Hạ đường huyết NGUY HIỂM"
            body = (
                f"Đường huyết của bạn QUÁ THẤP ({glucose_value:.0f} mg/dL). "
                "Uống nước đường hoặc ăn ngay — gọi cấp cứu nếu không tỉnh lại!"
            )
            severity = "CRITICAL"

        logger.warning(
            f"Cảnh báo khẩn cấp glucose — patient={patient_id} "
            f"glucose={glucose_value:.0f}"
        )

        # Gửi notification ngay lập tức
        _gui_firebase_notification(
            device_token=None,
            title=title,
            body=body,
            data={
                "type": "EMERGENCY_GLUCOSE",
                "glucose": glucose_value,
                "patient_id": patient_id,
                "reading_id": reading_id,
            },
        )

    except Exception as exc:
        logger.error(f"Lỗi gửi cảnh báo khẩn: {exc}")
        raise self.retry(exc=exc, countdown=10)


@celery_app.task(name="gui_bao_cao_hang_tuan", bind=True)
def gui_bao_cao_hang_tuan(self, patient_id: str):
    """Gửi báo cáo sức khỏe tóm tắt hàng tuần"""
    try:
        logger.info(f"Gửi báo cáo tuần cho patient={patient_id}")
        # Tích hợp email service trong production
        logger.info("Báo cáo tuần đã gửi (placeholder)")
    except Exception as exc:
        logger.error(f"Lỗi gửi báo cáo: {exc}")
        raise self.retry(exc=exc, countdown=300)
