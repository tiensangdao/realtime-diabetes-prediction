"""
FastAPI app chính cho auth_service — cổng 8000
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from auth_service.database import engine
from auth_service.models import Base
from auth_service.routers.auth import router as auth_router

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Khởi động và tắt service"""
    # Tạo bảng nếu chưa có
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Auth Service đã khởi động — bảng database sẵn sàng")
    yield
    await engine.dispose()
    logger.info("Auth Service đã tắt")


app = FastAPI(
    title="Auth Service",
    description="Dịch vụ xác thực — đăng ký, đăng nhập, quản lý tài khoản",
    version="1.0.0",
    lifespan=lifespan,
)

# Cho phép CORS từ mobile app và web dashboard
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


# Đăng ký router
app.include_router(auth_router)


@app.get("/health")
async def kiem_tra_suc_khoe():
    """Kiểm tra service đang chạy"""
    return {"status": "ok", "service": "auth_service"}
