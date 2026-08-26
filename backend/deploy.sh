#!/bin/bash
# 用药管理平台 v2.0 - 一键部署脚本
# 在腾讯云服务器上以 root 身份运行：bash <(curl -sL ...)
# 或：wget -qO- .../deploy.sh | bash
set -e

DB_NAME="medication_db"
DB_PASS="MedicationDB2024Safe"
API_DIR="/var/www/medication-api"
WEB_DIR="/var/www/medication-web"
API_PORT=8000
GITHUB_RAW="https://raw.githubusercontent.com/jilisun87/medication-app-Description/main"

echo "=========================================="
echo "  用药管理平台 v2.0 - 一键部署"
echo "=========================================="

if [ "$EUID" -ne 0 ]; then
  echo "⚠️  请用 root 用户运行: sudo bash deploy.sh"
  exit 1
fi

# 1. 系统依赖
echo "[1/7] 安装系统依赖..."
apt update -qq 2>/dev/null || true
apt install -y -qq python3 python3-pip python3-venv mysql-server nginx curl wget >/dev/null 2>&1 || {
  apt install -y -qq python3 python3-pip python3-venv mariadb-server nginx curl wget >/dev/null 2>&1
}

# 2. MySQL 启动 + 配置
echo "[2/7] 配置数据库..."
systemctl start mysql 2>/dev/null || systemctl start mariadb
systemctl enable mysql 2>/dev/null || systemctl enable mariadb
sleep 2

# 设置密码（幂等）
mysql -e "ALTER USER IF EXISTS 'root'@'localhost' IDENTIFIED WITH mysql_native_password BY '${DB_PASS}';" 2>/dev/null || \
mysql -e "SET PASSWORD FOR 'root'@'localhost' = PASSWORD('${DB_PASS}');" 2>/dev/null || true
mysql -e "FLUSH PRIVILEGES;"

# 创建数据库
mysql -u root -p"${DB_PASS}" -e "CREATE DATABASE IF NOT EXISTS ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>&1

# 3. 建表
echo "[3/7] 创建数据表..."
mysql -u root -p"${DB_PASS}" ${DB_NAME} << 'EOSQL'
CREATE TABLE IF NOT EXISTS patients (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(50) NOT NULL,
    sex ENUM('男','女') DEFAULT NULL,
    age TINYINT UNSIGNED DEFAULT NULL,
    phone VARCHAR(20) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    edu_level VARCHAR(50) DEFAULT NULL,
    height_cm DECIMAL(5,1) DEFAULT NULL,
    weight_kg DECIMAL(5,1) DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS diseases (
    id VARCHAR(36) PRIMARY KEY,
    patient_id VARCHAR(36) NOT NULL,
    disease_name VARCHAR(100) NOT NULL,
    years SMALLINT UNSIGNED DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_patient (patient_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS allergies (
    id VARCHAR(36) PRIMARY KEY,
    patient_id VARCHAR(36) NOT NULL,
    allergen VARCHAR(100) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_patient (patient_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS medications (
    id VARCHAR(36) PRIMARY KEY,
    patient_id VARCHAR(36) NOT NULL,
    name VARCHAR(100) NOT NULL,
    dosage VARCHAR(100) NOT NULL,
    time TIME NOT NULL,
    schedule VARCHAR(50) NOT NULL DEFAULT '[0,1,2,3,4,5,6]',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_patient (patient_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS medication_logs (
    id VARCHAR(36) PRIMARY KEY,
    medication_id VARCHAR(36) NOT NULL,
    patient_id VARCHAR(36) NOT NULL,
    log_date DATE NOT NULL,
    checkin_time DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (medication_id) REFERENCES medications(id) ON DELETE CASCADE,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    UNIQUE KEY uk_med_date (medication_id, log_date),
    INDEX idx_patient_date (patient_id, log_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS adverse_reports (
    id VARCHAR(36) PRIMARY KEY,
    patient_id VARCHAR(36) NOT NULL,
    symptoms JSON NOT NULL,
    severity ENUM('轻度','中度','重度') NOT NULL,
    description TEXT DEFAULT NULL,
    photo_url VARCHAR(500) DEFAULT NULL,
    status ENUM('待处理','已回复','已关闭') DEFAULT '待处理',
    pharmacist_reply TEXT DEFAULT NULL,
    replied_at DATETIME DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_patient (patient_id),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS messages (
    id VARCHAR(36) PRIMARY KEY,
    patient_id VARCHAR(36) NOT NULL,
    conversation_id VARCHAR(36) NOT NULL,
    from_role ENUM('patient','pharmacist') NOT NULL,
    content TEXT DEFAULT NULL,
    photo_url VARCHAR(500) DEFAULT NULL,
    audio_url LONGTEXT DEFAULT NULL,
    audio_duration INT DEFAULT NULL,
    is_read TINYINT(1) DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (patient_id) REFERENCES patients(id) ON DELETE CASCADE,
    INDEX idx_conversation (conversation_id),
    INDEX idx_patient_unread (patient_id, is_read)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS pharmacist_accounts (
    id VARCHAR(36) PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(50) NOT NULL,
    dept VARCHAR(100) DEFAULT NULL,
    hospital VARCHAR(200) DEFAULT NULL,
    phone VARCHAR(20) DEFAULT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
EOSQL

# 4. 插入测试数据
echo "[4/7] 插入测试账号..."
PHARM_HASH=$(python3 -c "import hashlib; print(hashlib.md5(b'qdsl1234').hexdigest())")
PATIENT_HASH=$(python3 -c "import hashlib; print(hashlib.md5(b'12345').hexdigest())")

mysql -u root -p"${DB_PASS}" ${DB_NAME} -e "
INSERT IGNORE INTO pharmacist_accounts (id, username, password_hash, name, dept, hospital, phone)
VALUES ('pharm_001', 'pharmacist', '${PHARM_HASH}', '孙吉利', '临床药学科', '青岛市市立医院', '0532-82789206');

INSERT IGNORE INTO patients (id, name, sex, age, phone, password_hash, height_cm, weight_kg)
VALUES ('p_test_001', '张三', '男', 65, '13800001111', '${PATIENT_HASH}', 170, 65);
"

# 5. 下载后端 + 前端 + 部署
echo "[5/7] 下载并部署代码..."
mkdir -p ${API_DIR} ${WEB_DIR}

# 下载后端
wget -qO ${API_DIR}/app.py "${GITHUB_RAW}/backend/app.py"
echo "  ✓ 后端 app.py (${API_DIR}/app.py)"

# 下载前端文件
for f in index.html pharmacist.html pharmacist-login.html pharmacist-dashboard.html manifest.json sw.js; do
  wget -qO ${WEB_DIR}/${f} "${GITHUB_RAW}/${f}"
  echo "  ✓ ${f}"
done

# 6. Python 虚拟环境 + 依赖
echo "[6/7] 安装 Python 依赖..."
cd ${API_DIR}
python3 -m venv venv 2>/dev/null || true
source venv/bin/activate
pip install --upgrade pip -q 2>/dev/null
pip install fastapi 'uvicorn[standard]' pymysql pydantic 'python-jose[cryptography]' python-multipart -q

# 7. systemd + Nginx
echo "[7/7] 配置 systemd + Nginx..."

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

# 杀掉旧进程（如果有）
pkill -f "uvicorn app:app" 2>/dev/null || true
sleep 1

systemctl daemon-reload
systemctl restart medication-api
systemctl enable medication-api

# Nginx 配置
cat > /etc/nginx/sites-available/medication << 'EONGINX'
server {
    listen 80 default_server;
    server_name _;
    charset utf-8;
    client_max_body_size 30M;

    location / {
        root /var/www/medication-web;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 60s;
    }

    location = /docs { proxy_pass http://127.0.0.1:8000; }
    location = /openapi.json { proxy_pass http://127.0.0.1:8000; }
    location = /health { proxy_pass http://127.0.0.1:8000; }
}
EONGINX

ln -sf /etc/nginx/sites-available/medication /etc/nginx/sites-enabled/medication
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl restart nginx

# 等待服务启动
sleep 3

# 健康检查
echo ""
echo "=========================================="
echo "  健康检查"
echo "=========================================="

HEALTH=$(curl -s --max-time 5 http://localhost/health 2>&1)
echo "API Health: $HEALTH"

if echo "$HEALTH" | grep -q '"status":"ok"'; then
  echo ""
  echo "✅ 部署成功！"
  echo ""
  echo "访问地址: http://106.53.126.250"
  echo "  - 患者端: /index.html"
  echo "  - 药师端: /pharmacist.html"
  echo "  - 登录:   /pharmacist-login.html"
  echo "  - API文档: /docs"
  echo ""
  echo "测试账号："
  echo "  药师: pharmacist / qdsl1234"
  echo "  患者: 13800001111 / 12345 (张三)"
else
  echo "⚠️  API未正常响应，请查看日志:"
  echo "  journalctl -u medication-api -n 50 --no-pager"
fi