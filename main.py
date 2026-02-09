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
def home(): return "Bot is Alive!"

def run_server():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def self_ping():
    if not RENDER_EXTERNAL_URL: return
    while True:
        try: 
            requests.get(RENDER_EXTERNAL_URL, timeout=10)
            logger.info("📡 تم إرسال Ping لابقاء السيرفر مستيقظاً")
        except: pass
        time.sleep(300)

# === قاعدة البيانات (كافة الخصائص الأصلية) ===
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

    # --- دوال العمليات ---
    def get_stats(self):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("SELECT (SELECT COUNT(*) FROM users), (SELECT COUNT(*) FROM subjects), (SELECT COUNT(*) FROM files), (SELECT COUNT(*) FROM channels)")
        res = cur.fetchone(); cur.close(); self.put_conn(conn)
        return res

    def add_user(self, uid, user, name):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("INSERT INTO users (user_id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING", (uid, user, name))
        conn.commit(); cur.close(); self.put_conn(conn)

    def get_all_subjects(self):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, name FROM subjects ORDER BY name")
        res = cur.fetchall(); cur.close(); self.put_conn(conn)
        return res

    def search_subjects(self, kw):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("SELECT id, name FROM subjects WHERE name ILIKE %s", (f'%{kw}%',))
        res = cur.fetchall(); cur.close(); self.put_conn(conn)
        return res

    def add_subject(self, name):
        conn = self.get_conn(); cur = conn.cursor()
        try:
            cur.execute("INSERT INTO subjects (name) VALUES (%s) ON CONFLICT DO NOTHING", (name,))
            conn.commit(); return True
        except: return False
        finally: cur.close(); self.put_conn(conn)

    def delete_subject(self, sid):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("DELETE FROM subjects WHERE id = %s", (sid,))
        conn.commit(); cur.close(); self.put_conn(conn)
        return True

    def add_file(self, sid, fid, fname):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("INSERT INTO files (subject_id, file_id, file_name) VALUES (%s, %s, %s)", (sid, fid, fname))
        conn.commit(); cur.close(); self.put_conn(conn)
        return True

    def get_files_by_subject(self, sid):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("SELECT file_id, file_name FROM files WHERE subject_id = %s", (sid,))
        res = cur.fetchall(); cur.close(); self.put_conn(conn)
        return res

    def get_all_channels(self):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("SELECT channel_id, channel_link, channel_name FROM channels")
        res = cur.fetchall(); cur.close(); self.put_conn(conn)
        return res

    def add_channel(self, cid, link, name):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("INSERT INTO channels (channel_id, channel_link, channel_name) VALUES (%s, %s, %s) ON CONFLICT (channel_id) DO UPDATE SET channel_link=EXCLUDED.channel_link", (cid, link, name))
        conn.commit(); cur.close(); self.put_conn(conn)
        return True

    def delete_channel(self, cid):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("DELETE FROM channels WHERE channel_id = %s", (cid,))
        conn.commit(); cur.close(); self.put_conn(conn)
        return True

    def get_all_users(self):
        conn = self.get_conn(); cur = conn.cursor()
        cur.execute("SELECT user_id, username, first_name FROM users LIMIT 50")
        res = cur.fetchall(); cur.close(); self.put_conn(conn)
        return res

# === تهيئة ---
db = Database()
bot = telebot.TeleBot(API_TOKEN)
user_states = {}

# === الكيبوردات ===
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
            row = subjects[i:i+2]
            kb.row(*[types.KeyboardButton(s[1]) for s in row])
        kb.row("🔄 تحديث", "🔍 بحث")
    return kb

# === التحقق من الاشتراك ===
def check_sub(uid):
    if uid == ADMIN_ID: return True, []
    channels = db.get_all_channels()
    unsubbed = []
    for cid, link, name in channels:
        try:
            status = bot.get_chat_member(cid, uid).status
            if status not in ['member', 'administrator', 'creator']: unsubbed.append((name, link))
        except: unsubbed.append((name, link))
    return len(unsubbed) == 0, unsubbed

# === المعالجات (Handlers) ===

@bot.message_handler(commands=['start'])
def start(m):
    db.add_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    ok, unsub = check_sub(m.from_user.id)
    if not ok:
        ikb = types.InlineKeyboardMarkup()
        for n, l in unsub: ikb.add(types.InlineKeyboardButton(f"اشترك في {n}", url=l))
        ikb.add(types.InlineKeyboardButton("تأكيد الاشتراك ✅", callback_data="recheck"))
        bot.send_message(m.chat.id, "يجب الاشتراك بالقنوات أولاً 👇", reply_markup=ikb)
    else:
        bot.send_message(m.chat.id, "📚 اختر المادة:", reply_markup=get_main_kb(m.from_user.id))

@bot.message_handler(func=lambda m: m.text == "📊 إحصائيات" and m.from_user.id == ADMIN_ID)
def stats(m):
    u, s, f, c = db.get_stats()
    bot.send_message(m.chat.id, f"📊 الإحصائيات:\n👥 مستخدمين: {u}\n📚 مواد: {s}\n📁 ملفات: {f}\n🔗 قنوات: {c}")

@bot.message_handler(func=lambda m: m.text == "➕ إضافة مادة" and m.from_user.id == ADMIN_ID)
def add_sub_step(m):
    user_states[m.from_user.id] = 'add_sub'
    bot.send_message(m.chat.id, "📝 أرسل اسم المادة:")

@bot.message_handler(func=lambda m: m.text == "🗑️ حذف مادة" and m.from_user.id == ADMIN_ID)
def del_sub_step(m):
    subs = db.get_all_subjects()
    ikb = types.InlineKeyboardMarkup()
    for sid, name in subs: ikb.add(types.InlineKeyboardButton(name, callback_data=f"ds_{sid}"))
    bot.send_message(m.chat.id, "🗑️ اختر المادة للحذف النهائي:", reply_markup=ikb)

@bot.message_handler(func=lambda m: m.text == "📁 رفع ملف" and m.from_user.id == ADMIN_ID)
def up_file_step(m):
    subs = db.get_all_subjects()
    ikb = types.InlineKeyboardMarkup()
    for sid, name in subs: ikb.add(types.InlineKeyboardButton(name, callback_data=f"uf_{sid}"))
    bot.send_message(m.chat.id, "📁 اختر المادة لرفع الملف إليها:", reply_markup=ikb)

@bot.message_handler(func=lambda m: m.text == "👥 المستخدمين" and m.from_user.id == ADMIN_ID)
def list_users(m):
    users = db.get_all_users()
    txt = "👥 قائمة المستخدمين:\n"
    for uid, user, name in users: txt += f"- {name} (@{user}) [{uid}]\n"
    bot.send_message(m.chat.id, txt)

@bot.message_handler(func=lambda m: m.text == "🔍 بحث")
def search_step(m):
    user_states[m.from_user.id] = 'search'
    bot.send_message(m.chat.id, "🔍 أرسل كلمة للبحث عنها:")

@bot.message_handler(func=lambda m: m.text == "🏠 الرئيسية")
def main_menu(m):
    user_states.pop(m.from_user.id, None)
    bot.send_message(m.chat.id, "🏠 العودة للرئيسية", reply_markup=get_main_kb(m.from_user.id))

# === معالجة الرسائل النصية المباشرة (إضافة، بحث، عرض مادة) ===
@bot.message_handler(func=lambda m: True)
def handle_all(m):
    uid = m.from_user.id
    state = user_states.get(uid)

    if state == 'add_sub' and uid == ADMIN_ID:
        if db.add_subject(m.text): bot.send_message(m.chat.id, "✅ تم إضافة المادة")
        else: bot.send_message(m.chat.id, "❌ موجودة مسبقاً")
        user_states.pop(uid)
    
    elif state == 'search':
        res = db.search_subjects(m.text)
        if res:
            ikb = types.InlineKeyboardMarkup()
            for sid, name in res: ikb.add(types.InlineKeyboardButton(name, callback_data=f"vs_{sid}"))
            bot.send_message(m.chat.id, "🔍 نتائج البحث:", reply_markup=ikb)
        else: bot.send_message(m.chat.id, "❌ لم يتم العثور على نتائج")
        user_states.pop(uid)
    
    else:
        # عرض ملفات المادة المختارة من الكيبورد
        subs = db.get_all_subjects()
        for sid, name in subs:
            if m.text == name:
                files = db.get_files_by_subject(sid)
                if not files: bot.send_message(m.chat.id, "📭 لا توجد ملفات حالياً")
                for fid, fname in files:
                    try: bot.send_document(m.chat.id, fid, caption=f"📄 {fname}")
                    except: pass
                return

# === معالجة الملفات المرفوعة ===
@bot.message_handler(content_types=['document'])
def handle_docs(m):
    uid = m.from_user.id
    state = user_states.get(uid, "")
    if state.startswith("wait_file_") and uid == ADMIN_ID:
        sid = state.split("_")[2]
        if db.add_file(sid, m.document.file_id, m.document.file_name):
            bot.send_message(m.chat.id, "✅ تم رفع الملف وحفظه بنجاح")
        user_states.pop(uid)

# === معالجة Callback Queries ===
@bot.callback_query_handler(func=lambda c: True)
def calls(c):
    if c.data.startswith("ds_"): # حذف مادة
        db.delete_subject(c.data.split("_")[1])
        bot.edit_message_text("✅ تم الحذف بنجاح", c.message.chat.id, c.message.message_id)
    
    elif c.data.startswith("uf_"): # رفع ملف
        sid = c.data.split("_")[1]
        user_states[c.from_user.id] = f"wait_file_{sid}"
        bot.edit_message_text("📎 أرسل الملف الآن (مستند):", c.message.chat.id, c.message.message_id)
        
    elif c.data == "recheck": # تأكيد اشتراك
        ok, _ = check_sub(c.from_user.id)
        if ok: bot.send_message(c.message.chat.id, "تم التفعيل ✅", reply_markup=get_main_kb(c.from_user.id))
        else: bot.answer_callback_query(c.id, "❌ لم تشترك بعد!")

# === التشغيل ===
if __name__ == '__main__':
    Thread(target=run_server, daemon=True).start()
    Thread(target=self_ping, daemon=True).start()
    
    logger.info("🛠️ تنظيف التعارض وبدء البوت...")
    bot.remove_webhook()
    time.sleep(1)
    
    bot.infinity_polling(skip_pending=True)
