"""
DataPreprocessor — tiền xử lý dữ liệu đầu vào cho ML models
"""
import logging
import pickle
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from imblearn.over_sampling import SMOTE

logger = logging.getLogger(__name__)

# 15 features theo đúng thứ tự trong PLAN.md
FEATURE_NAMES = [
    "glucose",
    "systolic_bp",
    "diastolic_bp",
    "heart_rate",
    "bmi",
    "hba1c",
    "cholesterol",
    "creatinine",
    "age",
    "diabetes_duration",
    "glucose_7d_mean",
    "bp_7d_mean",
    "hba1c_trend",
    "glucose_variability",
    "time_in_range",
]

# Các cột không được phép bằng 0 trong y tế
ZERO_NOT_ALLOWED = [
    "glucose", "systolic_bp", "diastolic_bp",
    "bmi", "hba1c",
]

# Đường dẫn lưu scaler và imputer đã fit
MODEL_DIR = Path(__file__).parent / "models"


class DataPreprocessor:
    """
    Pipeline tiền xử lý dữ liệu tiểu đường — 5 bước theo PLAN.md
    StandardScaler chỉ được fit trên training data
    """

    def __init__(self):
        # Khởi tạo scaler và imputer
        self.scaler = StandardScaler()
        self.imputer = SimpleImputer(strategy="median")
        self._da_fit = False

    def lam_sach_du_lieu(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Bước 1: Làm sạch — thay 0 không hợp lệ bằng NaN, xóa trùng
        """
        df = df.copy()
        df = df.drop_duplicates()

        # Thay 0 bằng NaN ở các cột y tế không thể = 0
        for col in ZERO_NOT_ALLOWED:
            if col in df.columns:
                df[col] = df[col].replace(0, np.nan)

        return df

    def xu_ly_gia_tri_thieu(self, df: pd.DataFrame, fit: bool = False) -> pd.DataFrame:
        """
        Bước 2: Điền giá trị thiếu bằng median
        fit=True chỉ dùng khi training, không dùng trên test/production
        """
        cols = [c for c in FEATURE_NAMES if c in df.columns]
        df = df.copy()

        if fit:
            # Chỉ fit trên training data
            df[cols] = self.imputer.fit_transform(df[cols])
        else:
            df[cols] = self.imputer.transform(df[cols])

        return df

    def xu_ly_outlier(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Bước 3: Clip outlier bằng IQR — giữ data, không xóa
        """
        df = df.copy()
        cols = [c for c in FEATURE_NAMES if c in df.columns]

        for col in cols:
            Q1 = df[col].quantile(0.25)
            Q3 = df[col].quantile(0.75)
            IQR = Q3 - Q1
            lower = Q1 - 1.5 * IQR
            upper = Q3 + 1.5 * IQR
            df[col] = df[col].clip(lower, upper)

        return df

    def can_bang_lop(
        self, X: np.ndarray, y: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Bước 4: SMOTE — cân bằng lớp, chỉ dùng khi training
        """
        smote = SMOTE(random_state=42)
        X_balanced, y_balanced = smote.fit_resample(X, y)
        logger.info(
            f"Sau SMOTE: {pd.Series(y_balanced).value_counts().to_dict()}"
        )
        return X_balanced, y_balanced

    def chuan_hoa(
        self,
        X_train: np.ndarray,
        X_test: Optional[np.ndarray] = None,
        fit: bool = False,
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """
        Bước 5: Chuẩn hóa features về cùng thang đo
        fit=True chỉ dùng khi training (fit trên train, transform test)
        """
        if fit:
            # Fit chỉ trên training data — tránh data leakage
            X_train_scaled = self.scaler.fit_transform(X_train)
            self._da_fit = True
        else:
            if not self._da_fit:
                raise RuntimeError("Scaler chưa được fit — cần train trước")
            X_train_scaled = self.scaler.transform(X_train)

        X_test_scaled = None
        if X_test is not None:
            # Transform test set — KHÔNG fit lại
            X_test_scaled = self.scaler.transform(X_test)

        return X_train_scaled, X_test_scaled

    def chuan_bi_training(
        self, df: pd.DataFrame, nhan: str = "outcome"
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Pipeline đầy đủ cho training: clean → impute → outlier → SMOTE → scale
        Trả về X_train_scaled, X_test_scaled, y_train, y_test
        """
        from sklearn.model_selection import train_test_split

        # Tách features và nhãn
        X = df[FEATURE_NAMES].copy()
        y = df[nhan].values

        # Bước 1-3
        X = self.lam_sach_du_lieu(X)
        X = self.xu_ly_gia_tri_thieu(X, fit=True)
        X = self.xu_ly_outlier(X)

        # Chia train/test trước khi SMOTE và scale
        X_train, X_test, y_train, y_test = train_test_split(
            X.values, y, test_size=0.2, random_state=42, stratify=y
        )

        # Bước 4: SMOTE chỉ trên training set
        X_train, y_train = self.can_bang_lop(X_train, y_train)

        # Bước 5: Scale — fit trên train, transform test
        X_train_scaled, X_test_scaled = self.chuan_hoa(X_train, X_test, fit=True)

        logger.info(
            f"Training set: {X_train_scaled.shape}, Test set: {X_test_scaled.shape}"
        )
        return X_train_scaled, X_test_scaled, y_train, y_test

    def chuan_bi_inference(self, features: dict) -> np.ndarray:
        """
        Tiền xử lý cho một bản ghi inference đơn lẻ
        """
        if not self._da_fit:
            raise RuntimeError("Preprocessor chưa được fit — cần load scaler trước")

        # Tạo DataFrame 1 hàng với đầy đủ 15 features
        row = {}
        for feat in FEATURE_NAMES:
            val = features.get(feat)
            # Thay 0 không hợp lệ bằng NaN
            if feat in ZERO_NOT_ALLOWED and val == 0:
                val = np.nan
            row[feat] = [val if val is not None else np.nan]

        df = pd.DataFrame(row)

        # Impute và scale
        df_imputed = pd.DataFrame(
            self.imputer.transform(df[FEATURE_NAMES]),
            columns=FEATURE_NAMES,
        )
        X_scaled = self.scaler.transform(df_imputed.values)
        return X_scaled

    def luu_preprocessor(self, duong_dan: Optional[Path] = None):
        """Lưu scaler và imputer đã fit"""
        path = duong_dan or (MODEL_DIR / "preprocessor.pkl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"scaler": self.scaler, "imputer": self.imputer}, f)
        logger.info(f"Đã lưu preprocessor tại {path}")

    def tai_preprocessor(self, duong_dan: Optional[Path] = None):
        """Tải scaler và imputer đã fit"""
        path = duong_dan or (MODEL_DIR / "preprocessor.pkl")
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.scaler = data["scaler"]
        self.imputer = data["imputer"]
        self._da_fit = True
        logger.info(f"Đã tải preprocessor từ {path}")
