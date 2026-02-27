"""
Script training RF và LSTM trên Pima Indians Diabetes Dataset
Chạy: python -m ml_service.train
"""
import logging
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score, roc_auc_score, f1_score,
    classification_report, confusion_matrix,
)

from ml_service.preprocessor import DataPreprocessor, FEATURE_NAMES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# URL dataset Pima từ UCI (hoặc dùng Kaggle)
PIMA_URL = (
    "https://raw.githubusercontent.com/jbrownlee/Datasets/master/pima-indians-diabetes.data.csv"
)

# Tên cột Pima dataset gốc
PIMA_COLUMNS = [
    "pregnancies", "glucose", "blood_pressure",
    "skin_thickness", "insulin", "bmi",
    "diabetes_pedigree", "age", "outcome",
]


def tai_du_lieu_pima() -> pd.DataFrame:
    """Tải và ánh xạ Pima dataset sang 15 features của hệ thống"""
    logger.info("Tải Pima Indians Diabetes Dataset...")
    try:
        df = pd.read_csv(PIMA_URL, header=None, names=PIMA_COLUMNS)
    except Exception as e:
        logger.error(f"Không tải được từ URL: {e}")
        # Thử tải từ file local nếu có
        local_path = MODEL_DIR / "pima_diabetes.csv"
        if local_path.exists():
            df = pd.read_csv(local_path, header=None, names=PIMA_COLUMNS)
            logger.info(f"Dùng file local: {local_path}")
        else:
            logger.error("Không tìm thấy dataset — tạo dữ liệu tổng hợp")
            return _tao_du_lieu_tong_hop()

    logger.info(f"Dataset: {df.shape[0]} mẫu, {df.shape[1]} cột")
    logger.info(f"Phân phối nhãn:\n{df['outcome'].value_counts()}")
    return df


def _tao_du_lieu_tong_hop(n_samples: int = 2000) -> pd.DataFrame:
    """
    Tạo dữ liệu tổng hợp theo phân phối y tế thực tế
    Dùng khi không có dataset thực
    """
    logger.info(f"Tạo {n_samples} mẫu tổng hợp...")
    np.random.seed(42)

    # Tỉ lệ 65% không biến chứng, 35% có biến chứng
    n_neg = int(n_samples * 0.65)
    n_pos = n_samples - n_neg

    def sinh_benh_nhan(n, bien_chung: bool):
        """Sinh dữ liệu bệnh nhân theo trạng thái biến chứng"""
        if bien_chung:
            # Phân phối cho bệnh nhân có nguy cơ cao
            glucose = np.random.normal(200, 50, n).clip(100, 400)
            systolic_bp = np.random.normal(145, 15, n).clip(110, 200)
            diastolic_bp = np.random.normal(90, 10, n).clip(70, 120)
            hba1c = np.random.normal(9.0, 1.5, n).clip(6.5, 15)
            creatinine = np.random.normal(1.5, 0.4, n).clip(0.8, 3.0)
            cholesterol = np.random.normal(230, 30, n).clip(150, 320)
            age = np.random.normal(58, 10, n).clip(30, 85)
            diabetes_duration = np.random.exponential(10, n).clip(1, 30)
        else:
            # Phân phối cho bệnh nhân ổn định
            glucose = np.random.normal(110, 25, n).clip(70, 180)
            systolic_bp = np.random.normal(120, 12, n).clip(90, 150)
            diastolic_bp = np.random.normal(78, 8, n).clip(60, 95)
            hba1c = np.random.normal(6.5, 0.8, n).clip(4.5, 8.5)
            creatinine = np.random.normal(0.95, 0.2, n).clip(0.5, 1.4)
            cholesterol = np.random.normal(185, 25, n).clip(120, 240)
            age = np.random.normal(48, 12, n).clip(20, 75)
            diabetes_duration = np.random.exponential(5, n).clip(0.5, 20)

        heart_rate = np.random.normal(80, 12, n).clip(55, 120)
        bmi = np.random.normal(28, 5, n).clip(18, 45)

        # Rolling features
        glucose_7d_mean = glucose + np.random.normal(0, 10, n)
        bp_7d_mean = systolic_bp + np.random.normal(0, 5, n)
        hba1c_trend = np.random.normal(0.1 if bien_chung else -0.05, 0.3, n)
        glucose_variability = np.random.exponential(15 if bien_chung else 8, n)
        time_in_range = np.random.uniform(0.3 if bien_chung else 0.7, 1.0, n)

        return {
            "glucose": glucose,
            "systolic_bp": systolic_bp,
            "diastolic_bp": diastolic_bp,
            "heart_rate": heart_rate,
            "bmi": bmi,
            "hba1c": hba1c,
            "cholesterol": cholesterol,
            "creatinine": creatinine,
            "age": age,
            "diabetes_duration": diabetes_duration,
            "glucose_7d_mean": glucose_7d_mean,
            "bp_7d_mean": bp_7d_mean,
            "hba1c_trend": hba1c_trend,
            "glucose_variability": glucose_variability,
            "time_in_range": time_in_range,
        }

    data_neg = sinh_benh_nhan(n_neg, False)
    data_pos = sinh_benh_nhan(n_pos, True)

    df = pd.DataFrame({
        col: np.concatenate([data_neg[col], data_pos[col]])
        for col in FEATURE_NAMES
    })
    df["outcome"] = np.concatenate([np.zeros(n_neg), np.ones(n_pos)])

    # Xáo trộn dữ liệu
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)
    logger.info(f"Dữ liệu tổng hợp: {df.shape}")
    return df


def _anh_xa_pima_sang_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ánh xạ Pima dataset (8 features gốc) sang 15 features của hệ thống
    Các features không có trong Pima sẽ được tạo tổng hợp
    """
    df_out = pd.DataFrame()

    # Map trực tiếp
    df_out["glucose"] = df["glucose"]
    df_out["systolic_bp"] = df["blood_pressure"]
    df_out["diastolic_bp"] = df["blood_pressure"] * 0.65  # ước tính tâm trương
    df_out["heart_rate"] = np.random.normal(80, 12, len(df)).clip(55, 120)
    df_out["bmi"] = df["bmi"]
    df_out["hba1c"] = df["glucose"] / 28.7 + 2.0  # ước tính HbA1c từ glucose
    df_out["cholesterol"] = np.random.normal(190, 35, len(df)).clip(120, 300)
    df_out["creatinine"] = np.random.normal(1.0, 0.3, len(df)).clip(0.5, 3.0)
    df_out["age"] = df["age"]
    df_out["diabetes_duration"] = (df["age"] - 30).clip(0, 40)

    # Rolling features ước tính
    df_out["glucose_7d_mean"] = df["glucose"] + np.random.normal(0, 15, len(df))
    df_out["bp_7d_mean"] = df["blood_pressure"] + np.random.normal(0, 5, len(df))
    df_out["hba1c_trend"] = np.where(df["outcome"] == 1, 0.2, -0.1)
    df_out["glucose_variability"] = np.abs(df["insulin"] / 10 + np.random.normal(0, 5, len(df)))
    df_out["time_in_range"] = np.where(df["outcome"] == 1, 0.45, 0.75)

    df_out["outcome"] = df["outcome"]
    return df_out


def train_rf_model(
    X_train: np.ndarray,
    y_train: np.ndarray,
) -> RandomForestClassifier:
    """
    Train Random Forest theo đúng cấu hình trong PLAN.md
    """
    logger.info("Training Random Forest (n_estimators=200)...")
    rf = RandomForestClassifier(
        n_estimators=200,
        max_depth=10,
        min_samples_split=5,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    rf.fit(X_train, y_train)
    logger.info("Random Forest training hoàn tất")
    return rf


def train_lstm_model(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    y_test: np.ndarray,
    sequence_length: int = 7,
    n_features: int = 15,
    epochs: int = 30,
    batch_size: int = 32,
):
    """
    Train LSTM model theo kiến trúc trong PLAN.md
    Input shape: (batch, 7, 15)
    """
    try:
        import tensorflow as tf  # type: ignore
        from tensorflow.keras.models import Sequential  # type: ignore
        from tensorflow.keras.layers import LSTM, Dense, Dropout  # type: ignore
        from tensorflow.keras.callbacks import EarlyStopping  # type: ignore
    except ImportError:
        logger.error("TensorFlow không khả dụng — bỏ qua training LSTM")
        return None

    logger.info("Training LSTM model...")

    # Xây dựng sequences 7 ngày từ data huấn luyện
    # Với Pima dataset phẳng, giả lập sequence bằng cách lặp lại
    n_train = len(X_train)
    # Tạo sequences: lấy ngẫu nhiên 7 điểm liên tiếp từ training data
    X_seq = []
    y_seq = []
    for i in range(n_train - sequence_length):
        seq = X_train[i:i + sequence_length]
        X_seq.append(seq)
        y_seq.append(y_train[i + sequence_length])

    if not X_seq:
        logger.warning("Không đủ data để tạo LSTM sequences")
        return None

    X_seq = np.array(X_seq, dtype=np.float32)
    y_seq = np.array(y_seq, dtype=np.float32)

    # Kiến trúc LSTM theo PLAN.md
    model = Sequential([
        LSTM(64, return_sequences=True, input_shape=(sequence_length, n_features)),
        Dropout(0.2),
        LSTM(32, return_sequences=False),
        Dropout(0.2),
        Dense(16, activation="relu"),
        Dense(1, activation="sigmoid"),
    ])

    model.compile(
        optimizer="adam",
        loss="binary_crossentropy",
        metrics=["accuracy", tf.keras.metrics.AUC(name="auc")],
    )

    early_stop = EarlyStopping(
        monitor="val_loss", patience=5, restore_best_weights=True
    )

    model.fit(
        X_seq, y_seq,
        epochs=epochs,
        batch_size=batch_size,
        validation_split=0.15,
        callbacks=[early_stop],
        verbose=1,
    )

    logger.info("LSTM training hoàn tất")
    return model


def danh_gia_model(model, X_test: np.ndarray, y_test: np.ndarray, ten_model: str):
    """Đánh giá và in metrics của model"""
    y_pred = model.predict(X_test)
    if hasattr(y_pred[0], "__len__"):
        y_pred_binary = (y_pred > 0.5).astype(int).flatten()
        y_prob = y_pred.flatten()
    else:
        y_pred_binary = y_pred
        y_prob = model.predict_proba(X_test)[:, 1]

    acc = accuracy_score(y_test, y_pred_binary)
    auc = roc_auc_score(y_test, y_prob)
    f1 = f1_score(y_test, y_pred_binary, average="weighted")

    logger.info(f"\n{'='*50}")
    logger.info(f"KẾT QUẢ {ten_model}")
    logger.info(f"Accuracy:  {acc:.4f}")
    logger.info(f"AUC-ROC:   {auc:.4f}")
    logger.info(f"F1-Score:  {f1:.4f}")
    logger.info(f"\nClassification Report:\n{classification_report(y_test, y_pred_binary)}")
    logger.info(f"Confusion Matrix:\n{confusion_matrix(y_test, y_pred_binary)}")
    logger.info(f"{'='*50}")

    return {"accuracy": acc, "auc": auc, "f1": f1}


def chay_training():
    """Entry point: chạy toàn bộ pipeline training"""
    logger.info("=== BẮT ĐẦU TRAINING ===")

    # Tải dữ liệu
    df_pima = tai_du_lieu_pima()

    # Xác định xem có cần map từ Pima format hay không
    if "outcome" in df_pima.columns and all(
        col in df_pima.columns for col in ["blood_pressure", "insulin"]
    ):
        logger.info("Ánh xạ Pima dataset sang 15 features...")
        np.random.seed(42)
        df = _anh_xa_pima_sang_features(df_pima)
    elif all(col in df_pima.columns for col in FEATURE_NAMES):
        df = df_pima
    else:
        logger.warning("Format không nhận ra — dùng dữ liệu tổng hợp")
        df = _tao_du_lieu_tong_hop()

    # Khởi tạo preprocessor
    preprocessor = DataPreprocessor()

    # Chạy pipeline preprocessing
    X_train, X_test, y_train, y_test = preprocessor.chuan_bi_training(df, nhan="outcome")

    logger.info(
        f"Training: {X_train.shape}, Test: {X_test.shape} | "
        f"Pos: {y_train.sum():.0f}/{len(y_train)}"
    )

    # Train Random Forest
    rf = train_rf_model(X_train, y_train)
    ket_qua_rf = danh_gia_model(rf, X_test, y_test, "Random Forest")

    # Lưu RF model
    rf_path = MODEL_DIR / "rf_model.pkl"
    with open(rf_path, "wb") as f:
        pickle.dump(rf, f)
    logger.info(f"Đã lưu RF model tại {rf_path}")

    # Train LSTM
    lstm = train_lstm_model(X_train, y_train, X_test, y_test)
    if lstm is not None:
        lstm_path = MODEL_DIR / "lstm_model.h5"
        lstm.save(str(lstm_path))
        logger.info(f"Đã lưu LSTM model tại {lstm_path}")

    # Lưu preprocessor — scaler chỉ được fit trên training data
    preprocessor.luu_preprocessor()

    logger.info("=== TRAINING HOÀN TẤT ===")
    logger.info(f"RF AUC-ROC: {ket_qua_rf['auc']:.4f}")

    return rf, lstm, preprocessor


if __name__ == "__main__":
    chay_training()
