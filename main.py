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

# تحميل الإعدادات
load_dotenv()

# === إعداد التسجيل (Logging) ===
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === الإعدادات من متغيرات البيئة ===
API_TOKEN = os.getenv('API_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
DATABASE_URL = os.getenv('DATABASE_URL')
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL')

# التحقق من وجود الإعدادات الأساسية
if not API_TOKEN or not DATABASE_URL:
    logger.error("❌ تأكد من ضبط API_TOKEN و DATABASE_URL في الإعدادات!")
    exit(1)

# === نظام Keep Alive لمنع توقف البوت في Render ===
app = Flask('')

@app.route('/')
def home(): 
    return "Bot is alive and kicking!"

@app.route('/health')
def health():
    return "OK", 200

def run_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def self_ping():
    if not RENDER_EXTERNAL_URL: 
        return
    while True:
        try: 
            requests.get(RENDER_EXTERNAL_URL, timeout=10)
            logger.info("📡 Ping sent to keep the bot awake.")
        except Exception as e:
            logger.warning(f"⚠️ Ping failed: {e}")
        time.sleep(600) # كل 10 دقائق

# === فئة قاعدة البيانات (PostgreSQL) ===
class Database:
    def __init__(self):
        url = DATABASE_URL
        if url and url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        try:
            # استخدام Connection Pool لإدارة أفضل للاتصالات
            self.pool = psycopg2.pool.SimpleConnectionPool(1, 20, url)
            self.init_db()
            logger.info("✅ Database Pool initialized.")
        except Exception as e:
            logger.error(f"❌ Database error: {e}")
            exit(1)

    def get_conn(self): 
        return self.pool.getconn()
    
    def put_conn(self, conn): 
        self.pool.putconn(conn)

    def init_db(self):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                # إنشاء الجداول
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS subjects (id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL);
                    CREATE TABLE IF NOT EXISTS files (
                        id SERIAL PRIMARY KEY, 
                        subject_id INTEGER REFERENCES subjects(id) ON DELETE CASCADE, 
                        file_id TEXT NOT NULL, 
                        file_name TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS channels (
                        id SERIAL PRIMARY KEY, 
                        channel_id TEXT UNIQUE NOT NULL, 
                        channel_link TEXT NOT NULL, 
                        channel_name TEXT
                    );
                    CREATE TABLE IF NOT EXISTS users (
                        user_id BIGINT PRIMARY KEY, 
                        username TEXT, 
                        first_name TEXT, 
                        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.commit()
        finally:
            self.put_conn(conn)

    # --- دوال العمليات ---
    def add_user(self, uid, user, name):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO users (user_id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING", (uid, user, name))
                conn.commit()
        finally: self.put_conn(conn)

    def get_stats(self):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT (SELECT COUNT(*) FROM users), (SELECT COUNT(*) FROM subjects), (SELECT COUNT(*) FROM files), (SELECT COUNT(*) FROM channels)")
                return cur.fetchone()
        finally: self.put_conn(conn)

    def get_all_subjects(self):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name FROM subjects ORDER BY name")
                return cur.fetchall()
        finally: self.put_conn(conn)

    def get_subject_by_id(self, sub_id):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name FROM subjects WHERE id = %s", (sub_id,))
                return cur.fetchone()
        finally: self.put_conn(conn)

    def add_subject(self, name):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO subjects (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (name,))
                conn.commit()
                return cur.rowcount > 0
        finally: self.put_conn(conn)

    def add_file(self, sid, fid, fname):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO files (subject_id, file_id, file_name) VALUES (%s, %s, %s)", (sid, fid, fname))
                conn.commit()
                return True
        finally: self.put_conn(conn)

    def get_files_by_subject(self, sid):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT file_id, file_name FROM files WHERE subject_id = %s", (sid,))
                return cur.fetchall()
        finally: self.put_conn(conn)

# === تهيئة البوت وقاعدة البيانات ===
db = Database()
bot = telebot.TeleBot(API_TOKEN)
user_states = {}

# 

# === دوال المساعدة ===
def check_sub(uid):
    if uid == ADMIN_ID: return True, []
    channels = db.get_all_channels() if hasattr(db, 'get_all_channels') else []
    unsubbed = []
    for cid, link, name in channels:
        try:
            status = bot.get_chat_member(cid, uid).status
            if status not in ['member', 'administrator', 'creator']: unsubbed.append((name or cid, link))
        except: unsubbed.append((name or cid, link))
    return len(unsubbed) == 0, unsubbed

def get_main_kb(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if uid == ADMIN_ID:
        kb.row("➕ إضافة مادة", "🗑️ حذف مادة")
        kb.row("📁 رفع ملف", "📊 إحصائيات")
        kb.row("🏠 الرئيسية", "🔗 إضافة قناة")
    else:
        subjects = db.get_all_subjects()
        for i in range(0, len(subjects), 2):
            row = subjects[i:i+2]
            kb.row(*[types.KeyboardButton(s[1]) for s in row])
        kb.row("🔄 تحديث", "🔍 بحث")
    return kb

# === معالجات الأوامر (Handlers) ===
@bot.message_handler(commands=['start'])
def welcome(m):
    db.add_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    bot.send_message(m.chat.id, "📚 أهلاً بك في بوت المواد الدراسية!", reply_markup=get_main_kb(m.from_user.id))

@bot.message_handler(func=lambda m: m.text == "📊 إحصائيات" and m.from_user.id == ADMIN_ID)
def show_stats(m):
    u, s, f, c = db.get_stats()
    bot.send_message(m.chat.id, f"📊 إحصائيات البوت:\n\n👥 مستخدمين: {u}\n📚 مواد: {s}\n📁 ملفات: {f}\n🔗 قنوات: {c}")

@bot.message_handler(func=lambda m: m.text == "➕ إضافة مادة" and m.from_user.id == ADMIN_ID)
def ask_subject_name(m):
    user_states[m.from_user.id] = 'adding_subject'
    bot.send_message(m.chat.id, "📝 أدخل اسم المادة الجديدة:", reply_markup=types.ReplyKeyboardRemove())

@bot.message_handler(func=lambda m: m.from_user.id == ADMIN_ID and user_states.get(m.from_user.id) == 'adding_subject')
def save_subject(m):
    if db.add_subject(m.text):
        bot.send_message(m.chat.id, f"✅ تم إضافة المادة: {m.text}", reply_markup=get_main_kb(m.from_user.id))
    else:
        bot.send_message(m.chat.id, "❌ فشل الإضافة (ربما موجودة بالفعل).")
    user_states.pop(m.from_user.id, None)

@bot.message_handler(func=lambda m: m.text == "📁 رفع ملف" and m.from_user.id == ADMIN_ID)
def select_subject_for_file(m):
    subjects = db.get_all_subjects()
    if not subjects:
        return bot.send_message(m.chat.id, "❌ لا توجد مواد حالياً.")
    
    kb = types.InlineKeyboardMarkup()
    for sid, name in subjects:
        kb.add(types.InlineKeyboardButton(name, callback_data=f"up_{sid}"))
    bot.send_message(m.chat.id, "اختر المادة لرفع الملف إليها:", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data.startswith('up_'))
def handle_upload_selection(call):
    sid = call.data.split('_')[1]
    user_states[call.from_user.id] = f'waiting_file_{sid}'
    bot.edit_message_text("📎 أرسل الملف الآن (PDF, Word, etc.):", call.message.chat.id, call.message.message_id)

@bot.message_handler(content_types=['document'])
def receive_file(m):
    state = user_states.get(m.from_user.id, "")
    if state.startswith('waiting_file_'):
        sid = int(state.split('_')[2])
        if db.add_file(sid, m.document.file_id, m.document.file_name):
            bot.send_message(m.chat.id, f"✅ تم حفظ الملف: {m.document.file_name}", reply_markup=get_main_kb(m.from_user.id))
        user_states.pop(m.from_user.id, None)

@bot.message_handler(func=lambda m: True)
def handle_user_selection(m):
    # إذا كان النص هو اسم مادة موجودة
    subjects = db.get_all_subjects()
    subject_map = {s[1]: s[0] for s in subjects}
    
    if m.text in subject_map:
        sid = subject_map[m.text]
        files = db.get_files_by_subject(sid)
        if not files:
            return bot.send_message(m.chat.id, f"📭 لا توجد ملفات في مادة {m.text} حالياً.")
        
        bot.send_message(m.chat.id, f"📁 ملفات مادة {m.text}:")
        for fid, fname in files:
            bot.send_document(m.chat.id, fid, caption=f"📄 {fname}")
    else:
        bot.send_message(m.chat.id, "⚠️ الرجاء اختيار مادة من القائمة.")

# === تشغيل البوت ===
if __name__ == '__main__':
    # تشغيل خادم الويب في خلفية
    Thread(target=run_server, daemon=True).start()
    Thread(target=self_ping, daemon=True).start()
    
    logger.info("🚀 Cleaning old webhooks...")
    bot.remove_webhook()
    time.sleep(1)
    
    logger.info("✅ Bot is online!")
    bot.infinity_polling(skip_pending=True)
