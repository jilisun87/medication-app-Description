# 患者用药管理平台 - 后端设计方案

> 青岛市市立医院 临床药学科
> 版本：v1.0 | 日期：2024-08-23

---

## 一、部署架构

```
                         ┌──────────────┐
[患者端 PWA] ──────────▶│   CDN        │（加速静态资源，火山引擎/腾讯云COS）
                         └──────┬───────┘
                                │
┌──────────────┐               │  HTTPS
│ 药师端 Web    │──────────────┼────────▶ [API Server]────▶ [MySQL]
└──────────────┘               │  (Flask/FastAPI)          (云数据库)
                                │                   │
                         ┌──────▼───────┐          │
                         │  文件存储     │◀─────────┘
                         │ (腾讯COS/OSS) │（图片存储）
                         └──────────────┘
```

**推荐托管平台**：腾讯云（与微信生态兼容最好）

---

## 二、技术栈选型

| 层次 | 推荐方案 | 理由 |
|------|---------|------|
| 后端框架 | **Python FastAPI** | 异步高性能、自动生成API文档、类型安全、学习曲线平缓 |
| 数据库 | **MySQL 8.0** | 医院场景推荐，稳定可靠，云服务商托管 |
| 认证 | **JWT** | 无状态，适合移动端 + Web 端分离架构 |
| 图片存储 | **腾讯云COS** | 与微信生态对接最顺，按量付费 |
| API协议 | **RESTful JSON** | 简单直观，兼容现有前端 |

---

## 三、数据库设计

### 表1：patients（患者信息）

```sql
CREATE TABLE patients (
    id              VARCHAR(36)      PRIMARY KEY,           -- UUID
    name            VARCHAR(50)      NOT NULL COMMENT '患者姓名',
    sex             ENUM('男','女')  DEFAULT NULL          COMMENT '性别',
    age             TINYINT UNSIGNED DEFAULT NULL          COMMENT '年龄',
    phone           VARCHAR(20)      NOT NULL UNIQUE       COMMENT '联系电话',
    password_hash   VARCHAR(255)     NOT NULL              COMMENT '密码（bcrypt）',
    edu_level       VARCHAR(50)      DEFAULT NULL          COMMENT '教育水平',
    height_cm       DECIMAL(5,1)    DEFAULT NULL          COMMENT '身高(cm)',
    weight_kg       DECIMAL(5,1)    DEFAULT NULL          COMMENT '体重(kg)',
    created_at      DATETIME         DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME         DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='患者基本信息';
```

> 设计理由：phone 作为患者唯一标识（手机号=账号），JWT token 关联 patient_id。

---

### 表2：diseases（既往病史）

```sql
CREATE TABLE diseases (
    id              VARCHAR(36)      PRIMARY KEY,
    patient_id      VARCHAR(36)      NOT NULL,
    disease_name    VARCHAR(100)     NOT NULL COMMENT '病名',
    years           SMALLINT UNSIGNED DEFAULT 0   COMMENT '患病年限',
    created_at      DATETIME         DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_patient (patient_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='既往病史';
```

---

### 表3：allergies（过敏史）

```sql
CREATE TABLE allergies (
    id              VARCHAR(36)      PRIMARY KEY,
    patient_id      VARCHAR(36)      NOT NULL,
    allergen        VARCHAR(100)     NOT NULL COMMENT '过敏原',
    created_at      DATETIME         DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_patient (patient_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='过敏史';
```

---

### 表4：medications（药品记录）

```sql
CREATE TABLE medications (
    id              VARCHAR(36)      PRIMARY KEY,
    patient_id      VARCHAR(36)      NOT NULL,
    name            VARCHAR(100)     NOT NULL COMMENT '药品名称',
    dosage          VARCHAR(100)     NOT NULL COMMENT '剂量/用法',
    time            TIME             NOT NULL COMMENT '服药时间',
    schedule        VARCHAR(20)      NOT NULL COMMENT '周期，如0,1,2,3,4,5,6',
    created_at      DATETIME         DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME         DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_patient (patient_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='药品记录';
```

> schedule 存 JSON 数组序列化字符串：周一=1，周日=0。

---

### 表5：medication_logs（打卡记录）

```sql
CREATE TABLE medication_logs (
    id              VARCHAR(36)      PRIMARY KEY,
    medication_id    VARCHAR(36)      NOT NULL,
    patient_id      VARCHAR(36)      NOT NULL,
    log_date        DATE             NOT NULL COMMENT '打卡日期',
    checkin_time    DATETIME         NOT NULL COMMENT '打卡时间',
    created_at      DATETIME         DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (medication_id) REFERENCES medications(id) ON DELETE CASCADE,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    UNIQUE KEY uk_med_date (medication_id, log_date),  -- 每天每药只记一次
    INDEX idx_patient_date (patient_id, log_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='服药打卡记录';
```

> UNIQUE KEY 防止重复打卡。

---

### 表6：adverse_reports（不良反应上报）

```sql
CREATE TABLE adverse_reports (
    id              VARCHAR(36)      PRIMARY KEY,
    patient_id      VARCHAR(36)      NOT NULL,
    symptoms        JSON             NOT NULL COMMENT '症状列表 JSON数组',
    severity        ENUM('轻度','中度','重度') NOT NULL COMMENT '严重程度',
    description     TEXT             DEFAULT NULL       COMMENT '详细描述',
    photo_url       VARCHAR(500)     DEFAULT NULL       COMMENT '照片COS路径',
    status          ENUM('待处理','已回复','已关闭') DEFAULT '待处理',
    pharmacist_reply TEXT            DEFAULT NULL       COMMENT '药师回复',
    replied_at      DATETIME         DEFAULT NULL,
    created_at      DATETIME         DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_patient (patient_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='不良反应上报';
```

---

### 表7：messages（消息记录）

```sql
CREATE TABLE messages (
    id              VARCHAR(36)      PRIMARY KEY,
    patient_id      VARCHAR(36)      NOT NULL,
    conversation_id VARCHAR(36)      NOT NULL,
    from_role       ENUM('patient','pharmacist') NOT NULL,
    content         TEXT             DEFAULT NULL,
    photo_url       VARCHAR(500)     DEFAULT NULL,
    is_read         TINYINT(1)      DEFAULT 0,
    created_at      DATETIME         DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_conversation (conversation_id),
    INDEX idx_patient_unread (patient_id, is_read)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='消息记录';
```

---

### 表8：pharmacist_accounts（药师账号）

```sql
CREATE TABLE pharmacist_accounts (
    id              VARCHAR(36)      PRIMARY KEY,
    username        VARCHAR(50)      NOT NULL UNIQUE,
    password_hash   VARCHAR(255)     NOT NULL,
    name            VARCHAR(50)      NOT NULL COMMENT '药师姓名',
    dept            VARCHAR(100)     DEFAULT NULL COMMENT '科室',
    hospital        VARCHAR(200)     DEFAULT NULL COMMENT '医院',
    phone           VARCHAR(20)      DEFAULT NULL,
    created_at      DATETIME         DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='药师账号';
```

---

## 四、API 设计

### 患者端 API

#### 1. 患者注册/登录
```
POST /api/patient/register
Body: { "phone": "138****1234", "password": "xxx", "name": "张三" }
Response: { "code": 0, "data": { "token": "eyJ...", "patient": {...} } }
```

```
POST /api/patient/login
Body: { "phone": "138****1234", "password": "xxx" }
Response: { "code": 0, "data": { "token": "eyJ...", "patient": {...} } }
```

#### 2. 获取/更新患者档案
```
GET /api/patient/profile
Header: Authorization: Bearer <token>
Response: { "code": 0, "data": { "name": "张三", "sex": "男", ... } }
```

```
PUT /api/patient/profile
Header: Authorization: Bearer <token>
Body: { "name": "张三", "sex": "男", "age": 65, "height_cm": 170, "weight_kg": 70,
        "diseases": [{"name": "高血压", "years": 8}],
        "allergies": ["青霉素"] }
Response: { "code": 0, "message": "更新成功" }
```

#### 3. 药品管理
```
GET /api/medications
Header: Authorization: Bearer <token>
Response: { "code": 0, "data": [{ "id": "...", "name": "硝苯地平", "dosage": "30mg", ... }] }
```

```
POST /api/medications
Header: Authorization: Bearer <token>
Body: { "name": "硝苯地平控释片", "dosage": "30mg", "time": "07:00", "schedule": [0,1,2,3,4,5,6] }
Response: { "code": 0, "data": { "id": "med_xxx" } }
```

```
DELETE /api/medications/{id}
Header: Authorization: Bearer <token>
Response: { "code": 0 }
```

#### 4. 打卡
```
POST /api/medications/{id}/checkin
Header: Authorization: Bearer <token>
Body: {}
Response: { "code": 0, "message": "打卡成功", "data": { "checkin_time": "2024-08-23 07:05" } }
```

#### 5. 用药记录日历
```
GET /api/medication-logs?month=2024-08
Header: Authorization: Bearer <token>
Response: {
  "code": 0, "data": {
    "2024-08-01": ["med1", "med2"],
    "2024-08-02": ["med1"]
  }
}
```

#### 6. 不良反应上报
```
POST /api/adverse-reports
Header: Authorization: Bearer <token>
Content-Type: multipart/form-data
Body: {
  "symptoms": ["恶心", "头晕"],
  "severity": "中度",
  "description": "服药后2小时出现...",
  "photo": <file>
}
Response: { "code": 0, "data": { "id": "rep_xxx" } }
```

#### 7. 消息
```
GET /api/messages?conversation_id=conv_xxx
Header: Authorization: Bearer <token>
Response: { "code": 0, "data": [{ "id": "m1", "from": "patient", "content": "...", "time": "10:30" }, ...] }
```

```
POST /api/messages
Header: Authorization: Bearer <token>
Body: { "conversation_id": "conv_xxx", "content": "药师你好", "photo_base64": "..." }
Response: { "code": 0, "data": { "id": "m_xxx", "created_at": "..." } }
```

---

### 药师端 API

#### 1. 药师登录
```
POST /api/pharmacist/login
Body: { "username": "pharmacist", "password": "xxx" }
Response: { "code": 0, "data": { "token": "eyJ...", "pharmacist": { "name": "孙药师", ... } } }
```

#### 2. 患者列表（支持搜索+分页）
```
GET /api/pharmacist/patients?keyword=张&page=1&page_size=20
Header: Authorization: Bearer <token>
Response: {
  "code": 0, "data": {
    "total": 156,
    "page": 1,
    "patients": [
      { "id": "p001", "name": "张华", "sex": "男", "age": 67, "adherence_rate": 0.92, ... }
    ]
  }
}
```

> adherence_rate 由后端统计最近30天打卡情况计算得出。

#### 3. 患者详情
```
GET /api/pharmacist/patients/{id}
Header: Authorization: Bearer <token>
Response: { "code": 0, "data": {
  "profile": {...},
  "diseases": [...],
  "allergies": [...],
  "medications": [...],
  "adherence": { "rate": 0.92, "total_days": 30, "taken_days": 28 }
}}
```

#### 4. 不良反应列表
```
GET /api/pharmacist/adverse-reports?status=待处理&page=1
Header: Authorization: Bearer <token>
Response: { "code": 0, "data": { "total": 5, "reports": [...] } }
```

#### 5. 处理不良反应
```
PUT /api/pharmacist/adverse-reports/{id}
Header: Authorization: Bearer <token>
Body: { "status": "已回复", "reply": "您好，根据您描述的情况…" }
Response: { "code": 0 }
```

#### 6. 发送用药指导
```
POST /api/pharmacist/guide
Header: Authorization: Bearer <token>
Body: { "patient_id": "p001", "content": "硝苯地平请整片吞服…" }
Response: { "code": 0 }
```

#### 7. 患者消息列表
```
GET /api/pharmacist/messages
Header: Authorization: Bearer <token>
Response: { "code": 0, "data": { "conversations": [...] } }
```

#### 8. 回复患者消息
```
POST /api/pharmacist/messages/reply
Header: Authorization: Bearer <token>
Body: { "conversation_id": "conv_xxx", "content": "您好…" }
Response: { "code": 0, "data": { "id": "m_xxx" } }
```

---

## 五、数据同步策略

### 离线优先方案（患者端）

```
患者端                        后端
  │                            │
  │  localStorage（本地数据）     │
  │       │                    │
  ├─── 打开App ────────────▶  拉取最新数据
  │                            │
  │   操作（打卡/发消息）         │
  │       │                    │
  ├─── 写入localStorage ───▶  异步上传到服务器
  │       │                    │
  │  网络异常/离线               │
  │       │                    │
  └── 缓存操作 ──────────────▶  网络恢复后重发
```

**冲突处理**：以服务器时间戳为准，后写入覆盖。

**离线队列**：患者操作存入 `pending_sync` 队列，联网后按顺序上传。

### 实时推送（药师端）

药师端不需要 WebSocket，用**轮询**即可（30秒轮询一次消息接口）。

药师端操作（回复消息/处理不良反应）直接通过 API → 数据库，患者端下次请求时自动拉取最新。

---

## 六、安全考虑

| 方面 | 措施 |
|------|------|
| 传输加密 | 全站 HTTPS |
| 密码存储 | bcrypt 哈希，不存明文 |
| JWT | 有效期7天，患者 refresh token |
| 药师权限 | 独立 JWT，只能看自己的患者 |
| 患者数据隔离 | 药师只能看到自己负责的患者 |
| 图片上传 | 文件类型校验 + 大小限制（≤5MB）|
| SQL注入 | ORM (SQLAlchemy) 参数化查询 |
| 敏感字段 | phone/姓名等不日志记录 |

---

## 七、实施计划

### 第一阶段（1-2周）：基础后端
- [ ] 数据库建表 + 迁移脚本
- [ ] FastAPI 骨架 + JWT 认证
- [ ] 患者端 API 实现
- [ ] 药师端 API 实现
- [ ] 腾讯云 COS 图片上传

### 第二阶段（1周）：联通测试
- [ ] 前端 API 对接（替换 Mock 数据）
- [ ] localStorage 同步逻辑
- [ ] 药师端消息实时拉取

### 第三阶段（1周）：部署上线
- [ ] 腾讯云服务器部署
- [ ] 域名 + HTTPS
- [ ] 药师账号开通
- [ ] 患者试用反馈

---

*文档版本：v1.0 | 制定人：孙药师 | 日期：2024-08-23*
