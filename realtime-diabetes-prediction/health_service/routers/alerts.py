"""
Router quản lý cảnh báo — lấy danh sách, đánh dấu đã đọc
"""
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, desc

from health_service.database import get_db
from health_service.models import Alert
from health_service.schemas import AlertResponse, DanhSachAlertResponse
from health_service.dependencies import decode_jwt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["alerts"])


def _lay_user_id_tu_token(request: Request) -> UUID:
    """Lấy user_id từ JWT token"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thiếu token xác thực",
        )
    payload = decode_jwt(auth[7:])
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token thiếu user_id",
        )
    return UUID(user_id)


@router.get("/alerts/{user_id}", response_model=DanhSachAlertResponse)
async def lay_danh_sach_canh_bao(
    user_id: UUID,
    request: Request,
    skip: int = 0,
    limit: int = 20,
    chi_chua_doc: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Lấy danh sách cảnh báo của user, mới nhất trước"""
    # Xác minh user chỉ xem cảnh báo của mình (hoặc bác sĩ xem bệnh nhân)
    token_user_id = _lay_user_id_tu_token(request)
    if token_user_id != user_id:
        auth = request.headers.get("Authorization", "")
        payload = decode_jwt(auth[7:])
        role = payload.get("role", "patient")
        if role not in ("doctor", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Không có quyền xem cảnh báo của người khác",
            )

    # Xây dựng query
    query = select(Alert).where(Alert.recipient_id == user_id)

    # Lọc chưa đọc nếu cần
    if chi_chua_doc:
        query = query.where(Alert.is_read == False)  # noqa: E712

    # Đếm tổng số
    count_query = select(func.count()).select_from(Alert).where(
        Alert.recipient_id == user_id
    )
    total_result = await db.execute(count_query)
    tong_so = total_result.scalar_one()

    # Đếm chưa đọc
    unread_query = select(func.count()).select_from(Alert).where(
        Alert.recipient_id == user_id,
        Alert.is_read == False,  # noqa: E712
    )
    unread_result = await db.execute(unread_query)
    so_chua_doc = unread_result.scalar_one()

    # Lấy danh sách
    query = query.order_by(desc(Alert.sent_at)).offset(skip).limit(limit)
    result = await db.execute(query)
    danh_sach = result.scalars().all()

    return DanhSachAlertResponse(
        total=tong_so,
        unread_count=so_chua_doc,
        alerts=[AlertResponse.model_validate(a) for a in danh_sach],
    )


@router.put("/alerts/{alert_id}/read", response_model=AlertResponse)
async def danh_dau_da_doc(
    alert_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Đánh dấu cảnh báo đã đọc"""
    token_user_id = _lay_user_id_tu_token(request)

    # Kiểm tra cảnh báo tồn tại và thuộc về user này
    result = await db.execute(
        select(Alert).where(Alert.alert_id == alert_id)
    )
    canh_bao = result.scalar_one_or_none()

    if not canh_bao:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy cảnh báo {alert_id}",
        )

    if canh_bao.recipient_id != token_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Không có quyền cập nhật cảnh báo này",
        )

    if canh_bao.is_read:
        return AlertResponse.model_validate(canh_bao)

    # Cập nhật trạng thái đã đọc
    await db.execute(
        update(Alert)
        .where(Alert.alert_id == alert_id)
        .values(is_read=True, read_at=datetime.utcnow())
    )
    await db.commit()
    await db.refresh(canh_bao)

    logger.info(f"Đã đánh dấu đọc: alert_id={alert_id} user={token_user_id}")

    return AlertResponse.model_validate(canh_bao)


@router.put("/alerts/{user_id}/read-all", status_code=status.HTTP_200_OK)
async def danh_dau_tat_ca_da_doc(
    user_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Đánh dấu tất cả cảnh báo của user là đã đọc"""
    token_user_id = _lay_user_id_tu_token(request)

    if token_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Không có quyền cập nhật cảnh báo của người khác",
        )

    thoi_gian_doc = datetime.utcnow()
    await db.execute(
        update(Alert)
        .where(Alert.recipient_id == user_id, Alert.is_read == False)  # noqa: E712
        .values(is_read=True, read_at=thoi_gian_doc)
    )
    await db.commit()

    logger.info(f"Đã đánh dấu tất cả đã đọc cho user={user_id}")

    return {"message": "Đã đánh dấu tất cả cảnh báo là đã đọc"}
