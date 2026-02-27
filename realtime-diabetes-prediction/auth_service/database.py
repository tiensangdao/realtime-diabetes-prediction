"""
Kết nối database async cho auth_service
"""
import os
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from dotenv import load_dotenv

load_dotenv()

# Đọc DATABASE_URL từ biến môi trường
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://admin:secret@localhost:5432/diabetes_db"
)

# Chuyển sang asyncpg driver nếu chưa có
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Tạo async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# Tạo session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base class cho tất cả ORM models"""
    pass


async def get_db() -> AsyncSession:
    """Dependency: cấp phát database session cho mỗi request"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """Tạo tất cả bảng nếu chưa có (dùng khi dev/test)"""
    async with engine.begin() as conn:
        from auth_service.models import Base as AuthBase  # noqa
        await conn.run_sync(AuthBase.metadata.create_all)
