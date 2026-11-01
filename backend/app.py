import os, json, uuid, re, smtplib, base64, threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timedelta, timezone, date
import mysql.connector, requests, jwt
from pwdlib import PasswordHash
from openai import OpenAI
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from typing import Literal
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as PDFImage, ListFlowable, ListItem
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from xml.sax.saxutils import escape
from fastapi.responses import FileResponse, StreamingResponse
from dotenv import load_dotenv
from email.message import EmailMessage
from apscheduler.schedulers.background import BackgroundScheduler
from PIL import Image, ImageOps
from io import BytesIO

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
UPLOAD_DIR = ROOT / "uploads"; REPORT_DIR = ROOT / "reports"
UPLOAD_DIR.mkdir(exist_ok=True); REPORT_DIR.mkdir(exist_ok=True)
DB = {"host":os.getenv("DB_HOST","localhost"),"port":int(os.getenv("DB_PORT","3306")),"user":os.getenv("DB_USER","root"),"password":os.getenv("DB_PASSWORD",""),"database":os.getenv("DB_NAME","kisan_mitra")}
SECRET_KEY=os.getenv("JWT_SECRET","CHANGE_THIS_SECRET_BEFORE_RUNNING")
ALGORITHM="HS256"; TOKEN_MINUTES=240
MAX_IMAGE_BYTES=8*1024*1024
ALLOWED_EXT={".jpg",".jpeg",".png",".webp"}
app=FastAPI(title="Kisan Mitra API", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=[x.strip() for x in os.getenv("CORS_ORIGINS","http://localhost:5500,http://127.0.0.1:5500").split(",")], allow_credentials=False, allow_methods=["GET","POST","PUT","PATCH","DELETE"], allow_headers=["Authorization","Content-Type"])
password_hash=PasswordHash.recommended(); oauth2_scheme=OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def db(): return mysql.connector.connect(**DB)
def init_db():
    base={k:v for k,v in DB.items() if k!="database"}
    c=mysql.connector.connect(**base); cur=c.cursor(); dbname=DB["database"]
    if not re.fullmatch(r"[A-Za-z0-9_]+",dbname): raise RuntimeError("DB_NAME may contain only letters, numbers and underscores")
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{dbname}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"); cur.close(); c.close()
    c=db(); cur=c.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users(id INT AUTO_INCREMENT PRIMARY KEY, full_name VARCHAR(120) NOT NULL, email VARCHAR(190) NOT NULL UNIQUE, password_hash VARCHAR(255) NOT NULL, role VARCHAR(20) NOT NULL DEFAULT 'farmer', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS crop_reports(id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, crop VARCHAR(100) NOT NULL, disease VARCHAR(200) NOT NULL, confidence DECIMAL(6,2) NOT NULL DEFAULT 0, severity VARCHAR(50), symptoms JSON, treatment JSON, prevention JSON, warning TEXT, recommendation TEXT, image_path VARCHAR(500), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)""")
    # Add columns safely for databases created by the older v2 project.
    cur.execute("SHOW COLUMNS FROM crop_reports"); existing={r[0] for r in cur.fetchall()}
    for col,ddl in [("symptoms","JSON NULL"),("treatment","JSON NULL"),("prevention","JSON NULL"),("warning","TEXT NULL")]:
        if col not in existing: cur.execute(f"ALTER TABLE crop_reports ADD COLUMN {col} {ddl}")
    cur.execute("SHOW COLUMNS FROM users"); ucols={r[0] for r in cur.fetchall()}
    if "role" not in ucols: cur.execute("ALTER TABLE users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'farmer'")
    cur.execute("UPDATE users SET role='farmer' WHERE role='user' OR role IS NULL OR role=''")
    cur.execute("""CREATE TABLE IF NOT EXISTS mandi_prices(
        id INT AUTO_INCREMENT PRIMARY KEY,
        state VARCHAR(100) NOT NULL,
        district VARCHAR(150) NOT NULL,
        market VARCHAR(255) NOT NULL,
        commodity VARCHAR(150) NOT NULL,
        variety VARCHAR(150),
        grade VARCHAR(100),
        arrival_date DATE,
        min_price DECIMAL(12,2),
        max_price DECIMAL(12,2),
        modal_price DECIMAL(12,2),
        INDEX idx_mandi_location (state, district),
        INDEX idx_mandi_commodity (state, district, commodity),
        INDEX idx_mandi_date (arrival_date)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS user_preferences (
        user_id INT PRIMARY KEY,
        language VARCHAR(30) NOT NULL DEFAULT 'en',
        email_address VARCHAR(190),
        email_enabled TINYINT(1) NOT NULL DEFAULT 0,
        weather_alerts TINYINT(1) NOT NULL DEFAULT 1,
        crop_reminders TINYINT(1) NOT NULL DEFAULT 1,
        notification_consent TINYINT(1) NOT NULL DEFAULT 0,
        latitude DECIMAL(10,7),
        longitude DECIMAL(10,7),
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS farm_calendar_events (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        title VARCHAR(160) NOT NULL,
        description TEXT,
        event_type VARCHAR(40) NOT NULL DEFAULT 'other',
        event_date DATE NOT NULL,
        reminder_days_before INT NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        INDEX idx_calendar_due (event_date, user_id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS notification_logs (
        id INT AUTO_INCREMENT PRIMARY KEY,
        user_id INT NOT NULL,
        event_id INT NULL,
        channel VARCHAR(20) NOT NULL,
        notification_type VARCHAR(40) NOT NULL,
        fingerprint VARCHAR(190) NOT NULL,
        status VARCHAR(20) NOT NULL,
        detail VARCHAR(500),
        sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        INDEX idx_notification_dedupe (user_id, fingerprint, channel, status)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS marketplace_profiles(
        user_id INT PRIMARY KEY, account_type VARCHAR(20) NOT NULL DEFAULT 'both',
        phone VARCHAR(30), state VARCHAR(100), district VARCHAR(150),
        latitude DECIMAL(10,7), longitude DECIMAL(10,7),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS crop_listings(
        id INT AUTO_INCREMENT PRIMARY KEY, seller_id INT NOT NULL,
        commodity VARCHAR(120) NOT NULL, variety VARCHAR(120), quality_grade VARCHAR(80),
        quantity_quintals DECIMAL(12,2) NOT NULL, available_quintals DECIMAL(12,2) NOT NULL,
        asking_price DECIMAL(12,2) NOT NULL, state VARCHAR(100) NOT NULL,
        district VARCHAR(150) NOT NULL, pickup_location VARCHAR(255), description TEXT,
        status VARCHAR(20) NOT NULL DEFAULT 'active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(seller_id) REFERENCES users(id) ON DELETE CASCADE,
        INDEX idx_listing_search(status,commodity,state,district)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS marketplace_offers(
        id INT AUTO_INCREMENT PRIMARY KEY, listing_id INT NOT NULL, buyer_id INT NOT NULL,
        seller_id INT NOT NULL, quantity_quintals DECIMAL(12,2) NOT NULL,
        offered_price DECIMAL(12,2) NOT NULL, message TEXT,
        payment_method VARCHAR(30) NOT NULL DEFAULT 'direct_mutual', payment_terms VARCHAR(500),
        delivery_option VARCHAR(30) NOT NULL DEFAULT 'buyer_pickup', delivery_notes VARCHAR(500), last_action_by INT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY(listing_id) REFERENCES crop_listings(id) ON DELETE CASCADE,
        FOREIGN KEY(buyer_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(seller_id) REFERENCES users(id) ON DELETE CASCADE,
        INDEX idx_offer_users(buyer_id,seller_id,status)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS marketplace_messages(
        id INT AUTO_INCREMENT PRIMARY KEY, offer_id INT NOT NULL, sender_id INT NOT NULL,
        message TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(offer_id) REFERENCES marketplace_offers(id) ON DELETE CASCADE,
        FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,
        INDEX idx_market_messages(offer_id,id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS chat_conversations(
        id INT AUTO_INCREMENT PRIMARY KEY, listing_id INT NOT NULL, buyer_id INT NOT NULL, seller_id INT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uq_listing_buyer (listing_id,buyer_id),
        FOREIGN KEY(listing_id) REFERENCES crop_listings(id) ON DELETE CASCADE,
        FOREIGN KEY(buyer_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(seller_id) REFERENCES users(id) ON DELETE CASCADE,
        INDEX idx_chat_participants (buyer_id,seller_id,updated_at)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS chat_messages(
        id BIGINT AUTO_INCREMENT PRIMARY KEY, conversation_id INT NOT NULL, sender_id INT NOT NULL,
        message TEXT NOT NULL, is_read TINYINT(1) NOT NULL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE,
        FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,
        INDEX idx_chat_message_history (conversation_id,id), INDEX idx_chat_unread (conversation_id,is_read)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS chat_notifications(
        id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, conversation_id INT NOT NULL,
        message_id BIGINT NOT NULL, title VARCHAR(160) NOT NULL, body VARCHAR(255) NOT NULL,
        is_read TINYINT(1) NOT NULL DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE,
        FOREIGN KEY(message_id) REFERENCES chat_messages(id) ON DELETE CASCADE,
        INDEX idx_chat_notifications_user (user_id,is_read,created_at)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS marketplace_orders(
        id INT AUTO_INCREMENT PRIMARY KEY, offer_id INT NOT NULL UNIQUE,
        listing_id INT NOT NULL, buyer_id INT NOT NULL, seller_id INT NOT NULL,
        quantity_quintals DECIMAL(12,2) NOT NULL, agreed_price DECIMAL(12,2) NOT NULL,
        payment_method VARCHAR(30) NOT NULL DEFAULT 'direct_mutual', payment_terms VARCHAR(500),
        delivery_option VARCHAR(30) NOT NULL DEFAULT 'buyer_pickup', delivery_notes VARCHAR(500),
        status VARCHAR(30) NOT NULL DEFAULT 'confirmed', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(offer_id) REFERENCES marketplace_offers(id),
        FOREIGN KEY(listing_id) REFERENCES crop_listings(id),
        FOREIGN KEY(buyer_id) REFERENCES users(id), FOREIGN KEY(seller_id) REFERENCES users(id)
    )""")
    # Backward-compatible marketplace migrations for existing installations.
    cur.execute("SHOW COLUMNS FROM marketplace_offers"); offer_cols={r[0] for r in cur.fetchall()}
    for col,ddl in [("payment_method","VARCHAR(30) NOT NULL DEFAULT 'direct_mutual'"),("payment_terms","VARCHAR(500) NULL"),("delivery_option","VARCHAR(30) NOT NULL DEFAULT 'buyer_pickup'"),("delivery_notes","VARCHAR(500) NULL"),("last_action_by","INT NULL")]:
        if col not in offer_cols: cur.execute(f"ALTER TABLE marketplace_offers ADD COLUMN {col} {ddl}")
    cur.execute("SHOW COLUMNS FROM marketplace_orders"); order_cols={r[0] for r in cur.fetchall()}
    for col,ddl in [("payment_method","VARCHAR(30) NOT NULL DEFAULT 'direct_mutual'"),("payment_terms","VARCHAR(500) NULL"),("delivery_option","VARCHAR(30) NOT NULL DEFAULT 'buyer_pickup'"),("delivery_notes","VARCHAR(500) NULL")]:
        if col not in order_cols: cur.execute(f"ALTER TABLE marketplace_orders ADD COLUMN {col} {ddl}")
    c.commit(); cur.close(); c.close()

@app.on_event("startup")
def startup():
    try: init_db()
    except Exception as e: print(f"Database initialization warning: {e}")
class RegisterRequest(BaseModel): full_name:str; email:EmailStr; password:str; role:Literal['farmer','buyer']='farmer'
class LoginRequest(BaseModel): email:EmailStr; password:str

def token_for(user_id): return jwt.encode({"sub":str(user_id),"exp":datetime.now(timezone.utc)+timedelta(minutes=TOKEN_MINUTES)},SECRET_KEY,algorithm=ALGORITHM)
def current_payload(token:str=Depends(oauth2_scheme)):
    try: return jwt.decode(token,SECRET_KEY,algorithms=[ALGORITHM])
    except Exception: raise HTTPException(401,"Login expired or invalid. Please log in again.")
def current_user_id(payload=Depends(current_payload)):
    try: return int(payload["sub"])
    except Exception: raise HTTPException(401,"Invalid login token")
class ChatConnectionManager:
    def __init__(self): self.connections={}
    async def connect(self, user_id:int, websocket:WebSocket):
        await websocket.accept(); self.connections.setdefault(user_id,set()).add(websocket)
    def disconnect(self, user_id:int, websocket:WebSocket):
        self.connections.get(user_id,set()).discard(websocket)
        if not self.connections.get(user_id): self.connections.pop(user_id,None)
    async def send_user(self, user_id:int, payload:dict):
        dead=[]
        for ws in list(self.connections.get(user_id,set())):
            try: await ws.send_json(payload)
            except Exception: dead.append(ws)
        for ws in dead: self.disconnect(user_id,ws)

chat_manager=ChatConnectionManager()

def websocket_user(token:str):
    try:
        payload=jwt.decode(token,SECRET_KEY,algorithms=[ALGORITHM]); return int(payload['sub'])
    except Exception: return None

def admin_required(uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor(); cur.execute("SELECT role FROM users WHERE id=%s",(uid,)); r=cur.fetchone(); cur.close(); c.close()
    if not r or r[0]!="admin": raise HTTPException(403,"Admin access required")
    return uid

def role_required(*allowed_roles):
    def dependency(uid:int=Depends(current_user_id)):
        c=db(); cur=c.cursor(); cur.execute("SELECT role FROM users WHERE id=%s",(uid,)); row=cur.fetchone(); cur.close(); c.close()
        if not row or row[0] not in allowed_roles:
            raise HTTPException(403, "This feature is not available for your account role.")
        return uid
    return dependency

@app.post("/api/auth/register")
def register(data:RegisterRequest):
    name=data.full_name.strip(); email=str(data.email).lower()
    if not name: raise HTTPException(400,"Name is required")
    if len(data.password)<8: raise HTTPException(400,"Password must contain at least 8 characters")
    c=db(); cur=c.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE email=%s",(email,))
        if cur.fetchone(): raise HTTPException(409,"Email is already registered")
        role="admin" if os.getenv("ADMIN_EMAIL","").lower()==email and os.getenv("ADMIN_EMAIL") else data.role
        cur.execute("INSERT INTO users(full_name,email,password_hash,role) VALUES(%s,%s,%s,%s)",(name,email,password_hash.hash(data.password),role)); uid=cur.lastrowid; c.commit()
    finally: cur.close(); c.close()
    return {
    "access_token": token_for(uid),
    "token_type": "bearer",
    "user": {
        "id": uid,
        "full_name": name,
        "email": email,
        "role": role
    }
}

@app.post("/api/auth/login")
def login(data:LoginRequest):
    c=db(); cur=c.cursor(dictionary=True); cur.execute("SELECT id,password_hash,full_name,email,role FROM users WHERE email=%s",(str(data.email).lower(),)); u=cur.fetchone(); cur.close(); c.close()
    if not u or not password_hash.verify(data.password,u["password_hash"]): raise HTTPException(401,"Incorrect email or password")
    return {"access_token":token_for(u["id"]),"token_type":"bearer","user":{"id":u["id"],"full_name":u["full_name"],"email":u["email"],"role":u["role"]}}

@app.get("/api/auth/me")
def me(uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor(dictionary=True); cur.execute("SELECT id,full_name,email,role,created_at FROM users WHERE id=%s",(uid,)); u=cur.fetchone(); cur.close(); c.close()
    if not u: raise HTTPException(401,"User not found")
    if u.get("created_at"): u["created_at"]=u["created_at"].isoformat()
    return u


def _ai_provider():
    """Kisan Mitra uses Groq for all generative AI features."""
    return "groq"


def _groq_client():
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key or key.startswith("YOUR_"):
        raise HTTPException(503, "Groq API key is missing. Add GROQ_API_KEY to the project .env file.")
    return OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1", timeout=90.0, max_retries=1)


def _groq_model(task="CHAT"):
    if task == "CROP":
        return (os.getenv("GROQ_VISION_MODEL") or "qwen/qwen3.8-27b").strip()
    return (os.getenv("GROQ_CHAT_MODEL") or os.getenv("GROQ_MODEL") or "openai/gpt-oss-120b").strip()


def _groq_json_completion(prompt, image_data_uri=None, task="CROP"):
    """Request JSON from Groq; optionally include a plant image for vision analysis."""
    client = _groq_client()
    user_content = prompt
    if image_data_uri:
        user_content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data_uri}},
        ]
    response = client.chat.completions.create(
        model=_groq_model(task),
        messages=[
            {"role": "system", "content": "Return only valid JSON matching the user's requested schema. Do not wrap it in Markdown."},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_completion_tokens=1200,
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)

def analyze_with_groq(path:Path):
    try:
        prompt = (
            "You are an agricultural crop-health assistant. Analyze this image. "
            "Never invent a diagnosis if unclear. If it is not a plant image, set "
            "is_plant_image false and explain in warning. Confidence is an uncalibrated "
            "AI assessment score, not a scientific probability. Give cautious general "
            "advice, no exact pesticide dosage, and recommend local agricultural extension "
            "confirmation for serious cases. Return concise JSON. "
            "Required JSON keys: is_plant_image (boolean), crop (string), disease (string), "
            "confidence (number 0-100), severity (string), symptoms (array of strings), "
            "treatment (array of strings), prevention (array of strings), warning (string)."
        )
        original_bytes = path.read_bytes()
        analysis_bytes = original_bytes
        try:
            with Image.open(BytesIO(original_bytes)) as source_image:
                image = ImageOps.exif_transpose(source_image).convert("RGB")
                image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                buffer = BytesIO()
                image.save(buffer, format="JPEG", quality=84, optimize=True)
                compressed = buffer.getvalue()
                if len(compressed) < len(original_bytes):
                    analysis_bytes = compressed
        except Exception:
            pass
        mime_type = "image/jpeg" if analysis_bytes != original_bytes else {
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp'
        }[path.suffix.lower()]
        image_data_uri = "data:" + mime_type + ";base64," + base64.b64encode(analysis_bytes).decode("ascii")
        result = _groq_json_completion(prompt, image_data_uri=image_data_uri, task="CROP")
        if not result.get("is_plant_image"):
            raise HTTPException(400, result.get("warning") or "Please upload a clear plant image")
        result["confidence"] = max(0, min(100, float(result.get("confidence", 0))))
        for key in ("symptoms", "treatment", "prevention"):
            if not isinstance(result.get(key), list):
                result[key] = []
        for key in ("crop", "disease", "severity", "warning"):
            if not isinstance(result.get(key), str):
                result[key] = str(result.get(key) or "")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        print("Groq crop analysis error:", repr(exc))
        raise HTTPException(502, "Crop analysis failed. Check your Groq API key, vision model access, internet connection, and try again.")

@app.post("/api/crop/analyze")
async def analyze(image:UploadFile=File(...),uid:int=Depends(current_user_id)):
    ext=Path(image.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT: raise HTTPException(400,"Use JPG, JPEG, PNG, or WebP image format")
    if image.content_type not in {"image/jpeg","image/png","image/webp"}: raise HTTPException(400,"Unsupported image content type")
    content=await image.read()
    if not content: raise HTTPException(400,"The selected image is empty")
    if len(content)>MAX_IMAGE_BYTES: raise HTTPException(413,"Image is too large. Maximum size is 8 MB")
    path=UPLOAD_DIR/f"{uuid.uuid4().hex}{ext}"; path.write_bytes(content)
    try: p=analyze_with_groq(path)
    except Exception:
        path.unlink(missing_ok=True); raise
    recommendation="\n".join(p["treatment"])
    c=db(); cur=c.cursor()
    cur.execute("""INSERT INTO crop_reports(user_id,crop,disease,confidence,severity,symptoms,treatment,prevention,warning,recommendation,image_path) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(uid,p["crop"],p["disease"],p["confidence"],p["severity"],json.dumps(p["symptoms"]),json.dumps(p["treatment"]),json.dumps(p["prevention"]),p["warning"],recommendation,str(path)))
    rid=cur.lastrowid; c.commit(); cur.close(); c.close()
    return {"report_id":rid,**p}

def parse_report(r):
    for k in ("symptoms","treatment","prevention"):
        if isinstance(r.get(k),str):
            try:r[k]=json.loads(r[k])
            except Exception:r[k]=[]
        if r.get(k) is None:r[k]=[]
    if r.get("created_at"):r["created_at"]=r["created_at"].isoformat()
    return r

@app.get("/api/reports")
def reports(uid:int=Depends(current_user_id),limit:int=Query(100,ge=1,le=100)):
    c=db(); cur=c.cursor(dictionary=True); cur.execute("SELECT id,crop,disease,confidence,severity,created_at FROM crop_reports WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",(uid,limit)); rows=cur.fetchall(); cur.close(); c.close()
    for r in rows:
        if r.get("created_at"):r["created_at"]=r["created_at"].isoformat()
    return rows

@app.get("/api/reports/{rid}")
def report_detail(rid:int,uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor(dictionary=True); cur.execute("SELECT * FROM crop_reports WHERE id=%s AND user_id=%s",(rid,uid)); r=cur.fetchone(); cur.close(); c.close()
    if not r: raise HTTPException(404,"Report not found")
    return parse_report(r)

@app.get("/api/reports/{rid}/image")
def report_image(rid:int,uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor(); cur.execute("SELECT image_path FROM crop_reports WHERE id=%s AND user_id=%s",(rid,uid)); r=cur.fetchone(); cur.close(); c.close()
    if not r or not r[0] or not Path(r[0]).exists(): raise HTTPException(404,"Image not found")
    return FileResponse(r[0])

def _pdf_font_name(language_code):
    font_files = {
        "en": "NotoSans-Regular.ttf", "hi": "NotoSansDevanagari-Regular.ttf", "ha": "NotoSansDevanagari-Regular.ttf",
        "pa": "NotoSansGurmukhi-Regular.ttf", "gu": "NotoSansGujarati-Regular.ttf", "mr": "NotoSansDevanagari-Regular.ttf",
        "bn": "NotoSansBengali-Regular.ttf", "as": "NotoSansBengali-Regular.ttf", "ur": "NotoSansArabic-Regular.ttf",
        "ta": "NotoSansTamil-Regular.ttf", "te": "NotoSansTelugu-Regular.ttf", "kn": "NotoSansKannada-Regular.ttf",
        "ml": "NotoSansMalayalam-Regular.ttf", "or": "NotoSansOriya-Regular.ttf"
    }
    font_path = ROOT / "backend" / "fonts" / font_files.get(language_code, "NotoSans-Regular.ttf")
    if font_path.exists():
        try:
            font_name = f"KMReportFont_{language_code}"
            if font_name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(font_name, str(font_path), shapable=True))
                pdfmetrics.registerFontFamily(font_name, normal=font_name, bold=font_name, italic=font_name, boldItalic=font_name)
            return font_name
        except Exception as exc:
            print("PDF font setup warning:", repr(exc))
    return "Helvetica"


def create_pdf(report, out, language="en"):
    # Translate all user-facing report content and labels, not IDs, dates, or numeric scores.
    labels = [
        "Kisan Mitra — Crop Doctor Report", "Report ID", "Date", "Crop", "Possible condition",
        "AI assessment (not a calibrated probability)", "Severity", "Not identified", "Visible symptoms",
        "Suggested treatment / care", "Prevention", "No specific advice available.", "Important",
        "This is an AI-assisted image assessment, not a laboratory diagnosis. Image-only identification can be wrong. Confirm serious cases with a local agricultural expert. Follow locally approved product labels; no pesticide dosage is prescribed here."
    ]
    field_keys = ["crop", "disease", "severity", "warning"]
    field_texts = [str(report.get(k) or "") for k in field_keys]
    list_keys = ["symptoms", "treatment", "prevention"]
    list_texts = []
    for key in list_keys:
        values = report.get(key) or []
        list_texts.extend([str(x) for x in values] or [""])
    all_texts = labels + field_texts + list_texts
    translated = translate_texts(all_texts, language)
    translated_labels = translated[:len(labels)]
    cursor = len(labels)
    translated_fields = translated[cursor:cursor+len(field_keys)]
    cursor += len(field_keys)
    report_copy = dict(report)
    for key, value in zip(field_keys, translated_fields):
        report_copy[key] = value
    for key in list_keys:
        original_values = report.get(key) or []
        if original_values:
            report_copy[key] = translated[cursor:cursor+len(original_values)]
            cursor += len(original_values)
        else:
            cursor += 1
            report_copy[key] = []

    font_name = _pdf_font_name(language)
    styles = getSampleStyleSheet()
    for style_name in ("Title", "Heading1", "Heading2", "BodyText"):
        styles[style_name].fontName = font_name
    L = translated_labels
    story = [Paragraph(escape(L[0]), styles["Title"]), Spacer(1, 12),
            Paragraph(f"<b>{escape(L[1])}:</b> KM-{report['id']:06d}", styles["BodyText"]),
            Paragraph(f"<b>{escape(L[2])}:</b> {escape(str(report['created_at']))}", styles["BodyText"]), Spacer(1, 12)]
    if report.get("image_path") and Path(report["image_path"]).exists():
        try: story.extend([PDFImage(report["image_path"], width=230, height=170, kind="proportional"), Spacer(1, 12)])
        except Exception: pass
    for label, key, translated_label in [("Crop", "crop", L[3]), ("Possible condition", "disease", L[4]),
                                        ("AI assessment", "confidence", L[5]), ("Severity", "severity", L[6])]:
        if key == "confidence": value = f"{report['confidence']}%"
        else: value = str(report_copy.get(key) or L[7])
        story.extend([Paragraph(f"<b>{escape(translated_label)}:</b> {escape(value)}", styles["BodyText"]), Spacer(1, 5)])
    for title_idx, key in [(8, "symptoms"), (9, "treatment"), (10, "prevention")]:
        story.extend([Spacer(1, 8), Paragraph(escape(L[title_idx]), styles["Heading2"])])
        items = report_copy.get(key) or [L[11]]
        story.append(ListFlowable([ListItem(Paragraph(escape(str(x)), styles["BodyText"])) for x in items], bulletType="bullet"))
    warning = report_copy.get("warning") or L[11]
    story.extend([Spacer(1, 12), Paragraph(f"<b>{escape(L[12])}:</b> {escape(warning)}", styles["BodyText"]),
                Spacer(1, 8), Paragraph(escape(L[13]), styles["BodyText"])])
    SimpleDocTemplate(str(out), pagesize=A4).build(story)

@app.get("/api/reports/{rid}/pdf")
def report_pdf(rid: int, language: str = Query("en"), uid: int = Depends(current_user_id)):
    if language not in SUPPORTED_LANGUAGES:
        language = "en"
    c = db(); cur = c.cursor(dictionary=True)
    cur.execute("SELECT * FROM crop_reports WHERE id=%s AND user_id=%s", (rid, uid))
    r = cur.fetchone(); cur.close(); c.close()
    if not r: raise HTTPException(404, "Report not found")
    parse_report(r)
    out = REPORT_DIR / f"report_{rid}_{uid}_{language}_v3.pdf"
    if not out.exists():
        create_pdf(r, out, language)
    return FileResponse(out, media_type="application/pdf", filename=f"kisan_mitra_report_{rid}_{language}.pdf")

@app.get("/api/weather")
def weather(lat:float=Query(...,ge=-90,le=90),lon:float=Query(...,ge=-180,le=180)):
    try:
        r=requests.get("https://api.open-meteo.com/v1/forecast",params={"latitude":lat,"longitude":lon,"current":"temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,rain,weather_code,wind_speed_10m","hourly":"temperature_2m,precipitation_probability","daily":"weather_code,temperature_2m_max,temperature_2m_min,sunrise,sunset,precipitation_probability_max,wind_speed_10m_max","forecast_days":7,"timezone":"auto"},timeout=15); r.raise_for_status(); w=r.json()
        try:
            g=requests.get("https://nominatim.openstreetmap.org/reverse",params={"lat":lat,"lon":lon,"format":"jsonv2"},headers={"User-Agent":"KisanMitra/1.0 (weather and agriculture dashboard)"},timeout=10); g.raise_for_status(); a=g.json().get("address",{}); place={"city":a.get("city") or a.get("town") or a.get("village") or a.get("county"),"district":a.get("state_district") or a.get("county"),"state":a.get("state"),"country":a.get("country")}
        except Exception: place={"city":None,"district":None,"state":None,"country":None}
        return {"location":place,"weather":w,"updated_at":datetime.now(timezone.utc).isoformat()}
    except Exception as e: print("Weather API error",repr(e)); raise HTTPException(502,"Weather service is temporarily unavailable")

@app.get("/api/mandi")
def mandi(
    lat: float | None = None,
    lon: float | None = None,
    state: str | None = None,
    district: str | None = None,
    commodity: str | None = None
):
    """
    Load mandi prices from the local MySQL mandi_prices table.

    State, district and commodity can be selected from the frontend.
    lat/lon are retained for backwards compatibility.
    """

    # Automatically detect state/district only when they weren't selected
    # in the frontend.
    if lat is not None and lon is not None and (not state or not district):
        try:
            g = requests.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={
                    "lat": lat,
                    "lon": lon,
                    "format": "jsonv2"
                },
                headers={
                    "User-Agent": "KisanMitra/1.0 (agriculture dashboard)"
                },
                timeout=10
            )

            g.raise_for_status()

            address = g.json().get("address", {})

            state = state or address.get("state")

            district = (
                district
                or address.get("state_district")
                or address.get("county")
            )

        except Exception as e:
            print("Mandi location lookup warning:", repr(e))

    state = state.strip() if state else None
    district = district.strip() if district else None
    commodity = commodity.strip() if commodity else None

    if not state or not district:
        raise HTTPException(
            400,
            "Please select both state and district"
        )

    connection = None
    cursor = None

    try:
        connection = db()
        cursor = connection.cursor(dictionary=True)

        query = """
            SELECT
                state,
                district,
                market,
                commodity,
                variety,
                grade,
                arrival_date,
                min_price,
                max_price,
                modal_price
            FROM mandi_prices
            WHERE LOWER(TRIM(state)) = LOWER(TRIM(%s))
            AND LOWER(TRIM(district)) = LOWER(TRIM(%s))
        """

        params = [state, district]

        if commodity:
            query += """
                AND LOWER(TRIM(commodity)) =
                    LOWER(TRIM(%s))
            """
            params.append(commodity)

        query += """
            ORDER BY arrival_date DESC, market ASC
            LIMIT 100
        """

        print("Mandi database filters:", {
            "state": state,
            "district": district,
            "commodity": commodity
        })

        cursor.execute(query, tuple(params))

        rows = cursor.fetchall()

        records = []

        for row in rows:

            arrival_date = row.get("arrival_date")

            if arrival_date:
                arrival_date = arrival_date.isoformat()

            # Return BOTH database-style names and the old
            # AGMARKNET/frontend-style names.
            record = {
                # New SQL names
                "state": row.get("state"),
                "district": row.get("district"),
                "market": row.get("market"),
                "commodity": row.get("commodity"),
                "variety": row.get("variety"),
                "grade": row.get("grade"),
                "arrival_date": arrival_date,
                "min_price": row.get("min_price"),
                "max_price": row.get("max_price"),
                "modal_price": row.get("modal_price"),

                # Frontend / AGMARKNET-compatible names
                "State": row.get("state"),
                "District": row.get("district"),
                "Market": row.get("market"),
                "Commodity": row.get("commodity"),
                "Variety": row.get("variety"),
                "Grade": row.get("grade"),
                "Arrival_Date": arrival_date,
                "Min_Price": row.get("min_price"),
                "Max_Price": row.get("max_price"),
                "Modal_Price": row.get("modal_price"),
            }

            records.append(record)

        return {
            "records": records,
            "total": len(records),

            "location": {
                "state": state,
                "district": district
            },

            "source": "Local official mandi CSV imported into MySQL",

            "note": (
                "Prices are wholesale market observations from "
                "the imported official dataset. Check arrival date, "
                "quality, transport cost and current market conditions "
                "before deciding where to sell."
            )
        }

    except mysql.connector.Error as e:

        print("Mandi database error:", repr(e))

        raise HTTPException(
            500,
            "Unable to load mandi prices from the local database."
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


@app.get("/api/admin/summary")
def admin_summary(uid:int=Depends(admin_required)):
    c=db(); cur=c.cursor(dictionary=True); cur.execute("SELECT COUNT(*) AS users FROM users"); users=cur.fetchone()["users"]; cur.execute("SELECT COUNT(*) AS reports FROM crop_reports"); reports_count=cur.fetchone()["reports"]; cur.execute("SELECT id,full_name,email,role,created_at FROM users ORDER BY created_at DESC LIMIT 100"); rows=cur.fetchall(); cur.close(); c.close()
    for x in rows:
        if x.get("created_at"):x["created_at"]=x["created_at"].isoformat()
    return {"users_count":users,"reports_count":reports_count,"users":rows}


SUPPORTED_LANGUAGES = {
    "en":"English", "hi":"हिन्दी", "pa":"ਪੰਜਾਬੀ", "ha":"हरियाणवी",
    "gu":"ગુજરાતી", "mr":"मराठी", "bn":"বাংলা", "ur":"اردو",
    "ta":"தமிழ்", "te":"తెలుగు", "kn":"ಕನ್ನಡ", "ml":"മലയാളം",
    "or":"ଓଡ଼ିଆ", "as":"অসমীয়া"
}
LANGUAGE_NAMES = ", ".join(SUPPORTED_LANGUAGES.values())

class ChatRequest(BaseModel):
    message: str
    language: str = "en"
    crop: str | None = None
    location: str | None = None

class PreferencesRequest(BaseModel):
    language: str = "en"
    email_address: EmailStr | None = None
    email_enabled: bool = False
    weather_alerts: bool = True
    crop_reminders: bool = True
    notification_consent: bool = False
    latitude: float | None = None
    longitude: float | None = None

class CalendarEventRequest(BaseModel):
    title: str
    description: str | None = None
    event_type: str = "other"
    event_date: date
    reminder_days_before: int = 1

def _pref_row(uid):
    c=db(); cur=c.cursor(dictionary=True)
    cur.execute("SELECT * FROM user_preferences WHERE user_id=%s",(uid,))
    p=cur.fetchone()
    if not p:
        cur.execute("SELECT email FROM users WHERE id=%s",(uid,))
        u=cur.fetchone() or {}
        cur.execute("INSERT INTO user_preferences(user_id,email_address) VALUES(%s,%s)",(uid,u.get("email")))
        c.commit()
        cur.execute("SELECT * FROM user_preferences WHERE user_id=%s",(uid,))
        p=cur.fetchone()
    cur.close(); c.close()
    if p:
        for k in ("email_enabled","weather_alerts","crop_reminders","notification_consent"):
            p[k]=bool(p[k])
        if p.get("updated_at"): p["updated_at"]=p["updated_at"].isoformat()
        if p.get("latitude") is not None: p["latitude"]=float(p["latitude"])
        if p.get("longitude") is not None: p["longitude"]=float(p["longitude"])
        # Return only supported preference fields; extra legacy database columns are ignored.
        allowed = {"user_id", "language", "email_address", "email_enabled", "weather_alerts", "crop_reminders", "notification_consent", "latitude", "longitude", "updated_at"}
        p = {key: value for key, value in p.items() if key in allowed}
    return p

@app.get("/api/languages")
def languages():
    return [{"code":k,"name":v} for k,v in SUPPORTED_LANGUAGES.items()]


class TranslateRequest(BaseModel):
    language: str = "en"
    texts: list[str]

# Persistent translation cache: avoids paying latency (and free-tier quota) for repeated strings.
_TRANSLATION_CACHE_PATH = ROOT / "backend" / "translation_cache.json"
_translation_cache = {}
_translation_cache_lock = threading.RLock()
_TRANSLATION_CACHE_LIMIT = 6000

def _load_translation_cache():
    try:
        if _TRANSLATION_CACHE_PATH.exists():
            raw = json.loads(_TRANSLATION_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for lang, entries in raw.items():
                    if lang in SUPPORTED_LANGUAGES and isinstance(entries, dict):
                        for source, translated in entries.items():
                            if isinstance(source, str) and isinstance(translated, str):
                                _translation_cache[(lang, source)] = translated
    except Exception as exc:
        print("Translation cache load warning:", repr(exc))

def _save_translation_cache():
    try:
        with _translation_cache_lock:
            # Keep newest entries and prevent an unbounded cache file.
            while len(_translation_cache) > _TRANSLATION_CACHE_LIMIT:
                _translation_cache.pop(next(iter(_translation_cache)))
            grouped = {}
            for (lang, source), translated in _translation_cache.items():
                grouped.setdefault(lang, {})[source] = translated
            tmp = _TRANSLATION_CACHE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(grouped, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, _TRANSLATION_CACHE_PATH)
    except Exception as exc:
        print("Translation cache save warning:", repr(exc))

_load_translation_cache()

def _libretranslate_one(text, language_code):
    """Use an optional self-hosted LibreTranslate endpoint; never require a paid hosted API."""
    endpoint = os.getenv("LIBRETRANSLATE_URL", "").strip()
    if not endpoint:
        return None
    allowed = {x.strip() for x in os.getenv("LIBRETRANSLATE_LANGUAGES", "hi,bn,ur,ar").split(",") if x.strip()}
    if language_code not in allowed:
        return None
    try:
        response = requests.post(endpoint, json={"q": text, "source": "auto", "target": language_code, "format": "text"}, timeout=3.5)
        response.raise_for_status()
        translated = response.json().get("translatedText")
        if isinstance(translated, str) and translated.strip():
            return translated.strip()
    except Exception as exc:
        print("LibreTranslate fallback warning:", repr(exc))
    return None

def translate_texts(texts, language_code):
    """Cache-first translation using an optional self-hosted LibreTranslate service.

    No Gemini or other generative-AI provider is called for translations. If a translation
    is not cached and LibreTranslate is not configured or cannot translate the language,
    the original text is returned unchanged.
    """
    source = [str(value) for value in texts]
    if language_code not in SUPPORTED_LANGUAGES or not source or language_code == "en":
        return source

    output = list(source)
    missing_indices, missing_texts = [], []
    with _translation_cache_lock:
        for i, value in enumerate(source):
            cached = _translation_cache.get((language_code, value))
            if cached is not None:
                output[i] = cached
            else:
                missing_indices.append(i)
                missing_texts.append(value)
    if not missing_texts:
        return output

    # Optional locally hosted LibreTranslate. It is free to self-host, but only supports
    # language pairs for which models are installed. Unsupported text stays unchanged.
    libre_results = [None] * len(missing_texts)
    if os.getenv("LIBRETRANSLATE_URL", "").strip():
        with ThreadPoolExecutor(max_workers=min(4, len(missing_texts))) as pool:
            futures = [pool.submit(_libretranslate_one, value, language_code) for value in missing_texts]
            for idx, future in enumerate(futures):
                try:
                    libre_results[idx] = future.result()
                except Exception:
                    libre_results[idx] = None

    # Keep untranslated items as-is when LibreTranslate cannot handle the language.
    # This project intentionally does not call Gemini or any other AI provider here.

    if any(_translation_cache.get((language_code, source[i])) is not None for i in range(len(source))):
        _save_translation_cache()
    return output

@app.post("/api/translate")
def translate_batch(data: TranslateRequest):
    if data.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(400, "Unsupported language.")
    if not data.texts or len(data.texts) > 60:
        raise HTTPException(400, "Send between 1 and 60 text items per translation request.")
    if any(len(str(x)) > 8000 for x in data.texts):
        raise HTTPException(413, "Each translation text must be 8,000 characters or fewer.")
    if sum(len(str(x)) for x in data.texts) > 12000:
        raise HTTPException(413, "Translation request is too large.")
    translations = translate_texts(data.texts, data.language)
    return {"language": data.language, "translations": translations, "translated": data.language == "en" or translations != [str(x) for x in data.texts]}

@app.post("/api/chat")
def crop_chat(data: ChatRequest, uid:int=Depends(current_user_id)):
    message = data.message.strip()
    if not message:
        raise HTTPException(400, "Please enter a question.")
    if len(message) > 3000:
        raise HTTPException(413, "Message is too long (maximum 3000 characters).")
    lang = SUPPORTED_LANGUAGES.get(data.language, "English")
    context = []
    if data.crop: context.append("Farmer's crop: " + data.crop[:100])
    if data.location: context.append("Farmer's location: " + data.location[:160])
    context_text = "\n".join(context) or "No crop or location context was supplied."
    prompt = f"""You are Kisan Mitra, a cautious agricultural support assistant for farmers.
Answer in {lang}. The farmer may ask in any language; respond in {lang}.
Context: {context_text}
Use clear practical wording. Do not claim certainty from incomplete information.
Do not invent live weather, prices, or forecasts. For current weather, direct the farmer to the app's live weather panel.
For pesticide or fertilizer questions, do not invent product dosages; follow locally approved product labels and consult an agricultural extension officer for serious cases.
Keep the answer helpful and concise.
Farmer question: {message}"""
    try:
        response = _groq_client().chat.completions.create(
            model=_groq_model("CHAT"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.25,
            max_completion_tokens=700,
        )
        answer = (response.choices[0].message.content or "").strip()
        if not answer:
            raise ValueError("Empty answer")
        return {"answer": answer, "language": data.language}
    except HTTPException:
        raise
    except Exception as exc:
        print("Groq chat error:", repr(exc))
        raise HTTPException(502, "The AI assistant is temporarily unavailable. Check your Groq API key and model access, then try again.")

@app.post("/api/chat/stream")
def crop_chat_stream(data: ChatRequest, uid: int = Depends(current_user_id)):
    """Stream chatbot responses from Groq."""
    message = data.message.strip()
    if not message:
        raise HTTPException(400, "Please enter a question.")
    if len(message) > 3000:
        raise HTTPException(413, "Message is too long (maximum 3000 characters).")
    lang = SUPPORTED_LANGUAGES.get(data.language, "English")
    context = []
    if data.crop: context.append("Farmer's crop: " + data.crop[:100])
    if data.location: context.append("Farmer's location: " + data.location[:160])
    context_text = "\n".join(context) or "No crop or location context was supplied."
    prompt = f"""You are Kisan Mitra, a cautious agricultural support assistant for farmers.
Answer in {lang}. The farmer may ask in any language; respond directly in {lang}.
Context: {context_text}
Use clear practical wording and keep the answer concise. Do not claim certainty from incomplete information.
Do not invent live weather, prices, or forecasts. For current conditions, direct the farmer to the app's live weather panel.
For pesticide or fertilizer questions, do not invent product dosages; follow locally approved product labels and consult an agricultural extension officer for serious cases.
Farmer question: {message}"""
    def generate():
        try:
            stream = _groq_client().chat.completions.create(
                model=_groq_model("CHAT"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.25,
                max_completion_tokens=700,
                stream=True,
            )
            for chunk in stream:
                choices = getattr(chunk, "choices", None) or []
                if choices:
                    piece = getattr(getattr(choices[0], "delta", None), "content", None)
                    if piece:
                        yield piece
        except Exception as exc:
            print("Groq streaming chat error:", repr(exc))
            yield "\n\n" + _translate_notification("The response was interrupted. Please try again.", data.language)
    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get("/api/preferences")
def get_preferences(uid:int=Depends(current_user_id)):
    return _pref_row(uid)

@app.put("/api/preferences")
def save_preferences(data: PreferencesRequest, uid: int = Depends(current_user_id)):
    if data.language not in SUPPORTED_LANGUAGES:
        raise HTTPException(400, "Unsupported language.")
    if data.email_enabled and not data.notification_consent:
        raise HTTPException(400, "Please confirm consent before enabling email notifications.")
    if data.email_enabled and not data.email_address:
        raise HTTPException(400, "Enter an email address or switch email notifications off.")
    if (data.latitude is None) != (data.longitude is None):
        raise HTTPException(400, "Latitude and longitude must be provided together.")
    c = db(); cur = c.cursor()
    cur.execute("""INSERT INTO user_preferences
        (user_id,language,email_address,email_enabled,weather_alerts,crop_reminders,notification_consent,latitude,longitude)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE language=VALUES(language),email_address=VALUES(email_address),
        email_enabled=VALUES(email_enabled),weather_alerts=VALUES(weather_alerts),
        crop_reminders=VALUES(crop_reminders),notification_consent=VALUES(notification_consent),
        latitude=VALUES(latitude),longitude=VALUES(longitude)""",
        (uid, data.language, str(data.email_address) if data.email_address else None, int(data.email_enabled),
        int(data.weather_alerts), int(data.crop_reminders), int(data.notification_consent), data.latitude, data.longitude))
    c.commit(); cur.close(); c.close()
    return _pref_row(uid)

@app.get("/api/calendar")
def list_calendar(uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor(dictionary=True)
    cur.execute("SELECT id,title,description,event_type,event_date,reminder_days_before,created_at FROM farm_calendar_events WHERE user_id=%s ORDER BY event_date ASC LIMIT 250",(uid,))
    rows=cur.fetchall(); cur.close(); c.close()
    for r in rows:
        if r.get("event_date"): r["event_date"]=r["event_date"].isoformat()
        if r.get("created_at"): r["created_at"]=r["created_at"].isoformat()
    return rows

@app.post("/api/calendar")
def create_calendar_event(data: CalendarEventRequest, uid:int=Depends(current_user_id)):
    title=data.title.strip()
    if not title: raise HTTPException(400,"Event title is required.")
    if len(title)>160: raise HTTPException(400,"Event title must be 160 characters or fewer.")
    if data.event_type not in {"sowing","irrigation","fertilizer","spraying","harvest","inspection","other"}:
        raise HTTPException(400,"Choose a valid event type.")
    if data.reminder_days_before not in range(0,31): raise HTTPException(400,"Reminder lead time must be between 0 and 30 days.")
    c=db(); cur=c.cursor()
    cur.execute("INSERT INTO farm_calendar_events(user_id,title,description,event_type,event_date,reminder_days_before) VALUES(%s,%s,%s,%s,%s,%s)",
        (uid,title,(data.description or "").strip() or None,data.event_type,data.event_date,data.reminder_days_before))
    eid=cur.lastrowid; c.commit(); cur.close(); c.close()
    return {"id":eid,"title":title,"event_date":data.event_date.isoformat(),"event_type":data.event_type}

@app.delete("/api/calendar/{event_id}")
def delete_calendar_event(event_id:int, uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor()
    cur.execute("DELETE FROM farm_calendar_events WHERE id=%s AND user_id=%s",(event_id,uid))
    deleted=cur.rowcount; c.commit(); cur.close(); c.close()
    if not deleted: raise HTTPException(404,"Calendar event not found.")
    return {"deleted":True}

def _send_email(to_addr, subject, body):
    host=os.getenv("SMTP_HOST"); user=os.getenv("SMTP_USER"); password=os.getenv("SMTP_PASSWORD")
    sender=os.getenv("SMTP_FROM") or user
    if not all([host,sender,to_addr]): raise RuntimeError("Email is not configured. Set SMTP_HOST, SMTP_FROM and related SMTP settings.")
    msg=EmailMessage(); msg["Subject"]=subject; msg["From"]=sender; msg["To"]=to_addr; msg.set_content(body)
    port=int(os.getenv("SMTP_PORT","587"))
    with smtplib.SMTP(host,port,timeout=20) as server:
        server.starttls()
        if user and password: server.login(user,password)
        server.send_message(msg)

def _deliver_email(uid, prefs, message, kind, fingerprint, event_id=None):
    if not prefs.get("email_enabled") or not prefs.get("email_address"):
        return
    c = db(); cur = c.cursor()
    cur.execute("SELECT id FROM notification_logs WHERE user_id=%s AND fingerprint=%s AND channel='email' AND status='sent' LIMIT 1", (uid, fingerprint))
    already = cur.fetchone(); cur.close(); c.close()
    if already: return
    status = "sent"; detail = "Submitted to email provider"
    try:
        _send_email(prefs["email_address"], "Kisan Mitra farm alert", message)
    except Exception as exc:
        status = "failed"; detail = str(exc)[:490]
    c = db(); cur = c.cursor()
    cur.execute("INSERT INTO notification_logs(user_id,event_id,channel,notification_type,fingerprint,status,detail) VALUES(%s,%s,'email',%s,%s,%s,%s)",
                (uid, event_id, kind, fingerprint, status, detail))
    c.commit(); cur.close(); c.close()

def _translate_notification(message, language_code):
    """Reuse the shared cached translation pipeline for email notifications."""
    if language_code == "en":
        return message
    return translate_texts([message], language_code)[0]

def run_scheduled_notifications():
    """Send due calendar reminders and forecast-risk alerts; provider delivery requires configuration."""
    try:
        c=db(); cur=c.cursor(dictionary=True)
        cur.execute("""SELECT e.*,p.language,p.email_address,p.email_enabled,
            p.weather_alerts,p.crop_reminders,p.notification_consent,p.latitude,p.longitude
            FROM farm_calendar_events e JOIN user_preferences p ON p.user_id=e.user_id
            WHERE e.event_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 30 DAY)""")
        events=cur.fetchall()
        cur.execute("""SELECT p.*,u.id AS owner_id FROM user_preferences p JOIN users u ON u.id=p.user_id
            WHERE p.notification_consent=1 AND p.weather_alerts=1 AND p.latitude IS NOT NULL AND p.longitude IS NOT NULL""")
        farmers=cur.fetchall()
        cur.close(); c.close()
        for e in events:
            if not e.get("crop_reminders") or not e.get("notification_consent"): continue
            due_date=e["event_date"]-timedelta(days=int(e.get("reminder_days_before") or 0))
            if due_date != date.today(): continue
            lang=SUPPORTED_LANGUAGES.get(e.get("language"),"English")
            msg=_translate_notification(f"Kisan Mitra reminder: {e['title']} is scheduled for {e['event_date'].isoformat()}. {e.get('description') or ''}".strip(),e.get("language") or "en")
            fp=f"calendar:{e['id']}:{date.today().isoformat()}"
            _deliver_email(e["user_id"], e, msg, "calendar", fp, e["id"])
        for p in farmers:
            try:
                r=requests.get("https://api.open-meteo.com/v1/forecast",params={"latitude":float(p["latitude"]),"longitude":float(p["longitude"]),
                    "daily":"temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max","forecast_days":3,"timezone":"auto"},timeout=12)
                r.raise_for_status(); daily=r.json().get("daily",{})
                risks=[]
                for i,daystr in enumerate(daily.get("time",[])):
                    rain=(daily.get("precipitation_probability_max") or [0]*len(daily.get("time",[])))[i] or 0
                    hi=(daily.get("temperature_2m_max") or [0]*len(daily.get("time",[])))[i] or 0
                    lo=(daily.get("temperature_2m_min") or [99]*len(daily.get("time",[])))[i] or 99
                    wind=(daily.get("wind_speed_10m_max") or [0]*len(daily.get("time",[])))[i] or 0
                    if rain>=70: risks.append((daystr,"heavy-rain",f"rain probability {rain}%"))
                    if hi>=40: risks.append((daystr,"heat",f"maximum temperature {hi}°C"))
                    if lo<=5: risks.append((daystr,"cold",f"minimum temperature {lo}°C"))
                    if wind>=45: risks.append((daystr,"wind",f"maximum wind {wind} km/h"))
                for daystr,risk,details in risks:
                    fp=f"weather:{daystr}:{risk}"
                    msg=_translate_notification(f"Kisan Mitra weather alert for {daystr}: {risk.replace('-', ' ').title()} risk ({details}). Check local conditions before irrigation, spraying or harvesting. This is a forecast-based alert, not a guarantee.",p.get("language") or "en")
                    _deliver_email(p["owner_id"], p, msg, "weather", fp, None)
            except Exception as e:
                print("Scheduled weather alert warning:",repr(e))
    except Exception as e:
        print("Scheduled notifications warning:",repr(e))

scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
@app.on_event("startup")
def start_notification_scheduler():
    try:
        if not scheduler.running:
            scheduler.add_job(run_scheduled_notifications,"interval",minutes=30,id="kisan_mitra_notifications",replace_existing=True,max_instances=1,coalesce=True)
            scheduler.start()
    except Exception as e: print("Notification scheduler warning:",repr(e))

@app.post("/api/notifications/test")
def test_notifications(uid: int = Depends(current_user_id)):
    prefs = _pref_row(uid)
    if not prefs.get("notification_consent"):
        raise HTTPException(400, "Enable email notification consent in your preferences first.")
    if not prefs.get("email_enabled") or not prefs.get("email_address"):
        raise HTTPException(400, "Enable email notifications and provide an email address first.")
    message = _translate_notification("Kisan Mitra test notification. Your email notification channel is configured for this account.", prefs.get("language") or "en")
    try:
        _send_email(prefs["email_address"], "Kisan Mitra test notification", message)
        return {"results": {"email": "submitted"}, "note": "Submitted means the email provider accepted the request; check the recipient inbox and spam folder."}
    except Exception as exc:
        print("Email notification test failed:", repr(exc))
        raise HTTPException(502, "Email is not configured or the provider rejected the message. Check SMTP settings.")


@app.get("/health")
def health():
    provider = _ai_provider()
    configured = bool(os.getenv("GROQ_API_KEY", "").strip())
    return {"status":"ok", "ai_provider":provider, "ai":"configured" if configured else f"{provider.title()} API key missing", "mandi":"configured" if os.getenv("DATA_GOV_API_KEY") and os.getenv("DATA_GOV_RESOURCE_ID") else "not configured"}


# ---------------- REAL DATA + MARKETPLACE ----------------
DATA_GOV_BASE = "https://api.data.gov.in/resource/"
DEFAULT_MANDI_RESOURCE = "9ef84268-d588-465a-a308-a864a43d0070"

def _data_gov_fetch(filters=None, limit=100, offset=0):
    api_key=os.getenv("DATA_GOV_API_KEY","").strip()
    resource=os.getenv("DATA_GOV_RESOURCE_ID","").strip() or DEFAULT_MANDI_RESOURCE
    if not api_key or api_key.startswith("YOUR_"):
        raise HTTPException(503,"Configure DATA_GOV_API_KEY in backend .env first.")
    params={"api-key":api_key,"format":"json","limit":min(max(int(limit),1),1000),"offset":max(int(offset),0),"sort[Arrival_Date]":"desc"}
    for k,v in (filters or {}).items():
        if v: params[f"filters[{k}]"]=v
    try:
        r=requests.get(DATA_GOV_BASE+resource,params=params,headers={"User-Agent":"KisanMitra/1.0","Accept":"application/json"},timeout=25)
        if not r.ok:
            # Keep the API key out of logs and error messages. Return only upstream
            # status and a short response body so configuration issues are diagnosable.
            detail=(r.text or "").strip().replace("\n", " ")[:400]
            print(f"data.gov.in mandi API error: HTTP {r.status_code}; response={detail}")
            raise HTTPException(
                status_code=502,
                detail=f"Government mandi API returned HTTP {r.status_code}. Check DATA_GOV_API_KEY, DATA_GOV_RESOURCE_ID and request filters. Upstream: {detail or 'No response body'}"
            )
        payload=r.json()
        if not isinstance(payload,dict) or "records" not in payload:
            raise ValueError("Unexpected data.gov.in response: missing records field")
        return payload
    except HTTPException:
        raise
    except requests.RequestException as e:
        print(f"data.gov.in mandi network error: {type(e).__name__}: {str(e)[:250]}")
        raise HTTPException(502,"Could not reach data.gov.in. Check internet connectivity, proxy/firewall and try again.")
    except ValueError as e:
        raise HTTPException(502,f"The configured resource did not return valid mandi JSON. Verify DATA_GOV_RESOURCE_ID. {str(e)[:200]}")

def _normalise_mandi(row):
    def val(*keys):
        for k in keys:
            if row.get(k) not in (None,""): return row.get(k)
        return None
    d=val("arrival_date","Arrival_Date","date")
    parsed=None
    if d:
        for fmt in ("%d/%m/%Y","%Y-%m-%d","%d-%m-%Y"):
            try: parsed=datetime.strptime(str(d),fmt).date(); break
            except ValueError: pass
    def num(x):
        try: return float(str(x).replace(',','')) if x not in (None,"") else None
        except Exception: return None
    return {"state":val("state","State"),"district":val("district","District"),"market":val("market","Market"),"commodity":val("commodity","Commodity"),"variety":val("variety","Variety"),"grade":val("grade","Grade"),"arrival_date":parsed,"min_price":num(val("min_price","Min_Price","Min_x0020_Price")),"max_price":num(val("max_price","Max_Price","Max_x0020_Price")),"modal_price":num(val("modal_price","Modal_Price","Modal_x0020_Price"))}

def _cache_mandi_rows(rows):
    c=db(); cur=c.cursor(); saved=0
    try:
        for raw in rows:
            x=_normalise_mandi(raw)
            if not all(x[k] for k in ("state","district","market","commodity")): continue
            cur.execute("SELECT id FROM mandi_prices WHERE state=%s AND district=%s AND market=%s AND commodity=%s AND arrival_date <=> %s AND variety <=> %s LIMIT 1",(x['state'],x['district'],x['market'],x['commodity'],x['arrival_date'],x['variety']))
            old=cur.fetchone()
            if old:
                cur.execute("UPDATE mandi_prices SET min_price=%s,max_price=%s,modal_price=%s,grade=%s WHERE id=%s",(x['min_price'],x['max_price'],x['modal_price'],x['grade'],old[0]))
            else:
                cur.execute("INSERT INTO mandi_prices(state,district,market,commodity,variety,grade,arrival_date,min_price,max_price,modal_price) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",tuple(x[k] for k in ("state","district","market","commodity","variety","grade","arrival_date","min_price","max_price","modal_price")))
            saved+=1
        c.commit()
    finally: cur.close(); c.close()
    return saved

@app.get("/api/mandi/locations")
def mandi_locations(state:str=Query(...,min_length=1)):
    """Load districts for the selected state from the configured government dataset."""
    payload=_data_gov_fetch({"state.keyword":state.strip()},1000,0)
    rows=payload.get("records",[])
    if not isinstance(rows,list):
        raise HTTPException(502,"The government mandi API returned an invalid locations list.")
    districts=sorted({
        str(row.get("district") or row.get("District")).strip()
        for row in rows
        if isinstance(row,dict) and (row.get("district") or row.get("District"))
    },key=str.casefold)
    return {"state":state.strip(),"districts":districts,"count":len(districts),"source":"data.gov.in / AGMARKNET"}

@app.get("/api/mandi/live")
def mandi_live(state:str|None=None,district:str|None=None,commodity:str|None=None,market:str|None=None,limit:int=Query(100,ge=1,le=1000),offset:int=Query(0,ge=0)):
    """Fetch current published daily mandi observations from data.gov.in/AGMARKNET.
    Results are also cached in MySQL so analytics can use a historical series.
    """
    filters={"state.keyword":state,"district":district,"commodity":commodity,"market":market}
    warning=None
    records=[]
    payload={}
    try:
        payload=_data_gov_fetch(filters,min(limit,100),offset)
        raw_rows=payload.get("records",[])
        records=[_normalise_mandi(x) for x in raw_rows]
        try:
            saved=_cache_mandi_rows(raw_rows)
        except Exception as e:
            print("Mandi cache warning:",repr(e)); saved=0
        for x in records:
            if x["arrival_date"]: x["arrival_date"]=x["arrival_date"].isoformat()
        if records:
            return {
                "records":records,
                "total":payload.get("total",len(records)),
                "count":len(records),
                "cached":saved,
                "source":"data.gov.in / AGMARKNET",
                "granularity":"Daily",
                "fetched_at":datetime.now(timezone.utc).isoformat(),
                "note":"These are the latest daily observations published by the source, not tick-by-tick live auction prices. Check arrival date before making a selling decision."
            }
        warning="The live government API returned no records for these filters; showing saved prices from the local database instead."
    except HTTPException as e:
        print("Live mandi fetch failed, using database fallback:",e.detail)
        warning="Live government mandi API is unavailable ("+str(e.detail)[:160]+"); showing saved prices from the local database instead."
    # Fallback: previously imported / cached prices in MySQL
    fb=mandi(state=state,district=district,commodity=commodity)
    fb["source"]="Local database (saved from earlier AGMARKNET data)"
    fb["warning"]=warning
    fb["note"]=warning+" Check each arrival date; saved prices may be old."
    return fb

@app.get("/api/mandi/analytics")
def mandi_analytics(state:str|None=None,district:str|None=None,commodity:str|None=None,days:int=Query(30,ge=7,le=365)):
    # Refresh a small filtered live sample before reading historical cached data.
    refresh_error = None
    refreshed_at = None
    try:
        live_payload = _data_gov_fetch({"state.keyword":state,"district":district,"commodity":commodity},100,0)
        _cache_mandi_rows(live_payload.get("records",[]))
        refreshed_at = datetime.now(timezone.utc).isoformat()
    except HTTPException as exc:
        refresh_error = exc.detail
    c=db(); cur=c.cursor(dictionary=True)
    try:
        where=["arrival_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)"]; args=[days]
        for col,val in (("state",state),("district",district),("commodity",commodity)):
            if val: where.append(f"LOWER({col})=LOWER(%s)"); args.append(val)
        w=" AND ".join(where)
        cur.execute(f"SELECT arrival_date,AVG(modal_price) avg_modal,MIN(min_price) min_price,MAX(max_price) max_price,SUM(modal_price IS NOT NULL) records FROM mandi_prices WHERE {w} GROUP BY arrival_date ORDER BY arrival_date",tuple(args))
        trend=cur.fetchall()
        for r in trend: r["arrival_date"]=r["arrival_date"].isoformat() if r["arrival_date"] else None
        cur.execute(f"SELECT market,AVG(modal_price) avg_modal,MIN(min_price) min_price,MAX(max_price) max_price,MAX(arrival_date) latest_date FROM mandi_prices WHERE {w} GROUP BY market ORDER BY avg_modal DESC LIMIT 20",tuple(args))
        markets=cur.fetchall()
        for r in markets: r["latest_date"]=r["latest_date"].isoformat() if r["latest_date"] else None
        return {
            "trend":trend,
            "markets":markets,
            "days":days,
            "source":"data.gov.in / AGMARKNET",
            "refreshed_at":refreshed_at,
            "refresh_error":refresh_error,
            "note":"Daily published observations, not tick-by-tick prices. Gaps mean no record was published for that date."
        }
    finally: cur.close(); c.close()

class MarketplaceProfile(BaseModel):
    account_type:str="both"; phone:str|None=None; state:str; district:str; latitude:float|None=None; longitude:float|None=None
class ListingCreate(BaseModel):
    commodity:str; variety:str|None=None; quality_grade:str|None=None; quantity_quintals:float; asking_price:float
    state:str; district:str; pickup_location:str|None=None; description:str|None=None
class OfferCreate(BaseModel):
    quantity_quintals:float; offered_price:float; message:str|None=None
    payment_method:str="direct_mutual"; payment_terms:str|None=None
    delivery_option:str="buyer_pickup"; delivery_notes:str|None=None
class MessageCreate(BaseModel): message:str
class OfferDecision(BaseModel):
    status:str; offered_price:float|None=None; quantity_quintals:float|None=None; message:str|None=None
    payment_method:str|None=None; payment_terms:str|None=None
    delivery_option:str|None=None; delivery_notes:str|None=None

@app.put("/api/marketplace/profile")
def save_market_profile(data:MarketplaceProfile,uid:int=Depends(current_user_id)):
    if data.account_type not in ("buyer","seller","both"): raise HTTPException(400,"Account type must be buyer, seller or both.")
    if data.latitude is not None and not -90<=data.latitude<=90: raise HTTPException(400,"Invalid latitude")
    if data.longitude is not None and not -180<=data.longitude<=180: raise HTTPException(400,"Invalid longitude")
    c=db(); cur=c.cursor()
    cur.execute("INSERT INTO marketplace_profiles(user_id,account_type,phone,state,district,latitude,longitude) VALUES(%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE account_type=VALUES(account_type),phone=VALUES(phone),state=VALUES(state),district=VALUES(district),latitude=VALUES(latitude),longitude=VALUES(longitude)",(uid,data.account_type,data.phone,data.state,data.district,data.latitude,data.longitude)); c.commit(); cur.close(); c.close()
    return {"ok":True,"account_type":data.account_type}

@app.get("/api/marketplace/profile")
def get_market_profile(uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor(dictionary=True); cur.execute("SELECT account_type,phone,state,district,latitude,longitude FROM marketplace_profiles WHERE user_id=%s",(uid,)); row=cur.fetchone(); cur.close(); c.close(); return row or {}

@app.post("/api/marketplace/listings")
def create_listing(data:ListingCreate,uid:int=Depends(role_required("farmer","admin"))):
    if not data.commodity.strip() or data.quantity_quintals<=0 or data.asking_price<=0: raise HTTPException(400,"Commodity, positive quantity and positive price are required.")
    c=db(); cur=c.cursor(); cur.execute("INSERT INTO crop_listings(seller_id,commodity,variety,quality_grade,quantity_quintals,available_quintals,asking_price,state,district,pickup_location,description) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(uid,data.commodity.strip(),data.variety,data.quality_grade,data.quantity_quintals,data.quantity_quintals,data.asking_price,data.state,data.district,data.pickup_location,data.description)); lid=cur.lastrowid; c.commit(); cur.close(); c.close(); return {"id":lid,"status":"active"}

@app.get("/api/marketplace/listings")
def list_listings(commodity:str|None=None,state:str|None=None,district:str|None=None,min_qty:float|None=None,max_price:float|None=None,uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor(dictionary=True)
    q="SELECT l.*,u.full_name seller_name FROM crop_listings l JOIN users u ON u.id=l.seller_id WHERE l.status='active' AND l.available_quintals>0"; a=[]
    for col,v in (("l.commodity",commodity),("l.state",state),("l.district",district)):
        if v: q+=f" AND LOWER({col}) LIKE LOWER(%s)"; a.append('%'+v+'%')
    if min_qty is not None: q+=" AND l.available_quintals >= %s"; a.append(min_qty)
    if max_price is not None: q+=" AND l.asking_price <= %s"; a.append(max_price)
    q+=" ORDER BY l.created_at DESC LIMIT 200"; cur.execute(q,tuple(a)); rows=cur.fetchall(); cur.close(); c.close(); return {"listings":rows}

@app.get("/api/marketplace/my-listings")
def my_listings(uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor(dictionary=True); cur.execute("SELECT * FROM crop_listings WHERE seller_id=%s ORDER BY created_at DESC",(uid,)); rows=cur.fetchall(); cur.close(); c.close(); return {"listings":rows}

class DirectChatMessage(BaseModel): message:str

@app.post("/api/marketplace/listings/{listing_id}/chat")
async def start_listing_chat(listing_id:int, uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor(dictionary=True)
    cur.execute("SELECT l.id,l.seller_id,l.commodity,l.variety,l.state,l.district,l.status,u.full_name seller_name FROM crop_listings l JOIN users u ON u.id=l.seller_id WHERE l.id=%s",(listing_id,)); listing=cur.fetchone()
    if not listing: cur.close(); c.close(); raise HTTPException(404,"Crop listing not found")
    if listing['seller_id']==uid: cur.close(); c.close(); raise HTTPException(400,"You cannot start a chat with yourself.")
    cur.execute("SELECT role FROM users WHERE id=%s",(uid,)); role_row=cur.fetchone()
    if not role_row or role_row['role'] not in ('buyer','admin'): cur.close(); c.close(); raise HTTPException(403,"Only buyers can start a chat from a crop listing.")
    if listing['status'] not in ('active','sold'): cur.close(); c.close(); raise HTTPException(409,"This listing is no longer available for chat.")
    cur.execute("INSERT INTO chat_conversations(listing_id,buyer_id,seller_id) VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE updated_at=CURRENT_TIMESTAMP",(listing_id,uid,listing['seller_id']))
    cur.execute("SELECT id FROM chat_conversations WHERE listing_id=%s AND buyer_id=%s",(listing_id,uid)); row=cur.fetchone(); conversation_id=row['id']
    cur.execute("SELECT id FROM chat_messages WHERE conversation_id=%s LIMIT 1",(conversation_id,))
    if not cur.fetchone():
        greeting=f"Hello! I’m interested in your {listing['commodity']} listing. Is it available?"
        cur.execute("INSERT INTO chat_messages(conversation_id,sender_id,message) VALUES(%s,%s,%s)",(conversation_id,uid,greeting)); mid=cur.lastrowid
        cur.execute("SELECT full_name FROM users WHERE id=%s",(uid,)); buyer_name=cur.fetchone()['full_name']
        cur.execute("INSERT INTO chat_notifications(user_id,conversation_id,message_id,title,body) VALUES(%s,%s,%s,%s,%s)",(listing['seller_id'],conversation_id,mid,f"New chat from {buyer_name}",greeting))
        c.commit()
        await chat_manager.send_user(listing['seller_id'],{"type":"new_message","conversation_id":conversation_id,"message":{"id":mid,"sender_id":uid,"sender_name":buyer_name,"message":greeting,"created_at":datetime.now(timezone.utc).isoformat()}})
    else: c.commit()
    cur.close(); c.close()
    return {"conversation_id":conversation_id,"listing":listing}

@app.get("/api/marketplace/chats")
def list_direct_chats(uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor(dictionary=True)
    cur.execute("""SELECT cc.id conversation_id,cc.listing_id,cc.updated_at,l.commodity,l.variety,l.state,l.district,
        CASE WHEN cc.buyer_id=%s THEN cc.seller_id ELSE cc.buyer_id END other_user_id,
        CASE WHEN cc.buyer_id=%s THEN seller.full_name ELSE buyer.full_name END other_name,
        (SELECT message FROM chat_messages WHERE conversation_id=cc.id ORDER BY id DESC LIMIT 1) last_message,
        (SELECT created_at FROM chat_messages WHERE conversation_id=cc.id ORDER BY id DESC LIMIT 1) last_message_at,
        (SELECT COUNT(*) FROM chat_messages WHERE conversation_id=cc.id AND sender_id<>%s AND is_read=0) unread_count
        FROM chat_conversations cc JOIN crop_listings l ON l.id=cc.listing_id
        JOIN users buyer ON buyer.id=cc.buyer_id JOIN users seller ON seller.id=cc.seller_id
        WHERE cc.buyer_id=%s OR cc.seller_id=%s ORDER BY cc.updated_at DESC""",(uid,uid,uid,uid,uid)); rows=cur.fetchall(); cur.close(); c.close()
    for r in rows:
        for k,v in list(r.items()):
            if hasattr(v,'isoformat'): r[k]=v.isoformat()
    return {"conversations":rows}

@app.get("/api/marketplace/chats/{conversation_id}/messages")
def direct_chat_history(conversation_id:int,uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor(dictionary=True)
    cur.execute("SELECT id FROM chat_conversations WHERE id=%s AND (buyer_id=%s OR seller_id=%s)",(conversation_id,uid,uid))
    if not cur.fetchone(): cur.close(); c.close(); raise HTTPException(404,"Conversation not found")
    cur.execute("UPDATE chat_messages SET is_read=1 WHERE conversation_id=%s AND sender_id<>%s",(conversation_id,uid))
    cur.execute("UPDATE chat_notifications SET is_read=1 WHERE conversation_id=%s AND user_id=%s AND is_read=0",(conversation_id,uid))
    cur.execute("SELECT m.id,m.sender_id,m.message,m.is_read,m.created_at,u.full_name sender_name FROM chat_messages m JOIN users u ON u.id=m.sender_id WHERE m.conversation_id=%s ORDER BY m.id",(conversation_id,)); rows=cur.fetchall(); c.commit(); cur.close(); c.close()
    for r in rows:
        if r.get('created_at'): r['created_at']=r['created_at'].isoformat()
    return {"messages":rows}

@app.post("/api/marketplace/chats/{conversation_id}/messages")
async def send_direct_chat_message(conversation_id:int,data:DirectChatMessage,uid:int=Depends(current_user_id)):
    message=data.message.strip()
    if not message: raise HTTPException(400,"Message cannot be empty.")
    if len(message)>5000: raise HTTPException(400,"Message is too long (maximum 5000 characters).")
    c=db(); cur=c.cursor(dictionary=True)
    cur.execute("SELECT cc.*,CASE WHEN cc.buyer_id=%s THEN cc.seller_id ELSE cc.buyer_id END receiver_id FROM chat_conversations cc WHERE cc.id=%s AND (cc.buyer_id=%s OR cc.seller_id=%s)",(uid,conversation_id,uid,uid)); convo=cur.fetchone()
    if not convo: cur.close(); c.close(); raise HTTPException(404,"Conversation not found")
    cur.execute("INSERT INTO chat_messages(conversation_id,sender_id,message) VALUES(%s,%s,%s)",(conversation_id,uid,message)); mid=cur.lastrowid
    cur.execute("UPDATE chat_conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=%s",(conversation_id,))
    cur.execute("SELECT full_name FROM users WHERE id=%s",(uid,)); sender=cur.fetchone()['full_name']
    cur.execute("INSERT INTO chat_notifications(user_id,conversation_id,message_id,title,body) VALUES(%s,%s,%s,%s,%s)",(convo['receiver_id'],conversation_id,mid,f"New message from {sender}",message[:240]))
    c.commit(); cur.close(); c.close()
    payload={"type":"new_message","conversation_id":conversation_id,"message":{"id":mid,"sender_id":uid,"sender_name":sender,"message":message,"created_at":datetime.now(timezone.utc).isoformat()}}
    await chat_manager.send_user(convo['receiver_id'],payload)
    await chat_manager.send_user(uid,payload)
    return {"id":mid,"sent":True}

@app.get("/api/marketplace/chat-notifications")
def get_chat_notifications(uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor(dictionary=True)
    cur.execute("SELECT id,conversation_id,title,body,is_read,created_at FROM chat_notifications WHERE user_id=%s ORDER BY id DESC LIMIT 30",(uid,)); rows=cur.fetchall()
    cur.execute("SELECT COUNT(*) unread FROM chat_notifications WHERE user_id=%s AND is_read=0",(uid,)); unread=cur.fetchone()['unread']
    cur.close(); c.close()
    for r in rows:
        if r.get('created_at'): r['created_at']=r['created_at'].isoformat()
    return {"notifications":rows,"unread_count":unread}

@app.post("/api/marketplace/chat-notifications/read")
def mark_chat_notifications_read(uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor(); cur.execute("UPDATE chat_notifications SET is_read=1 WHERE user_id=%s AND is_read=0",(uid,)); changed=cur.rowcount; c.commit(); cur.close(); c.close(); return {"ok":True,"updated":changed}

@app.websocket("/ws/marketplace-chat")
async def marketplace_chat_socket(websocket:WebSocket, token:str=Query(...)):
    uid=websocket_user(token)
    if not uid:
        await websocket.close(code=1008); return
    await chat_manager.connect(uid,websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: chat_manager.disconnect(uid,websocket)
    except Exception: chat_manager.disconnect(uid,websocket)

@app.post("/api/marketplace/listings/{listing_id}/offers")
def make_offer(listing_id:int,data:OfferCreate,uid:int=Depends(role_required("buyer","admin"))):
    if data.quantity_quintals<=0 or data.offered_price<=0: raise HTTPException(400,"Enter a positive quantity and price.")
    if data.payment_method not in ("direct_mutual","direct_cash","direct_bank_upi"): raise HTTPException(400,"Choose a supported direct payment arrangement.")
    if data.delivery_option not in ("buyer_pickup","seller_delivery"): raise HTTPException(400,"Choose buyer pickup or seller-arranged delivery.")
    c=db(); cur=c.cursor(dictionary=True); cur.execute("SELECT * FROM crop_listings WHERE id=%s AND status='active'",(listing_id,)); l=cur.fetchone()
    if not l: cur.close(); c.close(); raise HTTPException(404,"Listing not found")
    if l['seller_id']==uid: cur.close(); c.close(); raise HTTPException(400,"You cannot make an offer on your own listing.")
    if data.quantity_quintals>float(l['available_quintals']): cur.close(); c.close(); raise HTTPException(400,"Requested quantity exceeds available quantity.")
    cur.execute("INSERT INTO marketplace_offers(listing_id,buyer_id,seller_id,quantity_quintals,offered_price,message) VALUES(%s,%s,%s,%s,%s,%s)",(listing_id,uid,l['seller_id'],data.quantity_quintals,data.offered_price,data.message)); oid=cur.lastrowid
    # Persist the buyer's proposed terms with the offer; they become order terms only on acceptance.
    cur.execute("UPDATE marketplace_offers SET payment_method=%s,payment_terms=%s,delivery_option=%s,delivery_notes=%s,last_action_by=%s WHERE id=%s",(data.payment_method,data.payment_terms,data.delivery_option,data.delivery_notes,uid,oid))
    if data.message: cur.execute("INSERT INTO marketplace_messages(offer_id,sender_id,message) VALUES(%s,%s,%s)",(oid,uid,data.message))
    c.commit(); cur.close(); c.close(); return {"offer_id":oid,"status":"pending"}

@app.get("/api/marketplace/offers")
def my_offers(uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor(dictionary=True); cur.execute("SELECT o.*,l.commodity,l.variety,l.state,l.district,l.asking_price,u.full_name buyer_name FROM marketplace_offers o JOIN crop_listings l ON l.id=o.listing_id JOIN users u ON u.id=o.buyer_id WHERE o.buyer_id=%s OR o.seller_id=%s ORDER BY o.updated_at DESC",(uid,uid)); rows=cur.fetchall(); cur.close(); c.close(); return {"offers":rows}

@app.patch("/api/marketplace/offers/{offer_id}")
def update_offer(offer_id:int,data:OfferDecision,uid:int=Depends(current_user_id)):
    if data.status not in ("accepted","rejected","countered","cancelled"): raise HTTPException(400,"Invalid offer action")
    c=db(); cur=c.cursor(dictionary=True); cur.execute("SELECT * FROM marketplace_offers WHERE id=%s AND (buyer_id=%s OR seller_id=%s) FOR UPDATE",(offer_id,uid,uid)); o=cur.fetchone()
    if not o: c.rollback(); cur.close(); c.close(); raise HTTPException(404,"Offer not found")
    if data.status=="accepted" and (o.get('last_action_by') or o['buyer_id'])==uid: c.rollback(); cur.close(); c.close(); raise HTTPException(403,"The other party must accept your latest offer or counteroffer.")
    if data.status=="countered":
        if (o.get('last_action_by') or o['buyer_id'])==uid: c.rollback(); cur.close(); c.close(); raise HTTPException(403,"Wait for the other party to respond before sending another counteroffer.")
        if data.offered_price is None or data.quantity_quintals is None or data.offered_price<=0 or data.quantity_quintals<=0: c.rollback(); cur.close(); c.close(); raise HTTPException(400,"A counteroffer needs a positive price and quantity.")
        cur.execute("UPDATE marketplace_offers SET status='pending',offered_price=%s,quantity_quintals=%s,payment_method=COALESCE(%s,payment_method),payment_terms=COALESCE(%s,payment_terms),delivery_option=COALESCE(%s,delivery_option),delivery_notes=COALESCE(%s,delivery_notes),last_action_by=%s WHERE id=%s",(data.offered_price,data.quantity_quintals,data.payment_method,data.payment_terms,data.delivery_option,data.delivery_notes,uid,offer_id))
    else: cur.execute("UPDATE marketplace_offers SET status=%s WHERE id=%s",(data.status,offer_id))
    msg=data.message or ("Offer "+data.status)
    if data.status=="accepted":
        cur.execute("SELECT available_quintals FROM crop_listings WHERE id=%s FOR UPDATE",(o['listing_id'],)); available=float(cur.fetchone()['available_quintals'])
        if float(o['quantity_quintals'])>available: c.rollback(); cur.close(); c.close(); raise HTTPException(409,"Not enough quantity remains. Please negotiate a new quantity.")
        payment_method=data.payment_method or o.get('payment_method') or 'direct_mutual'
        delivery_option=data.delivery_option or o.get('delivery_option') or 'buyer_pickup'
        if payment_method not in ("direct_mutual","direct_cash","direct_bank_upi") or delivery_option not in ("buyer_pickup","seller_delivery"):
            c.rollback(); cur.close(); c.close(); raise HTTPException(400,"Invalid payment or delivery arrangement.")
        cur.execute("INSERT INTO marketplace_orders(offer_id,listing_id,buyer_id,seller_id,quantity_quintals,agreed_price,payment_method,payment_terms,delivery_option,delivery_notes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(offer_id,o['listing_id'],o['buyer_id'],o['seller_id'],o['quantity_quintals'],o['offered_price'],payment_method,data.payment_terms or o.get('payment_terms'),delivery_option,data.delivery_notes or o.get('delivery_notes')))
        cur.execute("UPDATE crop_listings SET available_quintals=available_quintals-%s, status=IF(available_quintals-%s<=0,'sold','active') WHERE id=%s",(o['quantity_quintals'],o['quantity_quintals'],o['listing_id']))
    cur.execute("INSERT INTO marketplace_messages(offer_id,sender_id,message) VALUES(%s,%s,%s)",(offer_id,uid,msg)); c.commit(); cur.close(); c.close(); return {"ok":True,"status":data.status}

@app.get("/api/marketplace/offers/{offer_id}/messages")
def offer_messages(offer_id:int,uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor(dictionary=True); cur.execute("SELECT id FROM marketplace_offers WHERE id=%s AND (buyer_id=%s OR seller_id=%s)",(offer_id,uid,uid))
    if not cur.fetchone(): cur.close(); c.close(); raise HTTPException(404,"Offer not found")
    cur.execute("SELECT m.id,m.sender_id,m.message,m.created_at,u.full_name sender_name FROM marketplace_messages m JOIN users u ON u.id=m.sender_id WHERE m.offer_id=%s ORDER BY m.id",(offer_id,)); rows=cur.fetchall(); cur.close(); c.close(); return {"messages":rows}

@app.post("/api/marketplace/offers/{offer_id}/messages")
def send_offer_message(offer_id:int,data:MessageCreate,uid:int=Depends(current_user_id)):
    msg=data.message.strip()
    if not msg or len(msg)>2000: raise HTTPException(400,"Message must contain 1–2000 characters.")
    c=db(); cur=c.cursor(); cur.execute("SELECT id FROM marketplace_offers WHERE id=%s AND (buyer_id=%s OR seller_id=%s)",(offer_id,uid,uid))
    if not cur.fetchone(): cur.close(); c.close(); raise HTTPException(404,"Offer not found")
    cur.execute("INSERT INTO marketplace_messages(offer_id,sender_id,message) VALUES(%s,%s,%s)",(offer_id,uid,msg)); c.commit(); mid=cur.lastrowid; cur.close(); c.close(); return {"id":mid,"sent":True}

@app.get("/api/marketplace/orders")
def marketplace_orders(uid:int=Depends(current_user_id)):
    c=db(); cur=c.cursor(dictionary=True); cur.execute("SELECT o.*,l.commodity,l.state,l.district,b.full_name buyer_name,s.full_name seller_name FROM marketplace_orders o JOIN crop_listings l ON l.id=o.listing_id JOIN users b ON b.id=o.buyer_id JOIN users s ON s.id=o.seller_id WHERE o.buyer_id=%s OR o.seller_id=%s ORDER BY o.created_at DESC",(uid,uid)); rows=cur.fetchall(); cur.close(); c.close(); return {"orders":rows}

@app.get("/api/marketplace/recommendations")
def selling_recommendations(commodity:str,quantity:float=Query(...,gt=0),lat:float|None=None,lon:float|None=None,state:str|None=None,district:str|None=None,
    transport_cost_per_quintal:float=Query(0.0,ge=0,le=100000),loading_cost_per_quintal:float=Query(0.0,ge=0,le=100000),
    market_fee_per_quintal:float=Query(0.0,ge=0,le=100000),packaging_cost_per_quintal:float=Query(0.0,ge=0,le=100000),
    other_cost_per_quintal:float=Query(0.0,ge=0,le=100000),production_cost_per_quintal:float=Query(0.0,ge=0,le=100000),uid:int=Depends(current_user_id)):
    # Resolve GPS to administrative location when possible. GPS distance is not fabricated.
    if lat is not None and lon is not None and (not state or not district):
        try:
            geo=requests.get("https://nominatim.openstreetmap.org/reverse",params={"lat":lat,"lon":lon,"format":"jsonv2"},headers={"User-Agent":"KisanMitra/1.0 (market recommendation)"},timeout=10)
            geo.raise_for_status(); addr=geo.json().get("address",{})
            state=state or addr.get("state"); district=district or addr.get("state_district") or addr.get("county")
        except Exception as exc: print("Recommendation reverse-geocode warning:",repr(exc))
    try:
        live_filters={"state":state,"district":district,"commodity":commodity}
        _cache_mandi_rows(_data_gov_fetch(live_filters,1000,0).get("records",[]))
    except HTTPException as exc: print("Recommendation live-data warning:",exc.detail)
    c=db(); cur=c.cursor(dictionary=True)
    q="SELECT market,state,district,AVG(modal_price) modal_price,MAX(arrival_date) latest_date FROM mandi_prices WHERE LOWER(commodity)=LOWER(%s) AND modal_price>0"; a=[commodity]
    if state: q+=" AND LOWER(state)=LOWER(%s)"; a.append(state)
    if district: q+=" AND LOWER(district)=LOWER(%s)"; a.append(district)
    q+=" GROUP BY market,state,district ORDER BY latest_date DESC LIMIT 100"; cur.execute(q,tuple(a)); rows=cur.fetchall(); cur.close(); c.close()
    costs={"transport":transport_cost_per_quintal,"loading_unloading":loading_cost_per_quintal,"market_fees_commission":market_fee_per_quintal,"packaging":packaging_cost_per_quintal,"other":other_cost_per_quintal,"production":production_cost_per_quintal}
    expense_per_q=sum(costs.values()); recs=[]
    for r in rows:
        price=float(r['modal_price']); gross=price*quantity; expenses=expense_per_q*quantity; net=gross-expenses
        recs.append({"market":r['market'],"state":r['state'],"district":r['district'],"modal_price":round(price,2),"estimated_gross_value":round(gross,2),
            "expense_per_quintal":round(expense_per_q,2),"non_transport_expenses_per_quintal":round(expense_per_q-transport_cost_per_quintal,2),"estimated_total_expenses":round(expenses,2),"expense_breakdown":{k:round(v*quantity,2) for k,v in costs.items()},
            "estimated_net_profit":round(net,2),"estimated_net_per_quintal":round(price-expense_per_q,2),"latest_date":r['latest_date'].isoformat() if r['latest_date'] else None,
            "distance_km":None,"recommendation_basis":"Ranked by estimated net profit using the expense amounts entered by the farmer. Mandi-specific distance and transport quotes are not independently verified."})
    recs.sort(key=lambda x:(x['estimated_net_profit'],x['latest_date'] or ''),reverse=True)
    return {"recommendations":recs[:20],"quantity_quintals":quantity,"commodity":commodity,"expenses_per_quintal":costs,
        "note":"Estimated net profit = (latest available modal price − entered expenses per quintal) × quantity. Include every relevant cost; production cost is included if entered. Prices are published mandi observations, not guaranteed offers. Distance is not estimated without verified mandi coordinates."}

@app.post("/api/marketplace/assistant")
def marketplace_assistant(data:ChatRequest,uid:int=Depends(current_user_id)):
    # AI advice is advisory; it cannot send offers or change orders.
    prompt = "You are Kisan Mitra's buyer/seller marketplace helper. Help users understand listings, quantity, price negotiation, quality checks, safe transaction steps and logistics. Never claim to verify a seller, guarantee prices, or execute a transaction. Ask users to confirm every offer themselves. Keep concise. User message: " + data.message[:2500]
    try:
        out = _groq_client().chat.completions.create(
            model=_groq_model("CHAT"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.25,
            max_completion_tokens=600,
        )
        answer = (out.choices[0].message.content or "").strip()
        return {"answer": answer}
    except HTTPException:
        raise
    except Exception as exc:
        print("Marketplace Groq assistant error:", repr(exc))
        raise HTTPException(502, "Marketplace assistant is temporarily unavailable. Check your Groq API key and model access.")
