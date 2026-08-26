#!/bin/bash
# 用药管理平台 v2.0 - 一键部署脚本
# 修复: DB密码统一, systemd自启动, Nginx正确代理
set -e

echo "=========================================="
echo "  用药管理平台 v2.0 - 自动化部署"
echo "=========================================="

DB_NAME="medication_db"
DB_USER="root"
DB_PASS="MedicationDB2024Safe"
API_DIR="/var/www/medication-api"
WEB_DIR="/var/www/medication-web"
API_PORT=8000

if [ "$EUID" -ne 0 ]; then
  echo "请用 root 运行: sudo bash deploy.sh"
  exit 1
fi

# 1. 系统更新
echo "[1/9] 安装系统依赖..."
apt update -qq
apt install -y -qq python3 python3-pip python3-venv mysql-server nginx curl git >/dev/null 2>&1

# 2. MySQL
echo "[2/9] 配置 MySQL..."
systemctl start mysql
systemctl enable mysql
# 设置密码（幂等）
mysql -e "ALTER USER IF EXISTS 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '${DB_PASS}';" 2>/dev/null || true
mysql -e "FLUSH PRIVILEGES;"

# 3. 数据库
echo "[3/9] 创建数据库..."
mysql -u root -p"${DB_PASS}" -e "CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 4. 建表
echo "[4/9] 创建数据表..."
mysql -u root -p"${DB_PASS}" ${DB_NAME} << 'EOSQL'
CREATE TABLE IF NOT EXISTS patients (
    id              VARCHAR(36) PRIMARY KEY,
    name            VARCHAR(50) NOT NULL,
    sex             ENUM('男','女') DEFAULT NULL,
    age             TINYINT UNSIGNED DEFAULT NULL,
    phone           VARCHAR(20) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    edu_level       VARCHAR(50) DEFAULT NULL,
    height_cm       DECIMAL(5,1) DEFAULT NULL,
    weight_kg       DECIMAL(5,1) DEFAULT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS diseases (
    id              VARCHAR(36) PRIMARY KEY,
    patient_id      VARCHAR(36) NOT NULL,
    disease_name    VARCHAR(100) NOT NULL,
    years           SMALLINT UNSIGNED DEFAULT 0,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_patient (patient_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS allergies (
    id              VARCHAR(36) PRIMARY KEY,
    patient_id      VARCHAR(36) NOT NULL,
    allergen        VARCHAR(100) NOT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_patient (patient_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS medications (
    id              VARCHAR(36) PRIMARY KEY,
    patient_id      VARCHAR(36) NOT NULL,
    name            VARCHAR(100) NOT NULL,
    dosage          VARCHAR(100) NOT NULL,
    time            TIME NOT NULL,
    schedule        VARCHAR(50) NOT NULL DEFAULT '[0,1,2,3,4,5,6]',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_patient (patient_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS medication_logs (
    id              VARCHAR(36) PRIMARY KEY,
    medication_id   VARCHAR(36) NOT NULL,
    patient_id      VARCHAR(36) NOT NULL,
    log_date        DATE NOT NULL,
    checkin_time    DATETIME NOT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (medication_id) REFERENCES medications(id) ON DELETE CASCADE,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    UNIQUE KEY uk_med_date (medication_id, log_date),
    INDEX idx_patient_date (patient_id, log_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS adverse_reports (
    id              VARCHAR(36) PRIMARY KEY,
    patient_id      VARCHAR(36) NOT NULL,
    symptoms        JSON NOT NULL,
    severity        ENUM('轻度','中度','重度') NOT NULL,
    description     TEXT DEFAULT NULL,
    photo_url       VARCHAR(500) DEFAULT NULL,
    status          ENUM('待处理','已回复','已关闭') DEFAULT '待处理',
    pharmacist_reply TEXT DEFAULT NULL,
    replied_at      DATETIME DEFAULT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_patient (patient_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS messages (
    id              VARCHAR(36) PRIMARY KEY,
    patient_id      VARCHAR(36) NOT NULL,
    conversation_id VARCHAR(36) NOT NULL,
    from_role       ENUM('patient','pharmacist') NOT NULL,
    content         TEXT DEFAULT NULL,
    photo_url       VARCHAR(500) DEFAULT NULL,
    audio_url       LONGTEXT DEFAULT NULL,
    audio_duration  INT DEFAULT NULL,
    is_read         TINYINT(1) DEFAULT 0,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_conversation (conversation_id),
    INDEX idx_patient_unread (patient_id, is_read)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS pharmacist_accounts (
    id              VARCHAR(36) PRIMARY KEY,
    username        VARCHAR(50) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    name            VARCHAR(50) NOT NULL,
    dept            VARCHAR(100) DEFAULT NULL,
    hospital        VARCHAR(200) DEFAULT NULL,
    phone           VARCHAR(20) DEFAULT NULL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
EOSQL

# 5. 插入测试数据（幂等）
echo "[5/9] 插入测试数据..."
# 药师: pharmacist / qdsl1234
PHARM_HASH=$(python3 -c "import hashlib; print(hashlib.md5(b'qdsl1234').hexdigest())")
mysql -u root -p"${DB_PASS}" ${DB_NAME} -e "
INSERT IGNORE INTO pharmacist_accounts (id, username, password_hash, name, dept, hospital, phone)
VALUES ('pharm_001', 'pharmacist', '${PHARM_HASH}', '孙吉利', '临床药学科', '青岛市市立医院', '0532-82789206');
"

# 测试患者: 张三 / 13800001111 / 12345
PATIENT_HASH=$(python3 -c "import hashlib; print(hashlib.md5(b'12345').hexdigest())")
mysql -u root -p"${DB_PASS}" ${DB_NAME} -e "
INSERT IGNORE INTO patients (id, name, sex, age, phone, password_hash, height_cm, weight_kg)
VALUES ('p_test_001', '张三', '男', 65, '13800001111', '${PATIENT_HASH}', 170, 65);
"

echo "  药师: pharmacist / qdsl1234"
echo "  患者: 张三 / 13800001111 / 12345"

# 6. Python 环境
echo "[6/9] 安装 Python 依赖..."
mkdir -p ${API_DIR}
cd ${API_DIR}
python3 -m venv venv 2>/dev/null || true
source venv/bin/activate
pip install --upgrade pip -q
pip install fastapi uvicorn[standard] pymysql pydantic python-jose[cryptography] python-multipart -q

# 7. 复制后端代码
echo "[7/9] 部署后端代码..."
cp -f app.py ${API_DIR}/app.py

# 8. systemd 服务
echo "[8/9] 配置 systemd 服务..."
cat > /etc/systemd/system/medication-api.service << EOUNIT
[Unit]
Description=Medication API Service v2
After=network.target mysql.service

[Service]
User=root
WorkingDirectory=${API_DIR}
ExecStart=${API_DIR}/venv/bin/uvicorn app:app --host 0.0.0.0 --port ${API_PORT}
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOUNIT

systemctl daemon-reload
systemctl restart medication-api
systemctl enable medication-api

# 9. Nginx
echo "[9/9] 配置 Nginx..."
mkdir -p ${WEB_DIR}

cat > /etc/nginx/sites-available/medication << 'EONGINX'
server {
    listen 80;
    server_name _;
    charset utf-8;
    client_max_body_size 30M;

    # 前端静态文件
    location / {
        root /var/www/medication-web;
        index index.html pharmacist.html;
        try_files $uri $uri/ /index.html;
    }

    # API 代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 60s;
    }

    # API docs
    location /docs {
        proxy_pass http://127.0.0.1:8000;
    }
    location /openapi.json {
        proxy_pass http://127.0.0.1:8000;
    }
    location /health {
        proxy_pass http://127.0.0.1:8000;
    }
}
EONGINX

ln -sf /etc/nginx/sites-available/medication /etc/nginx/sites-enabled/medication
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

# 等待服务启动
sleep 2

echo ""
echo "=========================================="
echo "  部署完成!"
echo "=========================================="
echo "API:      http://localhost/api/"
echo "患者端:   http://<服务器IP>/"
echo "药师端:   http://<服务器IP>/pharmacist.html"
echo "API文档:  http://<服务器IP>/docs"
echo ""
echo "药师: pharmacist / qdsl1234"
echo "患者: 张三 / 13800001111 / 12345"
echo ""
echo "状态: systemctl status medication-api"
echo "日志: journalctl -u medication-api -f --no-pager -n 50"
echo "=========================================="
