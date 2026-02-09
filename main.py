#!/usr/bin/env python3
import os
import sys
import logging
import time
import threading
from flask import Flask
from threading import Thread
import requests

# === تثبيت المكتبات المطلوبة ===
def install_and_import(package, import_name=None):
    if import_name is None: import_name = package
    try:
        __import__(import_name)
    except ImportError:
        os.system(f"pip install {package}")

install_and_import("python-dotenv", "dotenv")
install_and_import("pyTelegramBotAPI", "telebot")
install_and_import("flask")
install_and_import("psycopg2-binary", "psycopg2") # مكتبة PostgreSQL

from dotenv import load_dotenv
import telebot
from telebot import types
import psycopg2
from psycopg2 import pool

load_dotenv()

# === إعدادات التسجيل ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# === إعدادات البيئة ===
API_TOKEN = os.getenv('API_TOKEN')
ADMIN_ID = int(os.getenv('ADMIN_ID')) if os.getenv('ADMIN_ID') else None
DATABASE_URL = os.getenv('DATABASE_URL')
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL')

# === خادم الويب للـ Keep Alive ===
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
            logger.info("📡 Self-Ping Successful")
        except: logger.error("❌ Self-Ping Failed")
        time.sleep(600)

# === نظام قاعدة البيانات (Supabase/PostgreSQL) ===
class Database:
    def __init__(self):
        try:
            # إنشاء تجمع اتصالات (Connection Pool) لضمان الاستقرار
            self.connection_pool = psycopg2.pool.SimpleConnectionPool(1, 10, DATABASE_URL)
            self.init_database()
            logger.info("✅ Connected to Supabase Successfully")
        except Exception as e:
            logger.error(f"❌ Database Connection Error: {e}")
            sys.exit(1)

    def get_conn(self):
        return self.connection_pool.getconn()

    def put_conn(self, conn):
        self.connection_pool.putconn(conn)

    def init_database(self):
        conn = self.get_conn()
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
                    first_name TEXT
                );
            """)
            conn.commit()
        self.put_conn(conn)

    def add_user(self, user_id, username, first_name):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO users (user_id, username, first_name) VALUES (%s, %s, %s) ON CONFLICT (user_id) DO NOTHING", (user_id, username, first_name))
            conn.commit()
        self.put_conn(conn)

    def add_subject(self, name):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO subjects (name) VALUES (%s) ON CONFLICT DO NOTHING", (name,))
                conn.commit()
            return True
        except: return False
        finally: self.put_conn(conn)

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

    def add_file(self, subject_id, file_id, file_name):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("INSERT INTO files (subject_id, file_id, file_name) VALUES (%s, %s, %s)", (subject_id, file_id, file_name))
            conn.commit()
        self.put_conn(conn)

    def get_subject_files(self, name):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT f.file_id, f.file_name FROM files f JOIN subjects s ON f.subject_id = s.id WHERE s.name = %s", (name,))
            res = cur.fetchall()
        self.put_conn(conn)
        return res

# === تشغيل البوت ===
db = Database()
bot = telebot.TeleBot(API_TOKEN)

@bot.message_handler(commands=['start'])
def start(message):
    db.add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for _, name in db.get_all_subjects(): kb.add(types.KeyboardButton(name))
    bot.send_message(message.chat.id, "مرحباً! البيانات الآن محفوظة للأبد على Supabase.", reply_markup=kb)

# ... (بقية الـ Handlers كما في النسخة السابقة) ...

if __name__ == '__main__':
    Thread(target=run_server, daemon=True).start()
    Thread(target=self_ping, daemon=True).start()
    print("🚀 Bot is Polling with Supabase Persistence...")
    bot.infinity_polling()
