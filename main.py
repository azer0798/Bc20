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

# === التحقق من المتغيرات ===
if not API_TOKEN:
    logger.error("❌ API_TOKEN غير موجود في ملف .env")
    exit(1)
if not DATABASE_URL:
    logger.error("❌ DATABASE_URL غير موجود في ملف .env")
    exit(1)

# === خادم الويب (Keep Alive) ===
app = Flask('')
@app.route('/')
def home(): 
    return "Bot is running!"
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
        except Exception as e:
            logger.warning(f"⚠️ فشل في ping: {e}")
        time.sleep(300)

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

    def get_conn(self): 
        return self.pool.getconn()
    
    def put_conn(self, conn): 
        self.pool.putconn(conn)

    def init_db(self):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS subjects (
                    id SERIAL PRIMARY KEY, 
                    name TEXT UNIQUE NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id SERIAL PRIMARY KEY, 
                    subject_id INTEGER REFERENCES subjects(id) ON DELETE CASCADE, 
                    file_id TEXT NOT NULL, 
                    file_name TEXT NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS channels (
                    id SERIAL PRIMARY KEY, 
                    channel_id TEXT UNIQUE NOT NULL, 
                    channel_link TEXT NOT NULL, 
                    channel_name TEXT
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY, 
                    username TEXT, 
                    first_name TEXT, 
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
        self.put_conn(conn)

    # دوال الإدارة
    def get_stats(self):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM users),
                    (SELECT COUNT(*) FROM subjects),
                    (SELECT COUNT(*) FROM files),
                    (SELECT COUNT(*) FROM channels)
            """)
            res = cur.fetchone()
        self.put_conn(conn)
        return res

    def add_user(self, uid, user, name):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, username, first_name) 
                VALUES (%s, %s, %s) 
                ON CONFLICT (user_id) DO NOTHING
            """, (uid, user, name))
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

    def add_subject(self, name):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO subjects (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (name,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"❌ خطأ في إضافة المادة: {e}")
            return False
        finally:
            self.put_conn(conn)

    def delete_subject(self, subject_id):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM subjects WHERE id = %s", (subject_id,))
                conn.commit()
                return cur.rowcount > 0
        except Exception as e:
            logger.error(f"❌ خطأ في حذف المادة: {e}")
            return False
        finally:
            self.put_conn(conn)

    def get_subject_by_name(self, name):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM subjects WHERE name = %s", (name,))
            res = cur.fetchone()
        self.put_conn(conn)
        return res

    def get_files_by_subject(self, subject_id):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT file_id, file_name FROM files WHERE subject_id = %s", (subject_id,))
            res = cur.fetchall()
        self.put_conn(conn)
        return res

    def add_file(self, subject_id, file_id, file_name):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO files (subject_id, file_id, file_name) VALUES (%s, %s, %s)", 
                          (subject_id, file_id, file_name))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"❌ خطأ في إضافة الملف: {e}")
            return False
        finally:
            self.put_conn(conn)

    def add_channel(self, channel_id, channel_link, channel_name=""):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO channels (channel_id, channel_link, channel_name) 
                    VALUES (%s, %s, %s) 
                    ON CONFLICT (channel_id) DO UPDATE 
                    SET channel_link = EXCLUDED.channel_link, 
                        channel_name = EXCLUDED.channel_name
                """, (channel_id, channel_link, channel_name))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"❌ خطأ في إضافة القناة: {e}")
            return False
        finally:
            self.put_conn(conn)

    def delete_channel(self, channel_id):
        conn = self.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM channels WHERE channel_id = %s", (channel_id,))
                conn.commit()
                return cur.rowcount > 0
        except Exception as e:
            logger.error(f"❌ خطأ في حذف القناة: {e}")
            return False
        finally:
            self.put_conn(conn)

    def get_all_users(self):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, username, first_name, joined_at FROM users ORDER BY joined_at DESC")
            res = cur.fetchall()
        self.put_conn(conn)
        return res

    def search_subjects(self, keyword):
        conn = self.get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM subjects WHERE name ILIKE %s ORDER BY name", (f'%{keyword}%',))
            res = cur.fetchall()
        self.put_conn(conn)
        return res

db = Database()
bot = telebot.TeleBot(API_TOKEN)
user_states = {}

# === التحقق من الاشتراك ===
def check_sub(uid):
    if uid == ADMIN_ID: 
        return True, []
    
    channels = db.get_all_channels()
    unsubbed = []
    
    for cid, link, name in channels:
        try:
            status = bot.get_chat_member(cid, uid).status
            if status not in ['member', 'administrator', 'creator']: 
                unsubbed.append((name or cid, link))
        except Exception as e:
            logger.warning(f"⚠️ خطأ في التحقق من القناة {cid}: {e}")
            unsubbed.append((name or cid, link))
    
    return len(unsubbed) == 0, unsubbed

# === الكيبوردات ===
def get_main_kb(uid):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    if uid == ADMIN_ID:
        kb.row("➕ إضافة مادة", "🗑️ حذف مادة")
        kb.row("📁 رفع ملف", "🔗 إضافة قناة")
        kb.row("👥 المستخدمين", "📊 إحصائيات")
        kb.row("🏠 الرئيسية", "🚫 حذف قناة")
        kb.row("🔍 بحث عن مادة")
    else:
        subjects = db.get_all_subjects()
        for i in range(0, len(subjects), 2):
            row = subjects[i:i+2]
            kb.row(*[types.KeyboardButton(name) for _, name in row])
        
        if len(subjects) % 2 == 1:
            kb.add(types.KeyboardButton(subjects[-1][1]))
        
        kb.row("🔄 تحديث", "ℹ️ مساعدة", "🔍 بحث")
    
    return kb

def get_admin_subjects_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    subjects = db.get_all_subjects()
    
    for sub_id, name in subjects:
        kb.add(types.InlineKeyboardButton(name, callback_data=f"delete_sub_{sub_id}"))
    
    kb.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_delete"))
    return kb

def get_channels_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    channels = db.get_all_channels()
    
    for cid, link, name in channels:
        display_name = name if name else cid
        kb.add(types.InlineKeyboardButton(f"🗑️ {display_name}", callback_data=f"delete_channel_{cid}"))
    
    kb.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_delete"))
    return kb

def get_subjects_kb_for_file():
    kb = types.InlineKeyboardMarkup(row_width=2)
    subjects = db.get_all_subjects()
    
    for sub_id, name in subjects:
        kb.add(types.InlineKeyboardButton(name, callback_data=f"select_sub_{sub_id}"))
    
    kb.add(types.InlineKeyboardButton("❌ إلغاء", callback_data="cancel_upload"))
    return kb

# === المعالجات الأساسية ===
@bot.message_handler(commands=['start'])
def start(m):
    db.add_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    ok, unsubbed = check_sub(m.from_user.id)
    
    if not ok:
        ikb = types.InlineKeyboardMarkup()
        for name, link in unsubbed: 
            ikb.add(types.InlineKeyboardButton(f"🔗 اشترك في {name}", url=link))
        ikb.add(types.InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data="recheck"))
        
        bot.send_message(
            m.chat.id, 
            "⚠️ يجب الاشتراك في جميع القنوات التالية لاستخدام البوت:\n\n" +
            "\n".join([f"• {name}" for name, _ in unsubbed]),
            reply_markup=ikb
        )
    else:
        welcome_msg = """
        📚 أهلاً بك في بوت المواد الدراسية!

        ✨ المميزات:
        • 📖 تصفح المواد الدراسية
        • 📥 تحميل الملفات
        • 🔍 بحث سريع
        • 📁 تنظيم الملفات حسب المواد

        اختر المادة من القائمة 👇
        """
        bot.send_message(m.chat.id, welcome_msg, reply_markup=get_main_kb(m.from_user.id))

@bot.message_handler(commands=['help'])
def help_cmd(m):
    help_text = """
    ℹ️ **مساعدة استخدام البوت**

    **للمستخدمين:**
    • اختر المادة من القائمة الرئيسية
    • استخدم زر 🔄 تحديث لتحديث القائمة
    • استخدم 🔍 بحث للبحث عن مادة محددة

    **للمشرفين:**
    • ➕ إضافة مادة: إضافة مادة جديدة
    • 🗑️ حذف مادة: حذف مادة
    • 📁 رفع ملف: إضافة ملف لمادة
    • 🔗 إضافة قناة: إضافة قناة اشتراك
    • 👥 المستخدمين: عرض المستخدمين
    • 📊 إحصائيات: إحصائيات البوت

    📞 للدعم والتواصل: @username
    """
    bot.send_message(m.chat.id, help_text)

@bot.message_handler(func=lambda m: m.text == "🔄 تحديث")
def refresh(m):
    ok, unsubbed = check_sub(m.from_user.id)
    if not ok:
        ikb = types.InlineKeyboardMarkup()
        for name, link in unsubbed: 
            ikb.add(types.InlineKeyboardButton(f"🔗 اشترك في {name}", url=link))
        ikb.add(types.InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data="recheck"))
        bot.send_message(m.chat.id, "⚠️ يجب الاشتراك في القنوات أولاً!", reply_markup=ikb)
    else:
        bot.send_message(m.chat.id, "✅ تم تحديث القائمة!", reply_markup=get_main_kb(m.from_user.id))

@bot.message_handler(func=lambda m: m.text == "ℹ️ مساعدة")
def help_btn(m):
    help_cmd(m)

@bot.message_handler(func=lambda m: m.text == "🔍 بحث" or m.text == "🔍 بحث عن مادة")
def search_subject(m):
    user_states[m.from_user.id] = {'state': 'search'}
    bot.send_message(m.chat.id, "🔍 أدخل كلمة البحث عن المادة:")

@bot.message_handler(func=lambda m: m.text == "🏠 الرئيسية")
def home_btn(m):
    user_states.pop(m.from_user.id, None)
    bot.send_message(m.chat.id, "🏠 العودة للقائمة الرئيسية", reply_markup=get_main_kb(m.from_user.id))

# === معالجات الإدارة ===
@bot.message_handler(func=lambda m: m.text == "📊 إحصائيات" and m.from_user.id == ADMIN_ID)
def stats(m):
    u, s, f, c = db.get_stats()
    stats_text = f"""
    📊 **إحصائيات البوت**
    
    👥 **المستخدمين:** {u}
    📚 **المواد:** {s}
    📁 **الملفات:** {f}
    🔗 **القنوات:** {c}
    
    📅 آخر تحديث: {time.strftime('%Y-%m-%d %H:%M:%S')}
    """
    bot.send_message(m.chat.id, stats_text)

@bot.message_handler(func=lambda m: m.text == "➕ إضافة مادة" and m.from_user.id == ADMIN_ID)
def add_subject_start(m):
    user_states[m.from_user.id] = {'state': 'add_subject'}
    bot.send_message(m.chat.id, "📝 أدخل اسم المادة الجديدة:")

@bot.message_handler(func=lambda m: m.text == "🗑️ حذف مادة" and m.from_user.id == ADMIN_ID)
def delete_subject_start(m):
    subjects = db.get_all_subjects()
    if not subjects:
        bot.send_message(m.chat.id, "❌ لا توجد مواد للحذف!")
        return
    
    bot.send_message(m.chat.id, "🗑️ اختر المادة للحذف:", reply_markup=get_admin_subjects_kb())

@bot.message_handler(func=lambda m: m.text == "📁 رفع ملف" and m.from_user.id == ADMIN_ID)
def upload_file_start(m):
    subjects = db.get_all_subjects()
    if not subjects:
        bot.send_message(m.chat.id, "❌ لا توجد مواد، أضف مادة أولاً!")
        return
    
    user_states[m.from_user.id] = {'state': 'waiting_for_file'}
    bot.send_message(m.chat.id, "📁 اختر المادة لإضافة الملف:", reply_markup=get_subjects_kb_for_file())

@bot.message_handler(func=lambda m: m.text == "🔗 إضافة قناة" and m.from_user.id == ADMIN_ID)
def add_channel_start(m):
    user_states[m.from_user.id] = {'state': 'add_channel'}
    bot.send_message(m.chat.id, """
    🔗 **إضافة قناة اشتراك**
    
    أرسل رابط القناة مع ID في السطر التالي:
    
    مثال:
    @channel_username
    https://t.me/channel_username
    
    أو:
    -1001234567890
    https://t.me/joinchat/abc123
    """)

@bot.message_handler(func=lambda m: m.text == "🚫 حذف قناة" and m.from_user.id == ADMIN_ID)
def delete_channel_start(m):
    channels = db.get_all_channels()
    if not channels:
        bot.send_message(m.chat.id, "❌ لا توجد قنوات للحذف!")
        return
    
    bot.send_message(m.chat.id, "🗑️ اختر القناة للحذف:", reply_markup=get_channels_kb())

@bot.message_handler(func=lambda m: m.text == "👥 المستخدمين" and m.from_user.id == ADMIN_ID)
def show_users(m):
    users = db.get_all_users()
    if not users:
        bot.send_message(m.chat.id, "❌ لا يوجد مستخدمين بعد!")
        return
    
    users_text = "👥 **قائمة المستخدمين**\n\n"
    for idx, (uid, username, name, joined) in enumerate(users[:50], 1):
        user_display = f"{name}" if name else f"User {uid}"
        if username:
            user_display += f" (@{username})"
        users_text += f"{idx}. {user_display} - {joined.strftime('%Y-%m-%d')}\n"
    
    if len(users) > 50:
        users_text += f"\n📋 ... وعرض {len(users)-50} مستخدم آخر"
    
    bot.send_message(m.chat.id, users_text)

# === معالجة الملفات والمواد ===
@bot.message_handler(content_types=['document'])
def handle_document(m):
    uid = m.from_user.id
    
    if uid != ADMIN_ID:
        bot.send_message(m.chat.id, "❌ هذا الأمر للمشرفين فقط!")
        return
    
    if uid in user_states and 'selected_subject' in user_states[uid]:
        sub_id = user_states[uid]['selected_subject']
        file_id = m.document.file_id
        file_name = m.document.file_name
        
        if db.add_file(sub_id, file_id, file_name):
            subject_name = db.get_subject_by_id(sub_id)[1]
            bot.send_message(m.chat.id, f"✅ تم إضافة الملف '{file_name}' إلى مادة '{subject_name}'")
        else:
            bot.send_message(m.chat.id, "❌ فشل في إضافة الملف!")
        
        user_states.pop(uid, None)
        bot.send_message(m.chat.id, "🏠 القائمة الرئيسية:", reply_markup=get_main_kb(uid))

def get_subject_by_id(self, sub_id):
    conn = self.get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM subjects WHERE id = %s", (sub_id,))
        res = cur.fetchone()
    self.put_conn(conn)
    return res

db.get_subject_by_id = get_subject_by_id

# === معالجة الرسائل النصية ===
@bot.message_handler(func=lambda m: True)
def handle_text(m):
    uid = m.from_user.id
    text = m.text
    
    # التحقق من الاشتراك أولاً
    if uid != ADMIN_ID:
        ok, unsubbed = check_sub(uid)
        if not ok and text not in ["🔄 تحديث", "ℹ️ مساعدة"]:
            ikb = types.InlineKeyboardMarkup()
            for name, link in unsubbed: 
                ikb.add(types.InlineKeyboardButton(f"🔗 اشترك في {name}", url=link))
            ikb.add(types.InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data="recheck"))
            bot.send_message(m.chat.id, "⚠️ يجب الاشتراك في القنوات أولاً!", reply_markup=ikb)
            return
    
    # حالة البحث
    if uid in user_states and user_states[uid].get('state') == 'search':
        results = db.search_subjects(text)
        if results:
            kb = types.InlineKeyboardMarkup(row_width=2)
            for sub_id, name in results[:10]:  # عرض أول 10 نتائج فقط
                kb.add(types.InlineKeyboardButton(name, callback_data=f"view_sub_{sub_id}"))
            bot.send_message(m.chat.id, f"🔍 نتائج البحث عن '{text}':", reply_markup=kb)
        else:
            bot.send_message(m.chat.id, f"❌ لم يتم العثور على مواد تحتوي على '{text}'")
        user_states.pop(uid, None)
        return
    
    # إضافة مادة
    elif uid == ADMIN_ID and uid in user_states and user_states[uid].get('state') == 'add_subject':
        if db.add_subject(text):
            bot.send_message(m.chat.id, f"✅ تم إضافة المادة '{text}' بنجاح!")
        else:
            bot.send_message(m.chat.id, "❌ فشل في إضافة المادة أو أنها موجودة بالفعل!")
        user_states.pop(uid, None)
        bot.send_message(m.chat.id, "🏠 القائمة الرئيسية:", reply_markup=get_main_kb(uid))
        return
    
    # إضافة قناة
    elif uid == ADMIN_ID and uid in user_states and user_states[uid].get('state') == 'add_channel':
        try:
            parts = text.split('\n')
            if len(parts) >= 2:
                channel_id = parts[0].strip()
                channel_link = parts[1].strip()
                channel_name = parts[2].strip() if len(parts) > 2 else ""
                
                if db.add_channel(channel_id, channel_link, channel_name):
                    bot.send_message(m.chat.id, f"✅ تم إضافة القناة بنجاح!")
                else:
                    bot.send_message(m.chat.id, "❌ فشل في إضافة القناة!")
            else:
                bot.send_message(m.chat.id, "❌ صيغة غير صحيحة! أعد المحاولة.")
        except Exception as e:
            bot.send_message(m.chat.id, f"❌ خطأ: {e}")
        
        user_states.pop(uid, None)
        bot.send_message(m.chat.id, "🏠 القائمة الرئيسية:", reply_markup=get_main_kb(uid))
        return
    
    # اختيار مادة عادية (للمستخدمين)
    if uid != ADMIN_ID:
        subject = db.get_subject_by_name(text)
        if subject:
            sub_id, sub_name = subject
            files = db.get_files_by_subject(sub_id)
            
            if not files:
                bot.send_message(m.chat.id, f"📭 لا توجد ملفات في مادة '{sub_name}' بعد!")
                return
            
            files_text = f"📚 **{sub_name}**\n\nالملفات المتاحة:\n\n"
            file_buttons = []
            
            for file_id, file_name in files[:10]:  # عرض أول 10 ملفات فقط
                files_text += f"📄 {file_name}\n"
                file_buttons.append(
                    types.InlineKeyboardButton(
                        f"📥 {file_name[:20]}...", 
                        callback_data=f"download_{file_id}"
                    )
                )
            
            if len(files) > 10:
                files_text += f"\n📋 ... وعرض {len(files)-10} ملف آخر"
            
            kb = types.InlineKeyboardMarkup(row_width=1)
            for btn in file_buttons:
                kb.add(btn)
            
            kb.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
            
            bot.send_message(m.chat.id, files_text, reply_markup=kb)

# === معالجة Callback Queries ===
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    uid = call.from_user.id
    data = call.data
    
    # تأكيد الاشتراك
    if data == "recheck":
        ok, unsubbed = check_sub(uid)
        if ok:
            bot.edit_message_text(
                "✅ تم الاشتراك في جميع القنوات!\n\nاختر من القائمة:",
                call.message.chat.id,
                call.message.message_id
            )
            bot.send_message(call.message.chat.id, "📚 القائمة الرئيسية:", reply_markup=get_main_kb(uid))
        else:
            ikb = types.InlineKeyboardMarkup()
            for name, link in unsubbed: 
                ikb.add(types.InlineKeyboardButton(f"🔗 اشترك في {name}", url=link))
            ikb.add(types.InlineKeyboardButton("✅ تأكيد الاشتراك", callback_data="recheck"))
            
            bot.edit_message_text(
                "❌ لم تشترك في جميع القنوات بعد!",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=ikb
            )
    
    # حذف مادة
    elif data.startswith("delete_sub_"):
        if uid != ADMIN_ID:
            bot.answer_callback_query(call.id, "❌ هذا الأمر للمشرفين فقط!")
            return
        
        sub_id = int(data.split("_")[2])
        if db.delete_subject(sub_id):
            bot.edit_message_text(
                "✅ تم حذف المادة بنجاح!",
                call.message.chat.id,
                call.message.message_id
            )
        else:
            bot.answer_callback_query(call.id, "❌ فشل في حذف المادة!")
    
    # حذف قناة
    elif data.startswith("delete_channel_"):
        if uid != ADMIN_ID:
            bot.answer_callback_query(call.id, "❌ هذا الأمر للمشرفين فقط!")
            return
        
        channel_id = data.split("_")[2]
        if db.delete_channel(channel_id):
            bot.edit_message_text(
                "✅ تم حذف القناة بنجاح!",
                call.message.chat.id,
                call.message.message_id
            )
        else:
            bot.answer_callback_query(call.id, "❌ فشل في حذف القناة!")
    
    # اختيار مادة لرفع ملف
    elif data.startswith("select_sub_"):
        if uid != ADMIN_ID:
            bot.answer_callback_query(call.id, "❌ هذا الأمر للمشرفين فقط!")
            return
        
        sub_id = int(data.split("_")[2])
        user_states[uid] = {'state': 'waiting_for_file', 'selected_subject': sub_id}
        subject_name = db.get_subject_by_id(sub_id)[1]
        
        bot.edit_message_text(
            f"📁 اخترت مادة '{subject_name}'\n\nأرسل الملف الآن...",
            call.message.chat.id,
            call.message.message_id
        )
    
    # تنزيل ملف
    elif data.startswith("download_"):
        file_id = data.split("_")[1]
        try:
            bot.send_document(call.message.chat.id, file_id)
            bot.answer_callback_query(call.id, "✅ تم إرسال الملف!")
        except:
            bot.answer_callback_query(call.id, "❌ فشل في إرسال الملف!")
    
    # عرض مادة
    elif data.startswith("view_sub_"):
        sub_id = int(data.split("_")[2])
        subject = db.get_subject_by_id(sub_id)
        
        if subject:
            sub_id, sub_name = subject
            files = db.get_files_by_subject(sub_id)
            
            if not files:
                bot.edit_message_text(
                    f"📭 لا توجد ملفات في مادة '{sub_name}' بعد!",
                    call.message.chat.id,
                    call.message.message_id
                )
                return
            
            files_text = f"📚 **{sub_name}**\n\nالملفات المتاحة:\n\n"
            file_buttons = []
            
            for fid, fname in files[:10]:
                files_text += f"📄 {fname}\n"
                file_buttons.append(
                    types.InlineKeyboardButton(
                        f"📥 {fname[:20]}...", 
                        callback_data=f"download_{fid}"
                    )
                )
            
            kb = types.InlineKeyboardMarkup(row_width=1)
            for btn in file_buttons:
                kb.add(btn)
            kb.add(types.InlineKeyboardButton("🏠 الرئيسية", callback_data="main_menu"))
            
            bot.edit_message_text(
                files_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=kb
            )
    
    # القائمة الرئيسية
    elif data == "main_menu":
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.send_message(call.message.chat.id, "🏠 القائمة الرئيسية:", reply_markup=get_main_kb(uid))
    
    # إلغاء العمليات
    elif data in ["cancel_delete", "cancel_upload"]:
        bot.edit_message_text(
            "❌ تم الإلغاء",
            call.message.chat.id,
            call.message.message_id
        )
        if uid in user_states:
            user_states.pop(uid)
    
    bot.answer_callback_query(call.id)

# === بدء التشغيل ===
if __name__ == '__main__':
    # تشغيل خادم الويب
    Thread(target=run_server, daemon=True).start()
    
    # تشغيل self-ping إذا كان هناك URL خارجي
    if RENDER_EXTERNAL_URL:
        Thread(target=self_ping, daemon=True).start()
    
    logger.info("🚀 تنظيف الاتصالات القديمة...")
    bot.remove_webhook()
    time.sleep(1)
    
    logger.info("✅ بدء تشغيل البوت...")
    bot.infinity_polling(skip_pending=True, timeout=60)
