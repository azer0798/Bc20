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

# === Logging ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === ENV ===
API_TOKEN = os.getenv('API_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID', 0))
DATABASE_URL = os.getenv('DATABASE_URL')
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL')

# === Flask Ping ===
app = Flask('')
@app.route('/')
def home():
    return "Bot Alive"

def run_server():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

def self_ping():
    if not RENDER_EXTERNAL_URL:
        return
    while True:
        try:
            requests.get(RENDER_EXTERNAL_URL, timeout=10)
        except:
            pass
        time.sleep(300)

# === Database ===
class Database:
    def __init__(self):
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        self.pool = pool.SimpleConnectionPool(1, 15, url)
        self.init_db()

    def conn(self): return self.pool.getconn()
    def close(self, c): self.pool.putconn(c)

    def init_db(self):
        c = self.conn(); cur = c.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS subjects (id SERIAL PRIMARY KEY, name TEXT UNIQUE)")
        cur.execute("CREATE TABLE IF NOT EXISTS files (id SERIAL PRIMARY KEY, subject_id INT REFERENCES subjects(id) ON DELETE CASCADE, file_id TEXT, file_name TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS channels (id SERIAL PRIMARY KEY, channel_id TEXT UNIQUE, channel_link TEXT, channel_name TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS users (user_id BIGINT PRIMARY KEY, username TEXT, first_name TEXT)")
        c.commit(); cur.close(); self.close(c)

    # === Subjects ===
    def get_all_subjects(self):
        c=self.conn();cur=c.cursor()
        cur.execute("SELECT id,name FROM subjects ORDER BY name")
        r=cur.fetchall();cur.close();self.close(c);return r

    def add_subject(self,name):
        c=self.conn();cur=c.cursor()
        try:
            cur.execute("INSERT INTO subjects(name) VALUES(%s)",(name,))
            c.commit();return True
        except:
            return False
        finally:
            cur.close();self.close(c)

    def delete_subject(self,sid):
        c=self.conn();cur=c.cursor()
        cur.execute("DELETE FROM subjects WHERE id=%s",(sid,))
        c.commit();cur.close();self.close(c)

    # === Files ===
    def add_file(self,sid,fid,fname):
        c=self.conn();cur=c.cursor()
        cur.execute("INSERT INTO files(subject_id,file_id,file_name) VALUES(%s,%s,%s)",(sid,fid,fname))
        c.commit();cur.close();self.close(c)

    def get_files(self,sid):
        c=self.conn();cur=c.cursor()
        cur.execute("SELECT file_id,file_name FROM files WHERE subject_id=%s",(sid,))
        r=cur.fetchall();cur.close();self.close(c);return r

    # === Users ===
    def add_user(self,uid,u,n):
        c=self.conn();cur=c.cursor()
        cur.execute("INSERT INTO users VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",(uid,u,n))
        c.commit();cur.close();self.close(c)

    # === Channels ===
    def get_all_channels(self):
        c=self.conn();cur=c.cursor()
        cur.execute("SELECT channel_id,channel_link,channel_name FROM channels")
        r=cur.fetchall();cur.close();self.close(c);return r

    def add_channel(self,cid,link,name):
        c=self.conn();cur=c.cursor()
        cur.execute(
            "INSERT INTO channels(channel_id,channel_link,channel_name) VALUES(%s,%s,%s) "
            "ON CONFLICT(channel_id) DO UPDATE SET channel_link=EXCLUDED.channel_link",
            (cid,link,name)
        )
        c.commit();cur.close();self.close(c)

    def delete_channel(self,cid):
        c=self.conn();cur=c.cursor()
        cur.execute("DELETE FROM channels WHERE channel_id=%s",(cid,))
        c.commit();cur.close();self.close(c)

db = Database()
bot = telebot.TeleBot(API_TOKEN)
states = {}

# === Keyboard ===
def main_kb(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if uid == ADMIN_ID:
        kb.row("➕ إضافة مادة","🗑️ حذف مادة")
        kb.row("📁 رفع ملف","🔗 إضافة قناة")
        kb.row("📊 إحصائيات","👥 المستخدمين")
        kb.row("🏠 الرئيسية","🚫 حذف قناة")
    else:
        for _,n in db.get_all_subjects():
            kb.add(n)
    return kb

# === Start ===
@bot.message_handler(commands=['start'])
def start(m):
    db.add_user(m.from_user.id,m.from_user.username,m.from_user.first_name)
    bot.send_message(m.chat.id,"📚 اختر:",reply_markup=main_kb(m.from_user.id))

# === Admin Buttons ===
@bot.message_handler(func=lambda m:m.text=="➕ إضافة مادة" and m.from_user.id==ADMIN_ID)
def add_sub(m):
    states[m.from_user.id]="add_sub"
    bot.send_message(m.chat.id,"📝 أرسل اسم المادة")

@bot.message_handler(func=lambda m:m.text=="🗑️ حذف مادة" and m.from_user.id==ADMIN_ID)
def del_sub(m):
    ikb=types.InlineKeyboardMarkup()
    for sid,n in db.get_all_subjects():
        ikb.add(types.InlineKeyboardButton(n,callback_data=f"ds_{sid}"))
    bot.send_message(m.chat.id,"🗑️ اختر مادة للحذف",reply_markup=ikb)

@bot.message_handler(func=lambda m:m.text=="📁 رفع ملف" and m.from_user.id==ADMIN_ID)
def up_file(m):
    ikb=types.InlineKeyboardMarkup()
    for sid,n in db.get_all_subjects():
        ikb.add(types.InlineKeyboardButton(n,callback_data=f"uf_{sid}"))
    bot.send_message(m.chat.id,"📁 اختر مادة",reply_markup=ikb)

@bot.message_handler(func=lambda m:m.text=="🔗 إضافة قناة" and m.from_user.id==ADMIN_ID)
def add_channel(m):
    states[m.from_user.id]="add_channel"
    bot.send_message(
        m.chat.id,
        "🔗 أرسل القناة بهذا الشكل:\n\n"
        "channel_id | channel_link | channel_name\n\n"
        "مثال:\n-1001234567890 | https://t.me/example | قناة مثال"
    )

@bot.message_handler(func=lambda m:m.text=="🚫 حذف قناة" and m.from_user.id==ADMIN_ID)
def del_channel(m):
    ikb=types.InlineKeyboardMarkup()
    for cid,_,name in db.get_all_channels():
        ikb.add(types.InlineKeyboardButton(name or cid,callback_data=f"dc_{cid}"))
    bot.send_message(m.chat.id,"🚫 اختر قناة للحذف",reply_markup=ikb)

@bot.message_handler(func=lambda m:m.text=="🏠 الرئيسية")
def home_btn(m):
    states.clear()
    bot.send_message(m.chat.id,"🏠 الرئيسية",reply_markup=main_kb(m.from_user.id))

# === Text Handler ===
@bot.message_handler(func=lambda m:True)
def text(m):
    uid=m.from_user.id
    st=states.get(uid)

    if st=="add_sub":
        db.add_subject(m.text)
        states.pop(uid)
        bot.send_message(m.chat.id,"✅ تمت الإضافة",reply_markup=main_kb(uid))

    elif st=="add_channel":
        try:
            cid,link,name=[x.strip() for x in m.text.split("|",2)]
            db.add_channel(cid,link,name)
            bot.send_message(m.chat.id,"✅ تم إضافة القناة")
        except:
            bot.send_message(m.chat.id,"❌ الصيغة غير صحيحة")
        states.pop(uid)

    else:
        for sid,n in db.get_all_subjects():
            if m.text==n:
                files=db.get_files(sid)
                if not files:
                    bot.send_message(m.chat.id,"📭 لا توجد ملفات")
                for fid,fname in files:
                    bot.send_document(m.chat.id,fid,caption=fname)

# === Documents ===
@bot.message_handler(content_types=['document'])
def docs(m):
    st=states.get(m.from_user.id,"")
    if st.startswith("file_"):
        sid=st.split("_")[1]
        db.add_file(sid,m.document.file_id,m.document.file_name)
        states.pop(m.from_user.id)
        bot.send_message(m.chat.id,"✅ تم رفع الملف")

# === Callbacks ===
@bot.callback_query_handler(func=lambda c:True)
def cb(c):
    if c.data.startswith("ds_"):
        db.delete_subject(c.data.split("_")[1])
        bot.edit_message_text("✅ تم حذف المادة",c.message.chat.id,c.message.message_id)

    elif c.data.startswith("uf_"):
        states[c.from_user.id]=f"file_{c.data.split('_')[1]}"
        bot.edit_message_text("📎 أرسل الملف الآن",c.message.chat.id,c.message.message_id)

    elif c.data.startswith("dc_"):
        db.delete_channel(c.data.split("_",1)[1])
        bot.edit_message_text("✅ تم حذف القناة",c.message.chat.id,c.message.message_id)

# === Run ===
if __name__=="__main__":
    Thread(target=run_server,daemon=True).start()
    Thread(target=self_ping,daemon=True).start()
    bot.infinity_polling(skip_pending=True)
