"""
SHAP Explainer — giải thích kết quả dự đoán của Random Forest
"""
import logging
from typing import Dict, List, Optional

import numpy as np

from ml_service.preprocessor import FEATURE_NAMES

logger = logging.getLogger(__name__)

# Tên hiển thị thân thiện cho từng feature
TEN_HIEN_THI = {
    "glucose": "Đường huyết",
    "systolic_bp": "Huyết áp tâm thu",
    "diastolic_bp": "Huyết áp tâm trương",
    "heart_rate": "Nhịp tim",
    "bmi": "BMI",
    "hba1c": "HbA1c",
    "cholesterol": "Cholesterol",
    "creatinine": "Creatinine",
    "age": "Tuổi",
    "diabetes_duration": "Thời gian mắc bệnh",
    "glucose_7d_mean": "Trung bình glucose 7 ngày",
    "bp_7d_mean": "Trung bình huyết áp 7 ngày",
    "hba1c_trend": "Xu hướng HbA1c",
    "glucose_variability": "Biến động glucose",
    "time_in_range": "Thời gian glucose ổn định",
}


class SHAPExplainer:
    """
    Giải thích kết quả dự đoán bằng SHAP TreeExplainer cho RF model
    """

    def __init__(self):
        self.explainer = None
        self._da_khoi_tao = False

    def khoi_tao(self, rf_model) -> bool:
        """Khởi tạo SHAP explainer với RF model đã train"""
        try:
            import shap  # type: ignore
            self.explainer = shap.TreeExplainer(rf_model)
            self._da_khoi_tao = True
            logger.info("SHAP TreeExplainer đã khởi tạo")
            return True
        except Exception as e:
            logger.error(f"Lỗi khởi tạo SHAP explainer: {e}")
            return False

    def giai_thich(
        self,
        features_scaled: np.ndarray,
        features_goc: dict,
    ) -> List[Dict]:
        """
        Tính SHAP values và trả về top nhân tố ảnh hưởng
        features_scaled: mảng đã chuẩn hóa (1, 15)
        features_goc: dict giá trị gốc để hiển thị
        """
        if not self._da_khoi_tao:
            logger.warning("SHAP chưa khởi tạo, trả về feature importance thay thế")
            return self._fallback_feature_importance(features_goc)

        try:
            import shap  # type: ignore
            # Tính SHAP values — [0] là class 0, [1] là class 1 (nguy cơ)
            shap_values = self.explainer.shap_values(features_scaled)

            # Lấy SHAP values cho class 1 (dự đoán nguy cơ cao)
            if isinstance(shap_values, list):
                values_class1 = shap_values[1][0]
            else:
                values_class1 = shap_values[0]

            # Xây dựng danh sách nhân tố
            nhan_to = []
            for i, feat in enumerate(FEATURE_NAMES):
                shap_val = float(values_class1[i])
                gia_tri_goc = features_goc.get(feat)
                nhan_to.append({
                    "feature": feat,
                    "feature_name_vi": TEN_HIEN_THI.get(feat, feat),
                    "contribution": round(shap_val, 4),
                    "value": round(float(gia_tri_goc), 2) if gia_tri_goc is not None else None,
                })

            # Sắp xếp theo mức độ đóng góp tuyệt đối
            nhan_to.sort(key=lambda x: abs(x["contribution"]), reverse=True)

            # Trả về top 5 nhân tố
            return nhan_to[:5]

        except Exception as e:
            logger.error(f"Lỗi tính SHAP: {e}")
            return self._fallback_feature_importance(features_goc)

    def _fallback_feature_importance(self, features_goc: dict) -> List[Dict]:
        """
        Fallback khi SHAP không khả dụng — dùng giá trị tuyệt đối
        """
        # Ngưỡng bình thường của từng feature
        NGUONG = {
            "glucose": (70, 130),
            "systolic_bp": (90, 120),
            "diastolic_bp": (60, 80),
            "heart_rate": (60, 100),
            "bmi": (18.5, 24.9),
            "hba1c": (0, 5.7),
            "cholesterol": (0, 200),
            "creatinine": (0.6, 1.2),
        }

        nhan_to = []
        for feat, (low, high) in NGUONG.items():
            val = features_goc.get(feat)
            if val is not None:
                # Đóng góp ước tính = độ lệch so với ngưỡng bình thường
                mid = (low + high) / 2
                range_size = (high - low) or 1
                contribution = (float(val) - mid) / range_size
                nhan_to.append({
                    "feature": feat,
                    "feature_name_vi": TEN_HIEN_THI.get(feat, feat),
                    "contribution": round(contribution, 4),
                    "value": round(float(val), 2),
                })

        nhan_to.sort(key=lambda x: abs(x["contribution"]), reverse=True)
        return nhan_to[:5]


# Singleton instance
bo_giai_thich = SHAPExplainer()
