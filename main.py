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

# تحميل الإعدادات من ملف .env
load_dotenv()

# === إعداد التسجيل (Logging) ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === الإعدادات من متغيرات البيئة ===
API_TOKEN = os.getenv('API_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
DATABASE_URL = os.getenv('DATABASE_URL')
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL')

# التحقق من المتغيرات الأساسية
if not API_TOKEN or not DATABASE_URL:
    logger.error("❌ خطأ: تأكد من ضبط API_TOKEN و DATABASE_URL في ملف .env")
    exit(1)

# === خادم الويب (Flask) لمنع توقف السيرفر ===
app = Flask('')

@app.route('/')
def home():
    return "Bot is Alive!"

@app.route('/health')
def health():
    return "OK", 200

def run_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def self_ping():
    """وظيفة الـ Ping التلقائي لمنع وضع النوم في Render"""
    if not RENDER_EXTERNAL_URL:
        logger.warning("⚠️ RENDER_EXTERNAL_URL غير معرف. ميزة الـ Ping معطلة.")
        return
    while True:
        try:
            requests.get(RENDER_EXTERNAL_URL, timeout=10)
            logger.info("📡 Ping sent to keep server awake.")
        except Exception as e:
            logger.warning(f"⚠️ Ping failed: {e}")
        time.sleep(300) # كل 5 دقائق

# === إدارة قاعدة البيانات ===
class Database:
    def __init__(self):
        url = DATABASE_URL
        if url and url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        try:
            self.pool = psycopg2.pool.SimpleConnectionPool(1, 15, url)
            self.init_db()
            logger.info("✅ Database connected successfully.")
        except Exception as e:
            logger.error(f"❌ Database connection error: {e}")
            exit(1)

    def get_conn(self): return self.pool.getconn()
    def put_conn(self, conn): self.pool.putconn(conn)

    def init_db(self):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("CREATE TABLE IF NOT EXISTS subjects (id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL);")
                cur.execute("CREATE TABLE IF NOT EXISTS files (id SERIAL PRIMARY KEY, subject_id INTEGER REFERENCES subjects(id) ON DELETE CASCADE, file_id TEXT NOT NULL, file_name TEXT NOT NULL);")
                cur.execute("CREATE TABLE IF NOT EXISTS channels (id SERIAL PRIMARY KEY, channel_id TEXT UNIQUE NOT NULL, channel_link TEXT NOT NULL, channel_name TEXT);")
                cur.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT, joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
                conn.commit()
        finally: self.put_conn(conn)

    # --- حافظنا على الدوال الأصلية كما هي ---
    def get_stats(self):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT (SELECT COUNT(*) FROM users), (SELECT COUNT(*) FROM subjects), (SELECT COUNT(*) FROM files), (SELECT COUNT(*) FROM channels)")
                return cur.fetchone()
        finally: self.put_conn(conn)

    def add_user(self, uid, user, name):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO users (user_id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING", (uid, user, name))
                conn.commit()
        finally: self.put_conn(conn)

    def get_all_subjects(self):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name FROM subjects ORDER BY name")
                return cur.fetchall()
        finally: self.put_conn(conn)

    def get_all_channels(self):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT channel_id, channel_link, channel_name FROM channels")
                return cur.fetchall()
        finally: self.put_conn(conn)

    def add_subject(self, name):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO subjects (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (name,))
                conn.commit()
                return True
        except: return False
        finally: self.put_conn(conn)

    def delete_subject(self, sid):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM subjects WHERE id = %s", (sid,))
                conn.commit()
                return True
        finally: self.put_conn(conn)

# تهيئة الكائنات
db = Database()
bot = telebot.TeleBot(API_TOKEN)
user_states = {}

# === ملاحظة: هنا تضع بقية الكيبوردات والمعالجات (Handlers) الخاصة بك ===
# (لقد تم اختصارها هنا لتركز على هيكل التشغيل، تأكد من وجودها في ملفك)

@bot.message_handler(commands=['start'])
def start_cmd(m):
    db.add_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    bot.send_message(m.chat.id, "أهلاً بك في البوت!", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("🏠 الرئيسية"))

# ... (بقية الـ Handlers للحذف والإضافة والإحصائيات)

# === حل مشكلة Conflict 409 وبدء التشغيل الاستقراي ===
if __name__ == '__main__':
    # تشغيل Flask و الـ Ping في خيوط منفصلة
    Thread(target=run_server, daemon=True).start()
    Thread(target=self_ping, daemon=True).start()

    logger.info("🛠️ جاري تنظيف الاتصالات السابقة لتجنب خطأ 409...")
    
    try:
        # حذف الـ Webhook هو الحل الأهم لخطأ Conflict
        bot.remove_webhook()
        time.sleep(2) # مهلة لضمان استجابة سيرفر تلجرام
        
        logger.info("🚀 تم بدء تشغيل البوت بنجاح...")
        # skip_pending=True يتجاهل الرسائل المتراكمة التي تسبب ضغطاً عند التشغيل
        bot.infinity_polling(skip_pending=True, timeout=60, long_polling_timeout=20)
        
    except Exception as e:
        logger.error(f"⚠️ حدث خطأ في التشغيل: {e}")
        time.sleep(10) # انتظار قبل إعادة المحاولة تلقائياً
