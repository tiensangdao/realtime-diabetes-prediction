"""
EnsembleRiskPredictor — kết hợp Random Forest và LSTM để dự đoán nguy cơ
"""
import logging
import pickle
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from ml_service.preprocessor import DataPreprocessor, FEATURE_NAMES

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent / "models"

# Ngưỡng phân loại nguy cơ theo PLAN.md
NGUONG_LOW = 0.3
NGUONG_MEDIUM = 0.7
NGUONG_CRITICAL = 0.9

# Trọng số ensemble: RF=0.4, LSTM=0.6
RF_WEIGHT = 0.4
LSTM_WEIGHT = 0.6

# Số ngày tối thiểu để dùng LSTM
SO_NGAY_TOI_THIEU_LSTM = 7


def phan_loai_nguy_co(risk_score: float) -> str:
    """Phân loại mức nguy cơ từ điểm số"""
    if risk_score > NGUONG_CRITICAL:
        return "CRITICAL"
    elif risk_score > NGUONG_MEDIUM:
        return "HIGH"
    elif risk_score >= NGUONG_LOW:
        return "MEDIUM"
    else:
        return "LOW"


class MLModelManager:
    """
    Quản lý vòng đời của RF model và LSTM model
    """

    def __init__(self):
        self.rf_model = None
        self.lstm_model = None
        self.preprocessor = DataPreprocessor()
        self.model_version = "v1.0"
        self._rf_loaded = False
        self._lstm_loaded = False

    def tai_rf_model(self, duong_dan: Optional[Path] = None) -> bool:
        """Tải Random Forest model từ file"""
        path = duong_dan or (MODEL_DIR / "rf_model.pkl")
        try:
            with open(path, "rb") as f:
                self.rf_model = pickle.load(f)
            self._rf_loaded = True
            logger.info(f"Đã tải RF model từ {path}")
            return True
        except FileNotFoundError:
            logger.warning(f"Không tìm thấy RF model tại {path}")
            return False
        except Exception as e:
            logger.error(f"Lỗi tải RF model: {e}")
            return False

    def tai_lstm_model(self, duong_dan: Optional[Path] = None) -> bool:
        """Tải LSTM model từ file"""
        path = duong_dan or (MODEL_DIR / "lstm_model.h5")
        try:
            from tensorflow.keras.models import load_model  # type: ignore
            self.lstm_model = load_model(str(path))
            self._lstm_loaded = True
            logger.info(f"Đã tải LSTM model từ {path}")
            return True
        except FileNotFoundError:
            logger.warning(f"Không tìm thấy LSTM model tại {path}")
            return False
        except Exception as e:
            logger.error(f"Lỗi tải LSTM model: {e}")
            return False

    def tai_tat_ca(self) -> bool:
        """Tải tất cả models và preprocessor"""
        ok_preprocessor = False
        try:
            self.preprocessor.tai_preprocessor()
            ok_preprocessor = True
        except Exception as e:
            logger.error(f"Lỗi tải preprocessor: {e}")

        ok_rf = self.tai_rf_model()
        ok_lstm = self.tai_lstm_model()

        logger.info(
            f"Trạng thái tải model — preprocessor={ok_preprocessor}, "
            f"RF={ok_rf}, LSTM={ok_lstm}"
        )
        return ok_rf  # RF là bắt buộc


class EnsembleRiskPredictor:
    """
    Dự đoán nguy cơ biến chứng tiểu đường bằng Ensemble RF + LSTM
    """

    def __init__(self):
        self.model_manager = MLModelManager()

    def tai_models(self) -> bool:
        """Khởi động — tải tất cả models"""
        return self.model_manager.tai_tat_ca()

    @property
    def da_san_sang(self) -> bool:
        """Kiểm tra RF model đã sẵn sàng chưa"""
        return self.model_manager._rf_loaded

    def _du_doan_rf(self, features_scaled: np.ndarray) -> float:
        """Dự đoán xác suất nguy cơ từ Random Forest"""
        rf = self.model_manager.rf_model
        # Lấy xác suất class=1 (có biến chứng)
        prob = rf.predict_proba(features_scaled)[0][1]
        return float(prob)

    def _du_doan_lstm(self, sequence_7d: np.ndarray) -> float:
        """
        Dự đoán xác suất nguy cơ từ LSTM với 7 ngày lịch sử
        Input shape: (1, 7, 15) — 1 bản ghi, 7 ngày, 15 features
        """
        lstm = self.model_manager.lstm_model
        prob = lstm.predict(sequence_7d, verbose=0)[0][0]
        return float(prob)

    def _xay_dung_sequence(
        self, lich_su_7_ngay: List[Dict]
    ) -> Optional[np.ndarray]:
        """
        Xây dựng sequence 7 ngày cho LSTM
        Nếu thiếu ngày nào, pad bằng giá trị trung bình của các ngày còn lại
        """
        if not lich_su_7_ngay or len(lich_su_7_ngay) < SO_NGAY_TOI_THIEU_LSTM:
            return None

        rows = []
        for ngay in lich_su_7_ngay[:SO_NGAY_TOI_THIEU_LSTM]:
            row = [float(ngay.get(feat) or 0.0) for feat in FEATURE_NAMES]
            rows.append(row)

        # Chuẩn hóa sequence
        seq = np.array(rows, dtype=np.float32)
        # Áp dụng scaler đã fit
        preprocessor = self.model_manager.preprocessor
        seq_flat = seq.reshape(-1, len(FEATURE_NAMES))
        seq_scaled = preprocessor.scaler.transform(seq_flat)
        seq_scaled = seq_scaled.reshape(1, SO_NGAY_TOI_THIEU_LSTM, len(FEATURE_NAMES))
        return seq_scaled

    def _tinh_nguy_co_bien_chung(
        self, risk_score: float, features: dict
    ) -> Dict[str, float]:
        """
        Ước tính xác suất từng loại biến chứng dựa trên risk_score và features
        """
        glucose = float(features.get("glucose") or 0)
        hba1c = float(features.get("hba1c") or 0)
        systolic_bp = float(features.get("systolic_bp") or 0)
        creatinine = float(features.get("creatinine") or 0)
        cholesterol = float(features.get("cholesterol") or 0)

        # Nguy cơ bệnh thận — creatinine và huyết áp
        nephropathy = min(
            risk_score * 0.85
            + (0.1 if creatinine > 1.2 else 0)
            + (0.05 if systolic_bp > 140 else 0),
            1.0,
        )

        # Nguy cơ bệnh mắt — glucose và HbA1c
        retinopathy = min(
            risk_score * 0.6
            + (0.1 if glucose > 200 else 0)
            + (0.1 if hba1c > 8 else 0),
            1.0,
        )

        # Nguy cơ tim mạch — huyết áp và cholesterol
        cardiac = min(
            risk_score * 0.7
            + (0.1 if systolic_bp > 140 else 0)
            + (0.05 if cholesterol > 200 else 0),
            1.0,
        )

        # Nguy cơ thần kinh — glucose kéo dài
        neuropathy = min(
            risk_score * 0.45
            + (0.05 if hba1c > 9 else 0),
            1.0,
        )

        return {
            "nephropathy": round(nephropathy, 3),
            "retinopathy": round(retinopathy, 3),
            "cardiac": round(cardiac, 3),
            "neuropathy": round(neuropathy, 3),
        }

    def du_doan_nguy_co(
        self,
        features: dict,
        lich_su_7_ngay: Optional[List[Dict]] = None,
    ) -> dict:
        """
        Dự đoán nguy cơ biến chứng cho một bản ghi
        Tự động fallback về RF-only nếu < 7 ngày lịch sử
        """
        if not self.da_san_sang:
            raise RuntimeError("Models chưa được tải — gọi tai_models() trước")

        bat_dau = time.time()

        # Tiền xử lý features hiện tại
        features_scaled = self.model_manager.preprocessor.chuan_bi_inference(features)

        # Dự đoán RF
        rf_prob = self._du_doan_rf(features_scaled)

        # Dự đoán LSTM nếu đủ lịch sử
        dung_lstm = False
        final_score = rf_prob  # mặc định dùng RF-only

        if (
            self.model_manager._lstm_loaded
            and lich_su_7_ngay
            and len(lich_su_7_ngay) >= SO_NGAY_TOI_THIEU_LSTM
        ):
            try:
                sequence = self._xay_dung_sequence(lich_su_7_ngay)
                if sequence is not None:
                    lstm_prob = self._du_doan_lstm(sequence)
                    # Ensemble: RF=0.4, LSTM=0.6
                    final_score = RF_WEIGHT * rf_prob + LSTM_WEIGHT * lstm_prob
                    dung_lstm = True
                    logger.info(
                        f"Ensemble: rf={rf_prob:.3f}, lstm={lstm_prob:.3f}, "
                        f"final={final_score:.3f}"
                    )
            except Exception as e:
                logger.warning(f"LSTM thất bại, fallback về RF: {e}")
                final_score = rf_prob
        else:
            logger.info(
                f"Dùng RF-only (lịch sử < {SO_NGAY_TOI_THIEU_LSTM} ngày): "
                f"rf={rf_prob:.3f}"
            )

        # Phân loại nguy cơ
        risk_level = phan_loai_nguy_co(final_score)

        # Tính nguy cơ từng biến chứng
        bien_chung = self._tinh_nguy_co_bien_chung(final_score, features)

        ket_qua = {
            "prediction_id": str(uuid.uuid4()),
            "risk_score": round(final_score, 3),
            "risk_level": risk_level,
            "rf_prob": round(rf_prob, 3),
            "used_lstm": dung_lstm,
            "complications": bien_chung,
            "inference_time_ms": int((time.time() - bat_dau) * 1000),
            "model_version": self.model_manager.model_version,
        }

        logger.info(
            f"Dự đoán: risk_score={ket_qua['risk_score']} "
            f"level={risk_level} lstm={dung_lstm}"
        )
        return ket_qua


# Singleton instance cho ml_service
bo_du_doan = EnsembleRiskPredictor()
