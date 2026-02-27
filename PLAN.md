# PLAN.md — Real-time Diabetes Complication Prediction System
# READ THIS ENTIRE FILE BEFORE WRITING ANY CODE

---

## OVERVIEW

Build a full-stack real-time diabetes complication prediction system.
- Backend: FastAPI (Python 3.11)
- ML: Random Forest + LSTM Ensemble + SHAP explainability
- Database: PostgreSQL + Redis
- Notifications: Firebase FCM via Celery
- Containerized: Docker + Docker Compose

---

## FOLDER STRUCTURE TO CREATE

```
realtime-diabetes-prediction/
├── auth_service/
│   ├── main.py
│   ├── models.py
│   ├── schemas.py
│   ├── database.py
│   ├── dependencies.py
│   └── routers/
│       └── auth.py
│
├── health_service/
│   ├── main.py
│   ├── models.py
│   ├── schemas.py
│   ├── database.py
│   └── routers/
│       ├── readings.py
│       └── alerts.py
│   └── tasks.py              ← Celery tasks (send notifications)
│
├── ml_service/
│   ├── main.py
│   ├── predictor.py          ← EnsembleRiskPredictor class
│   ├── preprocessor.py       ← DataPreprocessor class
│   ├── explainer.py          ← SHAP explainer
│   ├── train.py              ← Training script
│   └── models/               ← Saved model files (.pkl, .h5)
│
├── ml/
│   ├── 01_EDA.ipynb
│   ├── 02_Preprocessing.ipynb
│   ├── 03_Training.ipynb
│   └── 04_Evaluation.ipynb
│
├── docker-compose.yml
├── nginx.conf
├── requirements.txt          ← shared dependencies
└── README.md
```

---

## DATABASE SCHEMA (PostgreSQL)

### Table: users
```sql
CREATE TABLE users (
    user_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name   VARCHAR(255) NOT NULL,
    role        VARCHAR(20) CHECK (role IN ('patient','doctor','admin')) NOT NULL,
    phone       VARCHAR(20),
    date_of_birth DATE,
    gender      VARCHAR(10),
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP DEFAULT NOW()
);
```

### Table: patient_profiles
```sql
CREATE TABLE patient_profiles (
    profile_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID REFERENCES users(user_id),
    doctor_id       UUID REFERENCES users(user_id),
    diabetes_type   VARCHAR(20),       -- 'Type1', 'Type2', 'Gestational'
    diagnosis_date  DATE,
    target_glucose  DECIMAL(5,2),
    medications     TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);
```

### Table: health_readings
```sql
CREATE TABLE health_readings (
    reading_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id      UUID REFERENCES users(user_id) NOT NULL,
    timestamp       TIMESTAMP DEFAULT NOW(),
    glucose         DECIMAL(5,2),      -- mg/dL, normal: 70-130
    systolic_bp     INTEGER,           -- mmHg
    diastolic_bp    INTEGER,           -- mmHg
    heart_rate      INTEGER,           -- bpm
    bmi             DECIMAL(4,1),
    hba1c           DECIMAL(3,1),      -- %, normal: <5.7
    cholesterol     DECIMAL(5,2),      -- mg/dL
    creatinine      DECIMAL(4,2),      -- mg/dL, kidney marker
    input_method    VARCHAR(20) DEFAULT 'MANUAL'  -- 'MANUAL','IOT','API'
);
```

### Table: predictions
```sql
CREATE TABLE predictions (
    prediction_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reading_id          UUID REFERENCES health_readings(reading_id),
    risk_score          DECIMAL(4,3),   -- 0.000 to 1.000
    risk_level          VARCHAR(10),    -- 'LOW','MEDIUM','HIGH','CRITICAL'
    nephropathy_prob    DECIMAL(4,3),
    retinopathy_prob    DECIMAL(4,3),
    cardiac_prob        DECIMAL(4,3),
    neuropathy_prob     DECIMAL(4,3),
    model_version       VARCHAR(20) DEFAULT 'v1.0',
    inference_time_ms   INTEGER,
    shap_values         JSONB,          -- feature contributions
    created_at          TIMESTAMP DEFAULT NOW()
);
```

### Table: alerts
```sql
CREATE TABLE alerts (
    alert_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prediction_id   UUID REFERENCES predictions(prediction_id),
    recipient_id    UUID REFERENCES users(user_id),
    alert_type      VARCHAR(20),   -- 'PUSH','EMAIL','SMS'
    severity        VARCHAR(20),   -- 'WARNING','DANGER','CRITICAL'
    message         TEXT,
    sent_at         TIMESTAMP DEFAULT NOW(),
    is_read         BOOLEAN DEFAULT FALSE,
    read_at         TIMESTAMP
);
```

---

## API ENDPOINTS

### auth_service (port 8000)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /auth/register | Đăng ký tài khoản mới |
| POST | /auth/login | Đăng nhập, trả JWT token |
| POST | /auth/logout | Đăng xuất |
| GET  | /auth/me | Lấy thông tin user hiện tại |
| PUT  | /auth/me | Cập nhật hồ sơ |

### health_service (port 8001)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/readings | Lưu chỉ số mới → tự động trigger dự đoán |
| GET  | /api/readings/{patient_id} | Lấy lịch sử đo |
| GET  | /api/readings/{patient_id}/latest | Lấy lần đo mới nhất |
| GET  | /api/alerts/{user_id} | Lấy danh sách cảnh báo |
| PUT  | /api/alerts/{alert_id}/read | Đánh dấu đã đọc |

### ml_service (port 8002)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /ml/predict | Dự đoán từ features |
| GET  | /ml/predictions/{patient_id} | Lịch sử dự đoán |
| GET  | /ml/predictions/{patient_id}/trend | Xu hướng 30 ngày |
| GET  | /ml/health | Kiểm tra model đã load chưa |

---

## ML MODEL SPECIFICATION

### Input Features (15 features)
```python
FEATURE_NAMES = [
    "glucose",           # mg/dL
    "systolic_bp",       # mmHg
    "diastolic_bp",      # mmHg
    "heart_rate",        # bpm
    "bmi",
    "hba1c",             # %
    "cholesterol",       # mg/dL
    "creatinine",        # mg/dL
    "age",
    "diabetes_duration", # years
    "glucose_7d_mean",   # rolling 7-day mean
    "bp_7d_mean",
    "hba1c_trend",       # positive = worsening
    "glucose_variability",
    "time_in_range",     # % time glucose 70-180
]
```

### Model 1: Random Forest
```python
RandomForestClassifier(
    n_estimators=200,
    max_depth=10,
    min_samples_split=5,
    class_weight='balanced',
    random_state=42
)
```

### Model 2: LSTM
```python
# Architecture:
Input → LSTM(64, return_sequences=True) → Dropout(0.2)
      → LSTM(32) → Dropout(0.2)
      → Dense(16, relu) → Dense(1, sigmoid)

# Input shape: (batch, 7, 15)  ← 7 ngày, 15 features mỗi ngày
# Compile: adam, binary_crossentropy
```

### Ensemble
```python
final_score = 0.4 * rf_prob + 0.6 * lstm_prob
```

### Risk Classification
```python
if final_score < 0.3:    risk_level = "LOW"
elif final_score < 0.7:  risk_level = "MEDIUM"
else:                    risk_level = "HIGH"
if final_score > 0.9:    risk_level = "CRITICAL"
```

### Preprocessing Pipeline
```python
# 1. Replace zero values in medical columns with NaN
# 2. Impute missing with median (SimpleImputer)
# 3. Clip outliers using IQR method
# 4. SMOTE for class balancing (training only)
# 5. StandardScaler normalize (fit on train set ONLY)
```

---

## PREDICTION RESPONSE FORMAT

```json
{
  "prediction_id": "uuid",
  "risk_score": 0.82,
  "risk_level": "HIGH",
  "complications": {
    "nephropathy": 0.70,
    "retinopathy": 0.48,
    "cardiac": 0.55,
    "neuropathy": 0.35
  },
  "top_risk_factors": [
    {"feature": "glucose", "contribution": 0.35, "value": 280},
    {"feature": "hba1c", "contribution": 0.28, "value": 9.2},
    {"feature": "systolic_bp", "contribution": 0.19, "value": 145}
  ],
  "advice": "Nguy cơ cao. Liên hệ bác sĩ ngay. Kiểm tra chức năng thận.",
  "inference_time_ms": 245
}
```

---

## ALERT LOGIC

Trigger alert when:
- risk_score > 0.7 → send to BOTH patient AND their doctor
- risk_score > 0.9 → mark as CRITICAL, send immediately
- glucose > 300 or glucose < 60 → emergency alert regardless of model

---

## DOCKER COMPOSE SERVICES

```yaml
services:
  postgres:     image postgres:15,    port 5432
  redis:        image redis:7-alpine, port 6379
  auth-service:    port 8000, depends on postgres
  health-service:  port 8001, depends on postgres + redis
  ml-service:      port 8002, RAM limit 2G
  celery-worker:   background tasks, depends on redis
  nginx:           port 80, routes to all services
```

---

## REQUIREMENTS.TXT (key packages)

```
fastapi==0.109.0
uvicorn==0.27.0
sqlalchemy==2.0.25
alembic==1.13.1
psycopg2-binary==2.9.9
redis==5.0.1
celery==5.3.6
python-jose[cryptography]==3.3.0   # JWT
passlib[bcrypt]==1.7.4
scikit-learn==1.4.0
tensorflow==2.15.0
shap==0.44.0
imbalanced-learn==0.11.0
pandas==2.1.4
numpy==1.26.3
pydantic==2.5.3
python-dotenv==1.0.0
httpx==0.26.0
```

---

## IMPLEMENTATION ORDER

Follow this order strictly:

1. **database.py** — SQLAlchemy setup, connection string from env
2. **models.py** — SQLAlchemy ORM models matching schema above
3. **schemas.py** — Pydantic request/response schemas
4. **auth_service** — Register, login with JWT
5. **health_service/routers/readings.py** — CRUD for health readings
6. **ml_service/preprocessor.py** — DataPreprocessor class
7. **ml_service/predictor.py** — EnsembleRiskPredictor class
8. **ml_service/explainer.py** — SHAP explainer
9. **ml_service/train.py** — Training script using Pima dataset
10. **ml_service/main.py** — FastAPI ML endpoints
11. **health_service/tasks.py** — Celery alert tasks
12. **health_service/routers/alerts.py** — Alert endpoints
13. **docker-compose.yml** — Wire everything together
14. **README.md** — Setup instructions

---

## ENVIRONMENT VARIABLES NEEDED

```env
DATABASE_URL=postgresql://admin:secret@postgres:5432/diabetes_db
REDIS_URL=redis://redis:6379/0
JWT_SECRET=your-super-secret-key-change-in-production
JWT_EXPIRE_MINUTES=1440
ML_SERVICE_URL=http://ml-service:8002
FIREBASE_CREDENTIALS=path/to/firebase.json
```

---

## IMPORTANT CONSTRAINTS

- All endpoints require JWT authentication except /auth/register and /auth/login
- StandardScaler must ONLY be fit on training data, never on full dataset
- LSTM requires minimum 7 days of readings; fall back to RF-only if less
- All UUIDs, never integer IDs
- Use async/await throughout FastAPI
- Include proper error handling (404, 422, 500) on all endpoints
- Log prediction results always, even on error

---

## DONE WHEN:

- [ ] All tables created via Alembic migration
- [ ] POST /auth/register and /auth/login working
- [ ] POST /api/readings saves data and returns prediction
- [ ] ML model loads and returns risk_score + shap explanation
- [ ] Alert fires when risk_score > 0.7
- [ ] docker-compose up starts entire system
- [ ] README has clear setup steps
