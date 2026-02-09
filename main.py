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

# تحميل متغيرات البيئة
load_dotenv()

# === إعداد التسجيل ===
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

if not API_TOKEN or not DATABASE_URL:
    logger.error("❌ خطأ: يجب ضبط API_TOKEN و DATABASE_URL في Render!")
    exit(1)

# === إعداد خادم الويب (Keep Alive) ===
app = Flask('')
@app.route('/')
def home(): return "Bot is Alive!"

def run_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def self_ping():
    if not RENDER_EXTERNAL_URL: return
    while True:
        try:
            requests.get(RENDER_EXTERNAL_URL)
            logger.info("📡 Self-Ping: Active")
        except: pass
        time.sleep(600)

# === فئة قاعدة البيانات (Supabase/PostgreSQL) ===
class Database:
    def __init__(self):
        self.connection_pool = None
        self.init_pool()
        self.init_database()

    def init_pool(self):
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        try:
            self.connection_pool = psycopg2.pool.SimpleConnectionPool(1, 15, url)
            logger.info("✅ Connected to Supabase Pool.")
        except Exception as e:
            logger.error(f"❌ Connection Failed: {e}")
            exit(1)

    def get_conn(self): return self.connection_pool.getconn()
    def put_conn(self, conn): self.connection_pool.putconn(conn)

    def init_database(self):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS subjects (id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL);
                    CREATE TABLE IF NOT EXISTS files (id SERIAL PRIMARY KEY, subject_id INTEGER REFERENCES subjects(id) ON DELETE CASCADE, file_id TEXT NOT NULL, file_name TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS channels (id SERIAL PRIMARY KEY, channel_id TEXT UNIQUE NOT NULL, channel_link TEXT NOT NULL, channel_name TEXT);
                    CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT, joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
                """)
                conn.commit()
        finally: self.put_conn(conn)

    # --- دوال المستخدمين والقنوات ---
    def add_user(self, uid, user, name):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (user_id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING", (uid, user, name))
            conn.commit()
        self.put_conn(conn)

    def add_channel(self, cid, clink, cname):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO channels (channel_id, channel_link, channel_name) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (cid, clink, cname))
            conn.commit()
            res = cur.rowcount > 0
        self.put_conn(conn)
        return res

    def get_all_channels(self):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT channel_id, channel_link, channel_name FROM channels")
            res = cur.fetchall()
        self.put_conn(conn)
        return res

    def delete_channel(self, cid):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM channels WHERE channel_id = %s", (cid,))
            conn.commit()
        self.put_conn(conn)

    # --- دوال المواد والملفات ---
    def add_subject(self, name):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO subjects (name) VALUES (%s) ON CONFLICT DO NOTHING", (name,))
            conn.commit()
            res = cur.rowcount > 0
        self.put_conn(conn)
        return res

    def get_all_subjects(self):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM subjects ORDER BY name")
            res = cur.fetchall()
        self.put_conn(conn)
        return res

    def get_subject_by_name(self, name):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM subjects WHERE name = %s", (name,))
            res = cur.fetchone()
        self.put_conn(conn)
        return res

    def add_file(self, sid, fid, fname):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO files (subject_id, file_id, file_name) VALUES (%s, %s, %s)", (sid, fid, fname))
            conn.commit()
        self.put_conn(conn)

    def get_subject_files(self, sname):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT f.file_id, f.file_name FROM files f JOIN subjects s ON f.subject_id = s.id WHERE s.name = %s", (sname,))
            res = cur.fetchall()
        self.put_conn(conn)
        return res

# === تهيئة البوت ===
db = Database()
bot = telebot.TeleBot(API_TOKEN)
user_states = {}

# === دوال مساعدة ===
def is_admin(uid): return uid == ADMIN_ID

def check_subscription(uid):
    if is_admin(uid): return True, []
    channels = db.get_all_channels()
    unsubbed = []
    for cid, link, name in channels:
        try:
            member = bot.get_chat_member(cid, uid)
            if member.status not in ['member', 'administrator', 'creator']:
                unsubbed.append((name or cid, link))
        except: unsubbed.append((name or cid, link))
    return len(unsubbed) == 0, unsubbed

def get_sub_keyboard(unsubbed):
    kb = types.InlineKeyboardMarkup()
    for name, link in unsubbed:
        kb.add(types.InlineKeyboardButton(f"🔗 اشترك في {name}", url=link))
    kb.add(types.InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data="check_sub"))
    return kb

def get_user_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    for _, name in db.get_all_subjects(): kb.add(types.KeyboardButton(name))
    kb.add("🔄 تحديث", "ℹ️ مساعدة")
    return kb

def get_admin_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.row("➕ إضافة مادة", "🗑️ حذف مادة")
    kb.row("📁 رفع ملف", "🔗 إضافة قناة")
    kb.row("👥 المستخدمين", "📊 إحصائيات")
    kb.row("🏠 الرئيسية", "🚫 حذف قناة")
    return kb

# === معالجات الأوامر ===
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    db.add_user(uid, message.from_user.username, message.from_user.first_name)
    
    is_sub, unsubbed = check_subscription(uid)
    if not is_sub:
        bot.send_message(message.chat.id, "⚠️ يجب الاشتراك في القنوات أولاً:", reply_markup=get_sub_keyboard(unsubbed))
        return

    if is_admin(uid):
        bot.send_message(message.chat.id, "👑 لوحة التحكم:", reply_markup=get_admin_keyboard())
    else:
        bot.send_message(message.chat.id, "📚 اختر مادة:", reply_markup=get_user_keyboard())

# --- معالجة القنوات (آدمن) ---
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "🔗 إضافة قناة")
def add_chan_step1(m):
    user_states[m.from_user.id] = "adding_chan"
    bot.send_message(m.chat.id, "أرسل معرف القناة (مثلاً @username) ثم مسافة ثم الرابط:", reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and user_states.get(m.from_user.id) == "adding_chan")
def add_chan_step2(m):
    try:
        parts = m.text.split()
        cid, clink = parts[0], parts[1]
        db.add_channel(cid, clink, f"قناة {cid}")
        bot.send_message(m.chat.id, "✅ تمت إضافة القناة", reply_markup=get_admin_keyboard())
    except:
        bot.send_message(m.chat.id, "❌ خطأ في التنسيق. استخدم: @id link", reply_markup=get_admin_keyboard())
    del user_states[m.from_user.id]

# --- معالجة المواد والملفات ---
@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "➕ إضافة مادة")
def add_sub_step1(m):
    user_states[m.from_user.id] = "adding_sub"
    bot.send_message(m.chat.id, "✏️ اسم المادة الجديدة:", reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and user_states.get(m.from_user.id) == "adding_sub")
def add_sub_step2(m):
    db.add_subject(m.text.strip())
    bot.send_message(m.chat.id, "✅ تم الحفظ", reply_markup=get_admin_keyboard())
    del user_states[m.from_user.id]

@bot.message_handler(func=lambda m: is_admin(m.from_user.id) and m.text == "📁 رفع ملف")
def upload_file_step1(m):
    kb = types.InlineKeyboardMarkup()
    for sid, name in db.get_all_subjects():
        kb.add(types.InlineKeyboardButton(name, callback_data=f"up_{sid}"))
    bot.send_message(m.chat.id, "اختر المادة:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith("up_"))
def upload_file_step2(call):
    sid = call.data.split("_")[1]
    user_states[call.from_user.id] = f"wait_file_{sid}"
    bot.edit_message_text("📎 أرسل الملف الآن:", call.message.chat.id, call.message.message_id)

@bot.message_handler(content_types=['document'])
def handle_docs(m):
    state = user_states.get(m.from_user.id, "")
    if state.startswith("wait_file_"):
        sid = int(state.split("_")[2])
        db.add_file(sid, m.document.file_id, m.document.file_name)
        bot.send_message(m.chat.id, "✅ تم الرفع", reply_markup=get_admin_keyboard())
        del user_states[m.from_user.id]

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def verify_sub(call):
    is_sub, unsubbed = check_subscription(call.from_user.id)
    if is_sub:
        bot.answer_callback_query(call.id, "✅ تم التحقق!")
        bot.edit_message_text("📚 تم التفعيل، أرسل /start", call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "⚠️ لم تشترك بعد!", show_alert=True)

@bot.message_handler(func=lambda m: True)
def view_files(m):
    is_sub, unsubbed = check_subscription(m.from_user.id)
    if not is_sub:
        bot.send_message(m.chat.id, "⚠️ اشترك أولاً:", reply_markup=get_sub_keyboard(unsubbed))
        return
    
    sub = db.get_subject_by_name(m.text)
    if sub:
        files = db.get_subject_files(m.text)
        if not files: bot.send_message(m.chat.id, "⚠️ لا توجد ملفات.")
        for fid, fname in files:
            bot.send_document(m.chat.id, fid, caption=f"📄 {fname}")

if __name__ == '__main__':
    Thread(target=run_server, daemon=True).start()
    Thread(target=self_ping, daemon=True).start()
    bot.infinity_polling()
