"""
FastAPI app chính cho health_service — cổng 8001
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from health_service.database import engine
from health_service.models import Base
from health_service.routers.readings import router as readings_router
from health_service.routers.alerts import router as alerts_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Khởi động và tắt service"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Health Service đã khởi động")
    yield
    await engine.dispose()
    logger.info("Health Service đã tắt")


app = FastAPI(
    title="Health Service",
    description="Dịch vụ quản lý chỉ số sức khỏe và cảnh báo",
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
async def xu_ly_loi_tong_quat(request: Request, exc: Exception):
    """Bắt tất cả lỗi không xử lý được"""
    logger.error(f"Lỗi không xử lý: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Lỗi server nội bộ"},
    )


app.include_router(readings_router)
app.include_router(alerts_router)


@app.get("/health")
async def kiem_tra_suc_khoe():
    """Kiểm tra service đang chạy"""
    return {"status": "ok", "service": "health_service"}
