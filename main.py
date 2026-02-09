#!/usr/bin/env python3
import os
import time
import logging
from threading import Thread
import requests
from flask import Flask
import telebot
from telebot import types
import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv

# تحميل متغيرات البيئة من ملف .env (للتجربة المحلية)
load_dotenv()

# === إعدادات التسجيل ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === سحب الإعدادات من الـ Environment Variables ===
API_TOKEN = os.getenv('API_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
DATABASE_URL = os.getenv('DATABASE_URL')
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL')

# التحقق من وجود الإعدادات الأساسية
if not API_TOKEN or not DATABASE_URL:
    logger.error("❌ خطأ: يجب ضبط API_TOKEN و DATABASE_URL في المتغيرات!")
    exit(1)

# === إعداد خادم الويب (Keep Alive) ===
app = Flask('')

@app.route('/')
def home():
    return "Bot is running and healthy!"

def run_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def self_ping():
    """وظيفة لمنع البوت من النوم على Render"""
    if not RENDER_EXTERNAL_URL:
        logger.warning("⚠️ RENDER_EXTERNAL_URL غير مضبوط، الـ Ping معطل.")
        return
    while True:
        try:
            requests.get(RENDER_EXTERNAL_URL)
            logger.info("📡 Self-Ping: تم إرسال إشارة بنجاح لإبقاء البوت مستيقظاً.")
        except Exception as e:
            logger.error(f"❌ خطأ في الـ Ping: {e}")
        time.sleep(600)  # كل 10 دقائق

# === فئة قاعدة البيانات (Supabase/PostgreSQL) ===
class Database:
    def __init__(self):
        self.connection_pool = None
        self.init_pool()
        self.init_database()

    def init_pool(self):
        # تصحيح رابط postgres ليوافق psycopg2
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        
        try:
            self.connection_pool = psycopg2.pool.SimpleConnectionPool(1, 10, url)
            logger.info("✅ تم إنشاء مجمع الاتصالات بنجاح.")
        except Exception as e:
            logger.error(f"❌ فشل الاتصال بقاعدة البيانات: {e}")
            exit(1)

    def get_conn(self): return self.connection_pool.getconn()
    def put_conn(self, conn): self.connection_pool.putconn(conn)

    def init_database(self):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS subjects (
                        id SERIAL PRIMARY KEY,
                        name TEXT UNIQUE NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS files (
                        id SERIAL PRIMARY KEY,
                        subject_id INTEGER REFERENCES subjects(id) ON DELETE CASCADE,
                        file_id TEXT NOT NULL,
                        file_name TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.commit()
            logger.info("✅ الجداول جاهزة في Supabase.")
        finally: self.put_conn(conn)

    def add_user(self, user_id, username, first_name):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO users (user_id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING", (user_id, username, first_name))
                conn.commit()
        finally: self.put_conn(conn)

    def add_subject(self, name):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO subjects (name) VALUES (%s) ON CONFLICT DO NOTHING", (name,))
                conn.commit()
                return cur.rowcount > 0
        finally: self.put_conn(conn)

    def get_all_subjects(self):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name FROM subjects ORDER BY name")
                return cur.fetchall()
        finally: self.put_conn(conn)

    def add_file(self, subject_id, file_id, file_name):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO files (subject_id, file_id, file_name) VALUES (%s, %s, %s)", (subject_id, file_id, file_name))
                conn.commit()
        finally: self.put_conn(conn)

    def get_subject_files(self, subject_name):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT f.file_id, f.file_name FROM files f JOIN subjects s ON f.subject_id = s.id WHERE s.name = %s", (subject_name,))
                return cur.fetchall()
        finally: self.put_conn(conn)

    def get_subject_by_name(self, name):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name FROM subjects WHERE name = %s", (name,))
                return cur.fetchone()
        finally: self.put_conn(conn)

# === تشغيل البوت ===
db = Database()
bot = telebot.TeleBot(API_TOKEN)
user_states = {}

def is_admin(uid): return uid == ADMIN_ID

def get_user_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    subjects = db.get_all_subjects()
    for _, name in subjects: kb.add(types.KeyboardButton(name))
    kb.add(types.KeyboardButton("🔄 تحديث"), types.KeyboardButton("ℹ️ مساعدة"))
    return kb

def get_admin_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.row("➕ إضافة مادة", "🗑️ حذف مادة")
    kb.row("📁 رفع ملف", "👥 المستخدمين")
    kb.row("📊 إحصائيات", "🏠 الرئيسية")
    return kb

@bot.message_handler(commands=['start'])
def start(message):
    db.add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    if is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "👑 مرحباً بك في لوحة تحكم الآدمن", reply_markup=get_admin_keyboard())
    else:
        bot.send_message(message.chat.id, "📚 اختر مادة لتصفح الملفات:", reply_markup=get_user_keyboard())

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "➕ إضافة مادة")
def add_sub_step1(m):
    user_states[m.from_user.id] = "adding_sub"
    bot.send_message(m.chat.id, "✏️ أرسل اسم المادة الجديدة:", reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and user_states.get(m.from_user.id) == "adding_sub")
def add_sub_step2(m):
    if db.add_subject(m.text.strip()):
        bot.send_message(m.chat.id, f"✅ تم إضافة {m.text}")
    else:
        bot.send_message(m.chat.id, "⚠️ المادة موجودة بالفعل.")
    del user_states[m.from_user.id]
    bot.send_message(m.chat.id, "🏠 العودة للوحة التحكم", reply_markup=get_admin_keyboard())

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📁 رفع ملف")
def upload_step1(m):
    kb = types.InlineKeyboardMarkup()
    for sid, name in db.get_all_subjects():
        kb.add(types.InlineKeyboardButton(name, callback_data=f"up_{sid}"))
    bot.send_message(m.chat.id, "📁 اختر المادة التي تريد رفع الملف إليها:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("up_"))
def upload_step2(call):
    sid = call.data.split("_")[1]
    user_states[call.from_user.id] = f"wait_file_{sid}"
    bot.edit_message_text("📎 أرسل الملف (PDF, صور، إلخ) الآن:", call.message.chat.id, call.message.message_id)

@bot.message_handler(content_types=['document', 'photo'])
def handle_incoming_file(m):
    state = user_states.get(m.from_user.id, "")
    if state.startswith("wait_file_"):
        sid = int(state.split("_")[2])
        fid = m.document.file_id if m.content_type == 'document' else m.photo[-1].file_id
        fname = m.document.file_name if m.content_type == 'document' else "Photo.jpg"
        db.add_file(sid, fid, fname)
        bot.send_message(m.chat.id, f"✅ تم حفظ {fname} بنجاح.", reply_markup=get_admin_keyboard())
        del user_states[m.from_user.id]

@bot.message_handler(func=lambda m: True)
def view_files(m):
    sub = db.get_subject_by_name(m.text)
    if sub:
        files = db.get_subject_files(m.text)
        if not files:
            bot.send_message(m.chat.id, "⚠️ لا توجد ملفات في هذه المادة بعد.")
            return
        bot.send_message(m.chat.id, f"📁 ملفات مادة {m.text}:")
        for fid, fname in files:
            bot.send_document(m.chat.id, fid, caption=f"📄 {fname}")

if __name__ == '__main__':
    # تشغيل خادم الويب والـ Ping في خلفية منفصلة
    Thread(target=run_server, daemon=True).start()
    Thread(target=self_ping, daemon=True).start()
    
    logger.info("🚀 البوت بدأ العمل الآن...")
    bot.infinity_polling()
