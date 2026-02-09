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

# === خادم Flask للـ Ping ===
app = Flask('')
@app.route('/')
def home():
    return "Bot is Alive!"

def run_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def self_ping():
    if not RENDER_EXTERNAL_URL:
        return
    while True:
        try:
            requests.get(RENDER_EXTERNAL_URL, timeout=10)
            logger.info("📡 Ping sent")
        except:
            pass
        time.sleep(300)

# === قاعدة البيانات ===
class Database:
    def __init__(self):
        url = DATABASE_URL
        if url and url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        self.pool = psycopg2.pool.SimpleConnectionPool(1, 15, url)
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

    def get_stats(self):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("""
        SELECT
        (SELECT COUNT(*) FROM users),
        (SELECT COUNT(*) FROM subjects),
        (SELECT COUNT(*) FROM files),
        (SELECT COUNT(*) FROM channels)
        """)
        res = cur.fetchone()
        cur.close(); self.put_conn(conn)
        return res

    def add_user(self, uid, user, name):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("""
        INSERT INTO users (user_id, username, first_name)
        VALUES (%s,%s,%s)
        ON CONFLICT (user_id) DO NOTHING
        """, (uid, user, name))
        conn.commit()
        cur.close(); self.put_conn(conn)

    def get_all_subjects(self):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, name FROM subjects ORDER BY name")
        res = cur.fetchall()
        cur.close(); self.put_conn(conn)
        return res

    def search_subjects(self, kw):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, name FROM subjects WHERE name ILIKE %s", (f"%{kw}%",))
        res = cur.fetchall()
        cur.close(); self.put_conn(conn)
        return res

    def add_subject(self, name):
        conn = self.get_conn(); cur = conn.cursor()
        try:
            cur.execute("INSERT INTO subjects (name) VALUES (%s) ON CONFLICT DO NOTHING", (name,))
            conn.commit()
            return True
        except:
            return False
        finally:
            cur.close(); self.put_conn(conn)

    def delete_subject(self, sid):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("DELETE FROM subjects WHERE id=%s", (sid,))
        conn.commit()
        cur.close(); self.put_conn(conn)

    def add_file(self, sid, fid, fname):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("INSERT INTO files (subject_id,file_id,file_name) VALUES (%s,%s,%s)", (sid, fid, fname))
        conn.commit()
        cur.close(); self.put_conn(conn)

    def get_files_by_subject(self, sid):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("SELECT file_id, file_name FROM files WHERE subject_id=%s", (sid,))
        res = cur.fetchall()
        cur.close(); self.put_conn(conn)
        return res

    def get_all_channels(self):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("SELECT channel_id, channel_link, channel_name FROM channels")
        res = cur.fetchall()
        cur.close(); self.put_conn(conn)
        return res

    def add_channel(self, cid, link, name):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("""
        INSERT INTO channels (channel_id, channel_link, channel_name)
        VALUES (%s,%s,%s)
        ON CONFLICT (channel_id)
        DO UPDATE SET channel_link=EXCLUDED.channel_link
        """, (cid, link, name))
        conn.commit()
        cur.close(); self.put_conn(conn)

    def delete_channel(self, cid):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("DELETE FROM channels WHERE channel_id=%s", (cid,))
        conn.commit()
        cur.close(); self.put_conn(conn)

    def get_all_users(self):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("SELECT user_id, username, first_name FROM users LIMIT 50")
        res = cur.fetchall()
        cur.close(); self.put_conn(conn)
        return res

# === التهيئة ===
db = Database()
bot = telebot.TeleBot(API_TOKEN)
user_states = {}

# === الكيبورد ===
def get_main_kb(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if uid == ADMIN_ID:
        kb.row("➕ إضافة مادة", "🗑️ حذف مادة")
        kb.row("📁 رفع ملف", "🔗 إضافة قناة")
        kb.row("👥 المستخدمين", "📊 إحصائيات")
        kb.row("🏠 الرئيسية", "🚫 حذف قناة")
    else:
        subjects = db.get_all_subjects()
        for i in range(0, len(subjects), 2):
            kb.row(*[s[1] for s in subjects[i:i+2]])
        kb.row("🔄 تحديث", "🔍 بحث")
    return kb

# === التحقق من الاشتراك ===
def check_sub(uid):
    if uid == ADMIN_ID:
        return True, []
    unsub = []
    for cid, link, name in db.get_all_channels():
        try:
            status = bot.get_chat_member(cid, uid).status
            if status not in ['member', 'administrator', 'creator']:
                unsub.append((name, link))
        except:
            unsub.append((name, link))
    return len(unsub) == 0, unsub

# === Handlers ===
@bot.message_handler(commands=['start'])
def start(m):
    db.add_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    ok, unsub = check_sub(m.from_user.id)
    if not ok:
        ikb = types.InlineKeyboardMarkup()
        for n, l in unsub:
            ikb.add(types.InlineKeyboardButton(f"اشترك في {n}", url=l))
        ikb.add(types.InlineKeyboardButton("تأكيد الاشتراك ✅", callback_data="recheck"))
        bot.send_message(m.chat.id, "يجب الاشتراك أولاً 👇", reply_markup=ikb)
    else:
        bot.send_message(m.chat.id, "📚 اختر المادة:", reply_markup=get_main_kb(m.from_user.id))

@bot.message_handler(func=lambda m: m.text == "🚫 حذف قناة" and m.from_user.id == ADMIN_ID)
def del_channel_step(m):
    channels = db.get_all_channels()
    if not channels:
        bot.send_message(m.chat.id, "❌ لا توجد قنوات")
        return
    ikb = types.InlineKeyboardMarkup()
    for cid, link, name in channels:
        ikb.add(types.InlineKeyboardButton(name or cid, callback_data=f"dc_{cid}"))
    bot.send_message(m.chat.id, "🚫 اختر القناة للحذف:", reply_markup=ikb)

@bot.callback_query_handler(func=lambda c: True)
def callbacks(c):
    if c.data.startswith("dc_"):
        cid = c.data.split("_", 1)[1]
        db.delete_channel(cid)
        bot.edit_message_text("✅ تم حذف القناة بنجاح", c.message.chat.id, c.message.message_id)

    elif c.data == "recheck":
        ok, _ = check_sub(c.from_user.id)
        if ok:
            bot.send_message(c.message.chat.id, "✅ تم التفعيل", reply_markup=get_main_kb(c.from_user.id))
        else:
            bot.answer_callback_query(c.id, "❌ لم يتم الاشتراك بعد")

# === التشغيل ===
if __name__ == '__main__':
    Thread(target=run_server, daemon=True).start()
    Thread(target=self_ping, daemon=True).start()
    bot.remove_webhook()
    time.sleep(1)
    bot.infinity_polling(skip_pending=True)
