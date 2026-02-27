# Hệ Thống Dự Đoán Biến Chứng Tiểu Đường Theo Thời Gian Thực

Hệ thống microservices dự đoán nguy cơ biến chứng tiểu đường sử dụng Ensemble RF + LSTM.

## Kiến trúc

```
nginx (port 80)
  ├── /auth/     → auth_service   (port 8000)  — JWT auth
  ├── /api/      → health_service (port 8001)  — health readings + alerts
  └── /ml/       → ml_service     (port 8002)  — RF + LSTM prediction
          ↕
postgres (port 5432) + redis (port 6379)
          ↕
celery-worker — async alert notifications (Firebase FCM)
```

## Yêu cầu

- Docker >= 24.0
- Docker Compose >= 2.20
- RAM >= 4GB (ML service cần 2GB)

## Cài đặt và chạy

### 1. Clone và cấu hình môi trường

```bash
git clone <repo>
cd realtime-diabetes-prediction
cp .env.example .env
# Sửa JWT_SECRET trong .env
```

### 2. Build và khởi động toàn bộ hệ thống

```bash
docker-compose up -d --build
```

### 3. Kiểm tra trạng thái

```bash
docker-compose ps
docker-compose logs -f
```

### 4. Train ML models (bắt buộc trước lần đầu dùng)

```bash
# Vào container ml-service và chạy training script
docker-compose exec ml-service python -m ml_service.train
```

Script sẽ:
- Tải Pima Indians Diabetes Dataset từ UCI
- Chạy pipeline: clean → impute → outlier → SMOTE → scale
- Train Random Forest (n_estimators=200) và LSTM (7→15 sequence)
- Lưu models vào `ml_service/models/`

### 5. Kiểm tra ML models đã load chưa

```bash
curl http://localhost:8002/ml/health
```

## Sử dụng API

### Đăng ký tài khoản

```bash
curl -X POST http://localhost/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "benh_nhan@example.com",
    "password": "matkhau123",
    "full_name": "Nguyễn Văn An",
    "role": "patient"
  }'
```

### Đăng nhập

```bash
curl -X POST http://localhost/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "benh_nhan@example.com", "password": "matkhau123"}'
```

Lưu `access_token` từ response để dùng cho các request tiếp theo.

### Nhập chỉ số sức khỏe (tự động trigger dự đoán)

```bash
curl -X POST http://localhost/api/readings \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "glucose": 280,
    "systolic_bp": 145,
    "diastolic_bp": 92,
    "heart_rate": 88,
    "bmi": 27.5,
    "hba1c": 9.2,
    "cholesterol": 215,
    "creatinine": 1.4,
    "input_method": "MANUAL"
  }'
```

Response bao gồm kết quả dự đoán ngay lập tức:

```json
{
  "reading": { ... },
  "prediction": {
    "risk_score": 0.82,
    "risk_level": "HIGH",
    "complications": {
      "nephropathy": 0.70,
      "retinopathy": 0.48,
      "cardiac": 0.55,
      "neuropathy": 0.35
    },
    "top_risk_factors": [
      {"feature": "glucose", "contribution": 0.35, "value": 280}
    ],
    "advice": "Nguy cơ cao. Liên hệ bác sĩ ngay hôm nay."
  }
}
```

### Xem lịch sử đo

```bash
curl http://localhost/api/readings/<patient_id> \
  -H "Authorization: Bearer <access_token>"
```

### Xem cảnh báo

```bash
curl http://localhost/api/alerts/<user_id> \
  -H "Authorization: Bearer <access_token>"
```

### Xem xu hướng 30 ngày

```bash
curl http://localhost/ml/predictions/<patient_id>/trend \
  -H "Authorization: Bearer <access_token>"
```

## Ngưỡng cảnh báo

| Điều kiện | Hành động |
|---|---|
| `risk_score > 0.9` | CRITICAL — cảnh báo ngay lập tức |
| `risk_score > 0.7` | HIGH — gửi cho bệnh nhân + bác sĩ |
| `glucose > 300` | Cảnh báo khẩn cấp (không cần model) |
| `glucose < 60` | Hạ đường huyết nguy hiểm |

## ML Model Architecture

```
Input (15 features)
  ├── Random Forest (n=200, depth=10)  → prob_rf
  └── LSTM (64→32→Dense)               → prob_lstm  [nếu ≥7 ngày lịch sử]
         ↓
  Ensemble: final = 0.4*rf + 0.6*lstm
         ↓
  Risk Level: <0.3=LOW, 0.3-0.7=MEDIUM, >0.7=HIGH, >0.9=CRITICAL
```

## Dừng hệ thống

```bash
docker-compose down
# Xóa data (cẩn thận!)
docker-compose down -v
```

## Cấu trúc thư mục

```
realtime-diabetes-prediction/
├── auth_service/       — FastAPI auth, JWT, user management
├── health_service/     — Health readings CRUD, alerts, Celery tasks
├── ml_service/         — RF+LSTM predictor, SHAP explainer, training
├── ml/                 — Jupyter notebooks (EDA, training, evaluation)
├── docker-compose.yml
├── nginx.conf
└── requirements.txt
```

## API Documentation

Khi hệ thống đang chạy:
- Auth Service docs: http://localhost:8000/docs
- Health Service docs: http://localhost:8001/docs
- ML Service docs: http://localhost:8002/docs
