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

load_dotenv()

# === إعداد التسجيل ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === الإعدادات من Environment Variables ===
API_TOKEN = os.getenv('API_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
DATABASE_URL = os.getenv('DATABASE_URL')
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL')

# === خادم الويب (Keep Alive) ===
app = Flask('')
@app.route('/')
def home(): return "Bot is running!"

def run_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def self_ping():
    if not RENDER_EXTERNAL_URL: return
    while True:
        try: requests.get(RENDER_EXTERNAL_URL)
        except: pass
        time.sleep(600)

# === قاعدة البيانات ===
class Database:
    def __init__(self):
        url = DATABASE_URL
        if url and url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        try:
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

    # دوال الإدارة
    def get_stats(self):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT (SELECT COUNT(*) FROM users), (SELECT COUNT(*) FROM subjects), (SELECT COUNT(*) FROM files)")
            res = cur.fetchone()
        self.put_conn(conn)
        return res

    def add_user(self, uid, user, name):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (user_id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING", (uid, user, name))
            conn.commit()
        self.put_conn(conn)

    def get_all_subjects(self):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM subjects ORDER BY name")
            res = cur.fetchall()
        self.put_conn(conn)
        return res

    def get_all_channels(self):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT channel_id, channel_link, channel_name FROM channels")
            res = cur.fetchall()
        self.put_conn(conn)
        return res

db = Database()
bot = telebot.TeleBot(API_TOKEN)
user_states = {}

# === التحقق من الاشتراك ===
def check_sub(uid):
    if uid == ADMIN_ID: return True, []
    channels = db.get_all_channels()
    unsubbed = []
    for cid, link, name in channels:
        try:
            status = bot.get_chat_member(cid, uid).status
            if status not in ['member', 'administrator', 'creator']: unsubbed.append((name or cid, link))
        except: unsubbed.append((name or cid, link))
    return len(unsubbed) == 0, unsubbed

# === الكيبوردات ===
def get_main_kb(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if uid == ADMIN_ID:
        kb.row("➕ إضافة مادة", "🗑️ حذف مادة")
        kb.row("📁 رفع ملف", "🔗 إضافة قناة")
        kb.row("👥 المستخدمين", "📊 إحصائيات")
        kb.row("🏠 الرئيسية", "🚫 حذف قناة")
    else:
        for _, name in db.get_all_subjects(): kb.add(types.KeyboardButton(name))
        kb.add("🔄 تحديث", "ℹ️ مساعدة")
    return kb

# === المعالجات ===
@bot.message_handler(commands=['start'])
def start(m):
    db.add_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    ok, unsubbed = check_sub(m.from_user.id)
    if not ok:
        ikb = types.InlineKeyboardMarkup()
        for name, link in unsubbed: ikb.add(types.InlineKeyboardButton(f"🔗 اشترك في {name}", url=link))
        ikb.add(types.InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data="recheck"))
        bot.send_message(m.chat.id, "⚠️ يجب الاشتراك لاستخدام البوت:", reply_markup=ikb)
    else:
        bot.send_message(m.chat.id, "📚 أهلاً بك! اختر من القائمة:", reply_markup=get_main_kb(m.from_user.id))

@bot.message_handler(func=lambda m: m.text == "📊 إحصائيات" and m.from_user.id == ADMIN_ID)
def stats(m):
    u, s, f = db.get_stats()
    bot.send_message(m.chat.id, f"📊 الإحصائيات:\n- المستخدمين: {u}\n- المواد: {s}\n- الملفات: {f}")

@bot.message_handler(func=lambda m: m.text == "🏠 الرئيسية")
def home_btn(m):
    user_states.pop(m.from_user.id, None)
    bot.send_message(m.chat.id, "العودة للقائمة الرئيسية", reply_markup=get_main_kb(m.from_user.id))

# تنظيف التعارض وبدء التشغيل
if __name__ == '__main__':
    Thread(target=run_server, daemon=True).start()
    Thread(target=self_ping, daemon=True).start()
    
    logger.info("🚀 Cleaning old connections...")
    bot.remove_webhook()  # حل مشكلة التعارض
    time.sleep(1)
    
    logger.info("✅ Bot is starting...")
    bot.infinity_polling(skip_pending=True)
