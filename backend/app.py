"""
用药管理平台 - 后端 API v2.0
FastAPI + MySQL + JWT认证
修复: DB重连/连接池, SQL bug, 密码hash一致性
"""

from fastapi import FastAPI, HTTPException, Header, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import datetime, date, timedelta
import pymysql
import pymysql.cursors
import uuid
import hashlib
import jwt
import json
import os
import traceback

# ============ 配置 ============
SECRET_KEY = "medication_platform_secret_key_2024_qd"
ALGORITHM = "HS256"
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "MedicationDB2024Safe",
    "database": "medication_db",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": False,
}

app = FastAPI(title="青岛市市立医院用药管理API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ 数据库连接（带自动重连） ============
_db_conn = None

def get_db():
    global _db_conn
    try:
        if _db_conn is None:
            _db_conn = pymysql.connect(**DB_CONFIG)
        _db_conn.ping(reconnect=True)
        return _db_conn
    except Exception:
        # 重试一次
        try:
            _db_conn = pymysql.connect(**DB_CONFIG)
            return _db_conn
        except Exception as e:
            raise HTTPException(500, f"数据库连接失败: {e}")

def query(sql, args=(), one=False, commit=False):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(sql, args)
        result = cur.fetchone() if one else cur.fetchall()
        if commit:
            conn.commit()
        return result
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        print(f"[SQL ERROR] {e}\n  SQL: {sql[:200]}\n  Args: {args}")
        raise HTTPException(500, f"数据库错误: {e}")
    finally:
        try:
            cur.close()
        except Exception:
            pass

# ============ 辅助函数 ============
def make_token(uid, role="patient"):
    payload = {"sub": uid, "role": role, "exp": datetime.utcnow() + timedelta(days=7)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(401, "未授权")
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(401, "无效认证")
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token已过期")
    except Exception:
        raise HTTPException(401, "Token无效")

def pw_hash(pw):
    return hashlib.md5(pw.encode()).hexdigest()

def make_id():
    return str(uuid.uuid4())

def pid_from_token(payload):
    return payload.get("sub")

def require_pharmacist(payload):
    if payload.get("role") != "pharmacist":
        raise HTTPException(403, "无权限")

def ok(data=None, message="success"):
    return {"code": 0, "message": message, "data": data}

# ============ 首页 ============
@app.get("/")
def root():
    return {"name": "青岛市市立医院用药管理API", "version": "2.0", "status": "running"}

@app.get("/health")
def health():
    try:
        query("SELECT 1")
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {"status": "ok", "db": db_status, "time": datetime.now().isoformat()}

# ============ 患者认证 ============
class PatientRegister(BaseModel):
    phone: str
    password: str
    name: str

class PatientLogin(BaseModel):
    phone: str
    password: str

@app.post("/api/patient/register")
def register(d: PatientRegister):
    exists = query("SELECT id FROM patients WHERE phone=%s", (d.phone,), one=True)
    if exists:
        raise HTTPException(400, "该手机号已注册")
    pid = make_id()
    query("INSERT INTO patients (id,phone,password_hash,name,created_at) VALUES (%s,%s,%s,%s,NOW())",
          (pid, d.phone, pw_hash(d.password), d.name), commit=True)
    return JSONResponse(ok({"token": make_token(pid), "patient_id": pid}))

@app.post("/api/patient/login")
def patient_login(d: PatientLogin):
    p = query("SELECT * FROM patients WHERE phone=%s AND password_hash=%s",
              (d.phone, pw_hash(d.password)), one=True)
    if not p:
        raise HTTPException(401, "手机号或密码错误")
    return JSONResponse(ok({
        "token": make_token(p["id"]),
        "patient_id": p["id"],
        "patient": {
            "id": p["id"], "name": p["name"], "sex": p["sex"], "age": p["age"],
            "phone": p["phone"],
            "height_cm": float(p["height_cm"]) if p["height_cm"] else None,
            "weight_kg": float(p["weight_kg"]) if p["weight_kg"] else None
        }
    }))

# ============ 患者档案 ============
class ProfileUpdate(BaseModel):
    name: str = None
    sex: str = None
    age: int = None
    height_cm: float = None
    weight_kg: float = None
    edu_level: str = None
    diseases: list = None
    allergies: list = None

@app.get("/api/patient/profile")
def get_profile(authorization: str = Header(None)):
    payload = verify_token(authorization)
    pid = pid_from_token(payload)
    p = query("SELECT * FROM patients WHERE id=%s", (pid,), one=True)
    if not p:
        raise HTTPException(404, "患者不存在")
    diseases = query("SELECT * FROM diseases WHERE patient_id=%s", (pid,))
    allergies = query("SELECT * FROM allergies WHERE patient_id=%s", (pid,))
    return JSONResponse(ok({
        "id": p["id"], "name": p["name"], "sex": p["sex"], "age": p["age"],
        "phone": p["phone"], "edu_level": p["edu_level"],
        "height_cm": float(p["height_cm"]) if p["height_cm"] else None,
        "weight_kg": float(p["weight_kg"]) if p["weight_kg"] else None,
        "diseases": [{"name": d["disease_name"], "years": d["years"]} for d in diseases],
        "allergies": [a["allergen"] for a in allergies]
    }))

@app.put("/api/patient/profile")
def update_profile(d: ProfileUpdate, authorization: str = Header(None)):
    payload = verify_token(authorization)
    pid = pid_from_token(payload)
    fields = {}
    if d.name is not None: fields["name"] = d.name
    if d.sex is not None: fields["sex"] = d.sex
    if d.age is not None: fields["age"] = d.age
    if d.height_cm is not None: fields["height_cm"] = d.height_cm
    if d.weight_kg is not None: fields["weight_kg"] = d.weight_kg
    if d.edu_level is not None: fields["edu_level"] = d.edu_level
    if fields:
        sets = ", ".join(f"{k}=%s" for k in fields.keys())
        query(f"UPDATE patients SET {sets}, updated_at=NOW() WHERE id=%s",
              (*fields.values(), pid), commit=True)
    if d.diseases is not None:
        query("DELETE FROM diseases WHERE patient_id=%s", (pid,), commit=True)
        for dis in d.diseases:
            if isinstance(dis, dict):
                query("INSERT INTO diseases (id,patient_id,disease_name,years) VALUES (%s,%s,%s,%s)",
                      (make_id(), pid, dis.get("name",""), dis.get("years",0)), commit=True)
            elif isinstance(dis, str):
                query("INSERT INTO diseases (id,patient_id,disease_name,years) VALUES (%s,%s,%s,%s)",
                      (make_id(), pid, dis, 0), commit=True)
    if d.allergies is not None:
        query("DELETE FROM allergies WHERE patient_id=%s", (pid,), commit=True)
        for alle in d.allergies:
            query("INSERT INTO allergies (id,patient_id,allergen) VALUES (%s,%s,%s)",
                  (make_id(), pid, alle), commit=True)
    return JSONResponse(ok(message="档案更新成功"))

# ============ 药品管理 ============
class MedInput(BaseModel):
    name: str
    dosage: str
    time: str
    schedule: list = None

@app.get("/api/medications")
def list_meds(authorization: str = Header(None)):
    payload = verify_token(authorization)
    pid = pid_from_token(payload)
    meds = query("SELECT * FROM medications WHERE patient_id=%s ORDER BY created_at DESC", (pid,))
    return JSONResponse(ok([{
        "id": m["id"], "name": m["name"], "dosage": m["dosage"],
        "time": str(m["time"]), "schedule": json.loads(m["schedule"]) if m["schedule"] else []
    } for m in meds]))

@app.post("/api/medications")
def add_med(d: MedInput, authorization: str = Header(None)):
    payload = verify_token(authorization)
    pid = pid_from_token(payload)
    mid = make_id()
    sched = json.dumps(d.schedule or [0,1,2,3,4,5,6])
    query("INSERT INTO medications (id,patient_id,name,dosage,time,schedule) VALUES (%s,%s,%s,%s,%s,%s)",
          (mid, pid, d.name, d.dosage, d.time, sched), commit=True)
    return JSONResponse(ok({"id": mid}))

@app.delete("/api/medications/{mid}")
def del_med(mid: str, authorization: str = Header(None)):
    payload = verify_token(authorization)
    pid = pid_from_token(payload)
    query("DELETE FROM medications WHERE id=%s AND patient_id=%s", (mid, pid), commit=True)
    return JSONResponse(ok())

# ============ 打卡 ============
@app.post("/api/medications/{mid}/checkin")
def checkin(mid: str, authorization: str = Header(None)):
    payload = verify_token(authorization)
    pid = pid_from_token(payload)
    today = date.today()
    med = query("SELECT * FROM medications WHERE id=%s AND patient_id=%s", (mid, pid), one=True)
    if not med:
        raise HTTPException(404, "药品不存在")
    existing = query("SELECT id FROM medication_logs WHERE medication_id=%s AND log_date=%s",
                     (mid, today), one=True)
    if existing:
        return JSONResponse(ok({"already": True}, message="今日已打卡"))
    lid = make_id()
    query("INSERT INTO medication_logs (id,medication_id,patient_id,log_date,checkin_time) VALUES (%s,%s,%s,%s,NOW())",
          (lid, mid, pid, today), commit=True)
    return JSONResponse(ok({"id": lid, "checkin_time": datetime.now().isoformat()}))

@app.get("/api/medication-logs")
def med_logs(month: str = None, authorization: str = Header(None)):
    payload = verify_token(authorization)
    pid = pid_from_token(payload)
    if month:
        rows = query("""SELECT ml.*, m.name as med_name FROM medication_logs ml
                        JOIN medications m ON ml.medication_id=m.id
                        WHERE ml.patient_id=%s AND DATE_FORMAT(ml.log_date,'%%Y-%%m')=%s
                        ORDER BY ml.log_date DESC""", (pid, month))
    else:
        rows = query("""SELECT ml.*, m.name as med_name FROM medication_logs ml
                        JOIN medications m ON ml.medication_id=m.id
                        WHERE ml.patient_id=%s ORDER BY ml.log_date DESC LIMIT 90""", (pid,))
    return JSONResponse(ok([{
        "date": str(r["log_date"]), "med_name": r["med_name"],
        "checkin_time": str(r["checkin_time"])
    } for r in rows]))

# ============ 不良反应 ============
class AdverseReport(BaseModel):
    symptoms: list
    severity: str
    description: str = None

@app.post("/api/adverse-reports")
def report_adr(d: AdverseReport, authorization: str = Header(None)):
    payload = verify_token(authorization)
    pid = pid_from_token(payload)
    rid = make_id()
    query("INSERT INTO adverse_reports (id,patient_id,symptoms,severity,description,status) VALUES (%s,%s,%s,%s,%s,'待处理')",
          (rid, pid, json.dumps(d.symptoms, ensure_ascii=False), d.severity, d.description), commit=True)
    return JSONResponse(ok({"id": rid}))

@app.get("/api/adverse-reports")
def list_adr(authorization: str = Header(None)):
    payload = verify_token(authorization)
    pid = pid_from_token(payload)
    rows = query("SELECT * FROM adverse_reports WHERE patient_id=%s ORDER BY created_at DESC", (pid,))
    return JSONResponse(ok([{
        "id": r["id"], "symptoms": json.loads(r["symptoms"]) if r["symptoms"] else [],
        "severity": r["severity"], "description": r["description"],
        "status": r["status"], "pharmacist_reply": r["pharmacist_reply"],
        "created_at": str(r["created_at"])
    } for r in rows]))

# ============ 消息 ============
class MessageInput(BaseModel):
    conversation_id: str = None
    content: str = None
    photo_base64: str = None
    audio_base64: str = None
    audio_duration: int = None

@app.get("/api/messages")
def get_messages(authorization: str = Header(None)):
    payload = verify_token(authorization)
    pid = pid_from_token(payload)
    rows = query("SELECT * FROM messages WHERE patient_id=%s ORDER BY created_at ASC LIMIT 200", (pid,))
    return JSONResponse(ok([{
        "id": r["id"], "from": r["from_role"], "content": r["content"],
        "photo_url": r["photo_url"], "audio_url": r["audio_url"],
        "audio_duration": r["audio_duration"],
        "time": str(r["created_at"])[11:16]
    } for r in rows]))

@app.post("/api/messages")
def send_message(d: MessageInput, authorization: str = Header(None)):
    payload = verify_token(authorization)
    pid = pid_from_token(payload)
    conv_id = d.conversation_id or f"conv_{pid}"
    mid = make_id()
    photo_url = f"data:image/jpeg;base64,{d.photo_base64}" if d.photo_base64 else None
    audio_url = f"data:audio/webm;base64,{d.audio_base64}" if d.audio_base64 else None
    query("""INSERT INTO messages (id,patient_id,conversation_id,from_role,content,photo_url,audio_url,audio_duration)
              VALUES (%s,%s,%s,'patient',%s,%s,%s,%s)""",
          (mid, pid, conv_id, d.content, photo_url, audio_url, d.audio_duration), commit=True)
    return JSONResponse(ok({"id": mid, "conversation_id": conv_id}))

@app.get("/api/conversations")
def get_convs(authorization: str = Header(None)):
    payload = verify_token(authorization)
    pid = pid_from_token(payload)
    rows = query("""SELECT conversation_id, content, created_at
                     FROM messages WHERE patient_id=%s
                     ORDER BY created_at DESC""", (pid,))
    if not rows:
        return JSONResponse(ok([]))
    convs = {}
    for r in rows:
        cid = r["conversation_id"]
        if cid not in convs:
            convs[cid] = {"id": cid, "last_message": r["content"], "last_time": str(r["created_at"])[0:16]}
    return JSONResponse(ok(list(convs.values())))

# ============ 药师端 API ============
class PharmLogin(BaseModel):
    username: str
    password: str

@app.post("/api/pharmacist/login")
def pharm_login(d: PharmLogin):
    p = query("SELECT * FROM pharmacist_accounts WHERE username=%s AND password_hash=%s",
              (d.username, pw_hash(d.password)), one=True)
    if not p:
        raise HTTPException(401, "账号或密码错误")
    return JSONResponse(ok({
        "token": make_token(p["id"], "pharmacist"),
        "pharmacist": {"id": p["id"], "name": p["name"], "dept": p["dept"], "hospital": p["hospital"]}
    }))

@app.get("/api/pharmacist/patients")
def pharm_patients(keyword: str = None, page: int = 1, page_size: int = 20,
                    authorization: str = Header(None)):
    payload = verify_token(authorization)
    require_pharmacist(payload)
    offset = (page - 1) * page_size
    if keyword:
        rows = query("""SELECT p.*,
                          (SELECT COUNT(DISTINCT ml.log_date) FROM medication_logs ml
                           JOIN medications m ON ml.medication_id=m.id
                           WHERE ml.patient_id=p.id AND ml.log_date>=DATE_SUB(CURDATE(),INTERVAL 30 DAY))
                          as taken_days
                          FROM patients p
                          WHERE p.name LIKE %s OR p.phone LIKE %s
                          ORDER BY p.created_at DESC LIMIT %s OFFSET %s""",
                     (f"%{keyword}%", f"%{keyword}%", page_size, offset))
        total = query("SELECT COUNT(*) as c FROM patients WHERE name LIKE %s OR phone LIKE %s",
                       (f"%{keyword}%", f"%{keyword}%"), one=True)["c"]
    else:
        rows = query("""SELECT p.*,
                          (SELECT COUNT(DISTINCT ml.log_date) FROM medication_logs ml
                           JOIN medications m ON ml.medication_id=m.id
                           WHERE ml.patient_id=p.id AND ml.log_date>=DATE_SUB(CURDATE(),INTERVAL 30 DAY))
                          as taken_days
                          FROM patients p ORDER BY p.created_at DESC LIMIT %s OFFSET %s""",
                     (page_size, offset))
        total = query("SELECT COUNT(*) as c FROM patients", one=True)["c"]
    patients = []
    for p in rows:
        diseases = query("SELECT disease_name,years FROM diseases WHERE patient_id=%s", (p["id"],))
        allergies = query("SELECT allergen FROM allergies WHERE patient_id=%s", (p["id"],))
        taken = p.get("taken_days") or 0
        adherence = round(taken / 30, 2) if taken else 0
        patients.append({
            "id": p["id"], "name": p["name"], "sex": p["sex"], "age": p["age"],
            "phone": p["phone"], "height_cm": float(p["height_cm"]) if p["height_cm"] else None,
            "weight_kg": float(p["weight_kg"]) if p["weight_kg"] else None,
            "adherence_rate": adherence,
            "diseases": [{"name": d["disease_name"], "years": d["years"]} for d in diseases],
            "allergies": [a["allergen"] for a in allergies],
            "created_at": str(p["created_at"])[0:10]
        })
    return JSONResponse(ok({"total": total, "page": page, "patients": patients}))

@app.get("/api/pharmacist/patients/{pid}")
def pharm_patient_detail(pid: str, authorization: str = Header(None)):
    payload = verify_token(authorization)
    require_pharmacist(payload)
    p = query("SELECT * FROM patients WHERE id=%s", (pid,), one=True)
    if not p:
        raise HTTPException(404, "患者不存在")
    diseases = query("SELECT * FROM diseases WHERE patient_id=%s", (pid,))
    allergies = query("SELECT * FROM allergies WHERE patient_id=%s", (pid,))
    meds = query("SELECT * FROM medications WHERE patient_id=%s", (pid,))
    logs = query("""SELECT ml.*, m.name as med_name FROM medication_logs ml
                     JOIN medications m ON ml.medication_id=m.id
                     WHERE ml.patient_id=%s AND ml.log_date>=DATE_SUB(CURDATE(),INTERVAL 30 DAY)
                     ORDER BY ml.log_date DESC""", (pid,))
    adrs = query("SELECT * FROM adverse_reports WHERE patient_id=%s ORDER BY created_at DESC LIMIT 10", (pid,))
    taken = len(set(str(l["log_date"]) for l in logs))
    adherence = round(taken / 30, 2)
    return JSONResponse(ok({
        "profile": {
            "id": p["id"], "name": p["name"], "sex": p["sex"], "age": p["age"],
            "phone": p["phone"], "edu_level": p["edu_level"],
            "height_cm": float(p["height_cm"]) if p["height_cm"] else None,
            "weight_kg": float(p["weight_kg"]) if p["weight_kg"] else None
        },
        "diseases": [{"name": d["disease_name"], "years": d["years"]} for d in diseases],
        "allergies": [a["allergen"] for a in allergies],
        "medications": [{"id": m["id"], "name": m["name"], "dosage": m["dosage"],
                         "time": str(m["time"]), "schedule": json.loads(m["schedule"]) if m["schedule"] else []}
                        for m in meds],
        "adherence": {"rate": adherence, "total_days": 30, "taken_days": taken},
        "recent_logs": [{"date": str(l["log_date"]), "med_name": l["med_name"]} for l in logs[:30]],
        "adverse_reports": [{"id": r["id"], "symptoms": json.loads(r["symptoms"]) if r["symptoms"] else [],
                              "severity": r["severity"], "status": r["status"],
                              "created_at": str(r["created_at"])} for r in adrs]
    }))

@app.get("/api/pharmacist/adverse-reports")
def pharm_adr_list(status: str = None, authorization: str = Header(None)):
    payload = verify_token(authorization)
    require_pharmacist(payload)
    if status:
        rows = query("""SELECT ar.*, p.name as patient_name, p.phone as patient_phone
                         FROM adverse_reports ar
                         JOIN patients p ON ar.patient_id=p.id
                         WHERE ar.status=%s ORDER BY ar.created_at DESC LIMIT 100""", (status,))
    else:
        rows = query("""SELECT ar.*, p.name as patient_name, p.phone as patient_phone
                         FROM adverse_reports ar
                         JOIN patients p ON ar.patient_id=p.id
                         ORDER BY ar.created_at DESC LIMIT 100""")
    return JSONResponse(ok([{
        "id": r["id"], "patient_id": r["patient_id"], "patient_name": r["patient_name"],
        "patient_phone": r["patient_phone"],
        "symptoms": json.loads(r["symptoms"]) if r["symptoms"] else [],
        "severity": r["severity"], "description": r["description"],
        "status": r["status"], "pharmacist_reply": r["pharmacist_reply"],
        "created_at": str(r["created_at"])
    } for r in rows]))

class PharmAdrReply(BaseModel):
    reply: str

@app.put("/api/pharmacist/adverse-reports/{rid}")
def pharm_reply_adr(rid: str, d: PharmAdrReply, authorization: str = Header(None)):
    payload = verify_token(authorization)
    require_pharmacist(payload)
    query("UPDATE adverse_reports SET status='已回复', pharmacist_reply=%s, replied_at=NOW() WHERE id=%s",
          (d.reply, rid), commit=True)
    return JSONResponse(ok())

@app.get("/api/pharmacist/messages")
def pharm_messages(authorization: str = Header(None)):
    payload = verify_token(authorization)
    require_pharmacist(payload)
    rows = query("""SELECT m.conversation_id, p.name as patient_name, p.id as patient_id,
                            p.phone as patient_phone,
                            MAX(m.created_at) as last_time,
                            (SELECT content FROM messages WHERE conversation_id=m.conversation_id
                             ORDER BY created_at DESC LIMIT 1) as last_message,
                            (SELECT COUNT(*) FROM messages WHERE conversation_id=m.conversation_id
                             AND is_read=0 AND from_role='patient') as unread
                     FROM messages m
                     JOIN patients p ON m.patient_id=p.id
                     GROUP BY m.conversation_id, p.name, p.id, p.phone
                     ORDER BY last_time DESC LIMIT 100""")
    return JSONResponse(ok([{
        "id": r["conversation_id"], "patient_name": r["patient_name"],
        "patient_id": r["patient_id"], "patient_phone": r["patient_phone"],
        "last_message": r["last_message"], "last_time": str(r["last_time"])[0:16] if r["last_time"] else "",
        "unread": r["unread"] or 0
    } for r in rows]))

@app.get("/api/pharmacist/messages/{conv_id}")
def pharm_conv_messages(conv_id: str, authorization: str = Header(None)):
    payload = verify_token(authorization)
    require_pharmacist(payload)
    rows = query("SELECT * FROM messages WHERE conversation_id=%s ORDER BY created_at ASC", (conv_id,))
    query("UPDATE messages SET is_read=1 WHERE conversation_id=%s AND from_role='patient'", (conv_id,), commit=True)
    return JSONResponse(ok([{
        "id": r["id"], "from": r["from_role"], "content": r["content"],
        "photo_url": r["photo_url"], "audio_url": r["audio_url"],
        "audio_duration": r["audio_duration"], "time": str(r["created_at"])[11:16]
    } for r in rows]))

class PharmReplyMsg(BaseModel):
    conversation_id: str
    content: str = None
    audio_base64: str = None
    audio_duration: int = None

@app.post("/api/pharmacist/messages/reply")
def pharm_reply(d: PharmReplyMsg, authorization: str = Header(None)):
    payload = verify_token(authorization)
    require_pharmacist(payload)
    # 获取 conversation_id 关联的 patient_id
    msg = query("SELECT patient_id FROM messages WHERE conversation_id=%s LIMIT 1", (d.conversation_id,), one=True)
    if not msg:
        raise HTTPException(404, "会话不存在")
    pid = msg["patient_id"]
    mid = make_id()
    audio_url = f"data:audio/webm;base64,{d.audio_base64}" if d.audio_base64 else None
    query("""INSERT INTO messages (id,patient_id,conversation_id,from_role,content,audio_url,audio_duration)
              VALUES (%s,%s,%s,'pharmacist',%s,%s,%s)""",
          (mid, pid, d.conversation_id, d.content, audio_url, d.audio_duration), commit=True)
    return JSONResponse(ok({"id": mid}))

class PharmGuideInput(BaseModel):
    content: str
    patient_id: str

@app.post("/api/pharmacist/guide")
def send_guide(d: PharmGuideInput, authorization: str = Header(None)):
    payload = verify_token(authorization)
    require_pharmacist(payload)
    conv_id = f"conv_{d.patient_id}"
    mid = make_id()
    query("INSERT INTO messages (id,patient_id,conversation_id,from_role,content) VALUES (%s,%s,%s,'pharmacist',%s)",
          (mid, d.patient_id, conv_id, f"[用药指导] {d.content}"), commit=True)
    return JSONResponse(ok({"id": mid}))

# ============ 静态文件（前端） ============
# 由 Nginx 处理，这里仅作 fallback
