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

# === الإعدادات ===
API_TOKEN = os.getenv('API_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
DATABASE_URL = os.getenv('DATABASE_URL')
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL')

# === خادم الويب (Keep Alive) ===
app = Flask('')
@app.route('/')
def home(): return "Bot is Alive!"

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
        if url.startswith("postgres://"): url = url.replace("postgres://", "postgresql://", 1)
        self.pool = psycopg2.pool.SimpleConnectionPool(1, 20, url)
        self.init_db()

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

    # دوال الجلب (Selects)
    def get_users(self):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, username, first_name FROM users ORDER BY joined_at DESC")
            res = cur.fetchall()
        self.put_conn(conn)
        return res

    def get_stats(self):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            u_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM subjects")
            s_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM files")
            f_count = cur.fetchone()[0]
        self.put_conn(conn)
        return u_count, s_count, f_count

    # بقية الدوال (إضافة وحذف) ...
    def add_user(self, uid, user, name):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (user_id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING", (uid, user, name))
            conn.commit()
        self.put_conn(conn)

    def add_subject(self, name):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO subjects (name) VALUES (%s) ON CONFLICT DO NOTHING", (name,))
            conn.commit()
        self.put_conn(conn)

    def delete_subject(self, sid):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM subjects WHERE id = %s", (sid,))
            conn.commit()
        self.put_conn(conn)

    def delete_channel(self, cid):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM channels WHERE channel_id = %s", (cid,))
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

# === الكيبوردات ===
def get_admin_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.row("➕ إضافة مادة", "🗑️ حذف مادة")
    kb.row("📁 رفع ملف", "🔗 إضافة قناة")
    kb.row("👥 المستخدمين", "📊 إحصائيات")
    kb.row("🏠 الرئيسية", "🚫 حذف قناة")
    return kb

def get_user_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    for _, name in db.get_all_subjects(): kb.add(types.KeyboardButton(name))
    kb.add("🔄 تحديث", "ℹ️ مساعدة")
    return kb

# === معالجات الأزرار الإدارية (الإصلاح هنا) ===

@bot.message_handler(func=lambda m: m.text == "🏠 الرئيسية")
def main_menu(m):
    user_states.pop(m.from_user.id, None)
    if m.from_user.id == ADMIN_ID:
        bot.send_message(m.chat.id, "🏠 عدنا للوحة التحكم", reply_markup=get_admin_keyboard())
    else:
        bot.send_message(m.chat.id, "🏠 القائمة الرئيسية", reply_markup=get_user_keyboard())

@bot.message_handler(func=lambda m: m.text == "📊 إحصائيات" and m.from_user.id == ADMIN_ID)
def stats(m):
    u, s, f = db.get_stats()
    bot.send_message(m.chat.id, f"📊 *إحصائيات البوت:*\n\n👥 عدد المستخدمين: {u}\n📚 عدد المواد: {s}\n📁 عدد الملفات: {f}", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "👥 المستخدمين" and m.from_user.id == ADMIN_ID)
def list_users(m):
    users = db.get_users()[:20] # عرض آخر 20 مستخدم فقط لتفادي طول الرسالة
    text = "👥 *آخر المستخدمين المنضمين:*\n\n"
    for uid, user, name in users:
        text += f"- {name} (@{user}) [`{uid}`]\n"
    bot.send_message(m.chat.id, text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "🗑️ حذف مادة" and m.from_user.id == ADMIN_ID)
def del_sub_menu(m):
    subjects = db.get_all_subjects()
    kb = types.InlineKeyboardMarkup()
    for sid, name in subjects:
        kb.add(types.InlineKeyboardButton(f"❌ {name}", callback_data=f"ds_{sid}"))
    bot.send_message(m.chat.id, "🗑️ اختر المادة المراد حذفها نهائياً:", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "🚫 حذف قناة" and m.from_user.id == ADMIN_ID)
def del_chan_menu(m):
    channels = db.get_all_channels()
    kb = types.InlineKeyboardMarkup()
    for cid, link, name in channels:
        kb.add(types.InlineKeyboardButton(f"🚫 {name or cid}", callback_data=f"dc_{cid}"))
    bot.send_message(m.chat.id, "🚫 اختر القناة المراد حذفها:", reply_markup=kb)

# === معالجة الـ Callback للحذف ===
@bot.callback_query_handler(func=lambda call: call.data.startswith(("ds_", "dc_")))
def delete_callback(call):
    if call.data.startswith("ds_"):
        sid = int(call.data.split("_")[1])
        db.delete_subject(sid)
        bot.answer_callback_query(call.id, "✅ تم حذف المادة")
        bot.edit_message_text("✅ تم حذف المادة ومحتوياتها بنجاح.", call.message.chat.id, call.message.message_id)
    elif call.data.startswith("dc_"):
        cid = call.data.split("_")[1]
        db.delete_channel(cid)
        bot.answer_callback_query(call.id, "✅ تم حذف القناة")
        bot.edit_message_text("✅ تم إزالة القناة من قائمة الاشتراك الإجباري.", call.message.chat.id, call.message.message_id)

# (بقية المعالجات السابقة: إضافة مادة، رفع ملف، التحقق من الاشتراك تبقى كما هي في الكود السابق)
# ... أضف هنا الـ handlers الخاصة بالبداية والتحقق والرفع التي أرسلتها لك في الرد السابق ...

if __name__ == '__main__':
    Thread(target=run_server, daemon=True).start()
    Thread(target=self_ping, daemon=True).start()
    bot.infinity_polling()
