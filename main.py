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

# تحميل المتغيرات من ملف .env
load_dotenv()

# === إعداد التسجيل ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === الإعدادات من متغيرات البيئة ===
API_TOKEN = os.getenv('API_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
DATABASE_URL = os.getenv('DATABASE_URL')
# رابط البوت الخارجي (مثلاً من Render) لعمل الـ Ping
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL')

# === خادم الويب (Keep Alive) ===
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

@app.route('/health')
def health():
    return "OK", 200

def run_server():
    # المنفذ الافتراضي 8080 أو ما يحدده السيرفر
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def self_ping():
    """وظيفة تقوم بزيارة رابط البوت كل 5 دقائق لمنع النوم (Sleep)"""
    if not RENDER_EXTERNAL_URL:
        logger.warning("⚠️ RENDER_EXTERNAL_URL غير معرف، لن يتم تفعيل الـ Ping التلقائي.")
        return
    
    logger.info(f"🚀 تم تفعيل ميزة Ping التلقائي على الرابط: {RENDER_EXTERNAL_URL}")
    while True:
        try:
            # محاولة الوصول للرابط لابقاء السيرفر مستيقظاً
            requests.get(RENDER_EXTERNAL_URL, timeout=10)
            logger.info("📡 Ping sent successfully.")
        except Exception as e:
            logger.warning(f"⚠️ فشل في إرسال Ping: {e}")
        time.sleep(300)  # الانتظار لمدة 5 دقائق (300 ثانية)

# === قاعدة البيانات ===
class Database:
    def __init__(self):
        url = DATABASE_URL
        if url and url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        try:
            # استخدام Connection Pool لضمان استقرار الاتصال
            self.pool = psycopg2.pool.SimpleConnectionPool(1, 10, url)
            self.init_db()
        except Exception as e:
            logger.error(f"❌ Database connection error: {e}")
            exit(1)

    def get_conn(self): return self.pool.getconn()
    def put_conn(self, conn): self.pool.putconn(conn)

    def init_db(self):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS subjects (id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL);")
            cur.execute("CREATE TABLE IF NOT EXISTS files (id SERIAL PRIMARY KEY, subject_id INTEGER REFERENCES subjects(id) ON DELETE CASCADE, file_id TEXT NOT NULL, file_name TEXT NOT NULL);")
            cur.execute("CREATE TABLE IF NOT EXISTS channels (id SERIAL PRIMARY KEY, channel_id TEXT UNIQUE NOT NULL, channel_link TEXT NOT NULL, channel_name TEXT);")
            cur.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT, joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
            conn.commit()
        self.put_conn(conn)

    # (بقية دوال قاعدة البيانات كما هي في السكربت الأصلي بدون تعديل)
    def add_user(self, uid, user, name):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("INSERT INTO users (user_id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING", (uid, user, name))
        conn.commit(); cur.close(); self.put_conn(conn)

    def get_all_subjects(self):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, name FROM subjects ORDER BY name")
        res = cur.fetchall(); cur.close(); self.put_conn(conn)
        return res

    def get_all_channels(self):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("SELECT channel_id, channel_link, channel_name FROM channels")
        res = cur.fetchall(); cur.close(); self.put_conn(conn)
        return res

# تهيئة الكائنات
db = Database()
bot = telebot.TeleBot(API_TOKEN)
user_states = {}

# (هنا تضع بقية الكيبوردات والمعالجات "Handlers" كما هي في سكربتك الأصلي)
# ... [بقية منطق البوت] ...

# === بدء التشغيل المدمج ===
if __name__ == '__main__':
    # 1. تشغيل خادم الويب (Flask) في خيط منفصل
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()

    # 2. تشغيل ميزة الـ Ping التلقائي في خيط منفصل
    ping_thread = Thread(target=self_ping)
    ping_thread.daemon = True
    ping_thread.start()

    # 3. تنظيف أي اتصالات قديمة وبدء البوت
    logger.info("🚀 تنظيف الاتصالات القديمة وبدء تشغيل البوت...")
    bot.remove_webhook()
    time.sleep(1)
    
    # استخدام infinity_polling لضمان استمرارية العمل
    bot.infinity_polling(skip_pending=True)
