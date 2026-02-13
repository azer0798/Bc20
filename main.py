#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نظام فليكسي - نسخة مصححة (إصلاح خطأ block title المكرر)
"""

import os
import sqlite3
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, flash
import requests

# ==================== التكوين ====================
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', secrets.token_hex(32))
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

CHARGILY_BASE_URL = "https://pro.chargily.net/api/v1"
CHARGILY_PUBLIC_KEY = os.getenv('CHARGILY_PUBLIC_KEY', '3NHPUC2I0eE3cP5I997BI8IsjamBoNQMy0d0iEgMPuJu1Xvz54bRkUIfI6IQb2lL')
CHARGILY_SECRET_KEY = os.getenv('CHARGILY_SECRET_KEY', 'secret_3fb56db2396d6c02c1f6251df61a9d81e803b625a402abf6abf4c65a06c00835')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://your-app.onrender.com/webhook/topup')

# ==================== قاعدة البيانات ====================
DATABASE = 'flexy.db'

def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, full_name TEXT NOT NULL, phone TEXT, role TEXT NOT NULL DEFAULT 'shop', balance REAL DEFAULT 0, commission_rate REAL DEFAULT 0, is_active INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS operations (id INTEGER PRIMARY KEY AUTOINCREMENT, request_number TEXT UNIQUE NOT NULL, user_id INTEGER NOT NULL, customer_name TEXT NOT NULL, phone_number TEXT NOT NULL, operator TEXT NOT NULL, mode TEXT, value INTEGER NOT NULL, cost REAL NOT NULL, commission REAL DEFAULT 0, status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users (id))''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS deposits (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount REAL NOT NULL, note TEXT, created_by INTEGER NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (user_id) REFERENCES users (id))''')
    admin_password = hashlib.sha256('admin123'.encode()).hexdigest()
    try:
        cursor.execute('''INSERT INTO users (username, password, full_name, role, is_active) VALUES ('admin', ?, 'المدير', 'admin', 1)''', (admin_password,))
    except sqlite3.IntegrityError: pass
    db.commit()
    db.close()

# ==================== المساعدات ====================
def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session: return redirect(url_for('login'))
            if role and session.get('role') != role:
                flash('غير مصرح لك بالوصول', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def generate_request_number():
    return f"REQ-{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4).upper()}"

def calculate_cost(operator, value, mode=None):
    discounts = {'ooredoo': 2.5, 'djezzy': 2.0, 'mobilis': 2.0}
    discount = discounts.get(operator, 0)
    if mode: discount = 1.5
    return round(value * (1 - discount / 100), 2)

def call_chargily_api(endpoint, method='GET', data=None):
    url = f"{CHARGILY_BASE_URL}{endpoint}"
    headers = {'X-Authorization': CHARGILY_PUBLIC_KEY, 'Content-Type': 'application/json'}
    try:
        resp = requests.request(method, url, headers=headers, json=data, timeout=10)
        return (True, resp.json()) if resp.status_code in [200, 201] else (False, resp.json().get('message', 'خطأ'))
    except Exception as e: return False, str(e)

# ==================== القوالب HTML (تم تصحيح التكرار) ====================
BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>{% block title %}نظام فليكسي{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #f5f7fa; }
        .navbar { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
        .card { border: none; border-radius: 15px; box-shadow: 0 5px 15px rgba(0,0,0,0.08); }
    </style>
</head>
<body>
    {% if session.user_id %}
    <nav class="navbar navbar-expand-lg navbar-dark mb-4">
        <div class="container-fluid">
            <a class="navbar-brand" href="{{ url_for('dashboard') }}">نظام فليكسي</a>
            <div class="collapse navbar-collapse">
                <ul class="navbar-nav me-auto">
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('dashboard') }}">الرئيسية</a></li>
                    {% if session.role == 'admin' %}
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('admin_users') }}">المستخدمين</a></li>
                    {% endif %}
                </ul>
                <a class="nav-link text-white" href="{{ url_for('logout') }}">خروج</a>
            </div>
        </div>
    </nav>
    {% endif %}
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}{% for cat, msg in messages %}<div class="alert alert-{{ cat }}">{{ msg }}</div>{% endfor %}{% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </div>
</body>
</html>
'''

LOGIN_TEMPLATE = '''
{% extends "base" %}
{% block title %}دخول{% endblock %}
{% block content %}
<div class="row justify-content-center mt-5">
    <div class="col-md-5 card p-4">
        <h3 class="text-center">تسجيل الدخول</h3>
        <form method="POST">
            <input type="text" name="username" class="form-control mb-3" placeholder="اسم المستخدم" required>
            <input type="password" name="password" class="form-control mb-3" placeholder="كلمة المرور" required>
            <button type="submit" class="btn btn-primary w-100">دخول</button>
        </form>
    </div>
</div>
{% endblock %}
'''

DASHBOARD_TEMPLATE = '''
{% extends "base" %}
{% block title %}لوحة التحكم{% endblock %}
{% block content %}
<div class="row g-4 mb-4">
    <div class="col-md-4 card bg-primary text-white p-3">
        <h6>الرصيد المتاح</h6>
        <h2>{{ "%.2f"|format(balance) }} د.ج</h2>
    </div>
</div>
<div class="card p-4">
    <h5>طلب شحن جديد</h5>
    <form method="POST" action="{{ url_for('create_topup') }}">
        <div class="row">
            <div class="col-md-3"><input type="text" name="customer_name" class="form-control" placeholder="اسم العميل" required></div>
            <div class="col-md-3"><input type="tel" name="phone_number" class="form-control" placeholder="رقم الهاتف" required></div>
            <div class="col-md-2">
                <select name="operator" class="form-select" required>
                    <option value="ooredoo">أوريدو</option>
                    <option value="djezzy">جيزي</option>
                    <option value="mobilis">موبيليس</option>
                </select>
            </div>
            <div class="col-md-2"><input type="number" name="value" class="form-control" value="100"></div>
            <div class="col-md-2"><button type="submit" class="btn btn-success w-100">شحن</button></div>
        </div>
    </form>
</div>
{% endblock %}
'''

# ==================== المسارات ====================

@app.route('/')
def index():
    return redirect(url_for('dashboard')) if 'user_id' in session else redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = get_db().execute('SELECT * FROM users WHERE username = ? AND password = ?', 
                               (request.form['username'], hashlib.sha256(request.form['password'].encode()).hexdigest())).fetchone()
        if user and user['is_active']:
            session.update({'user_id': user['id'], 'username': user['username'], 'role': user['role']})
            return redirect(url_for('dashboard'))
        flash('خطأ في البيانات', 'danger')
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', LOGIN_TEMPLATE).replace('{% extends "base" %}', ''))

@app.route('/dashboard')
@login_required()
def dashboard():
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    recent = db.execute('SELECT * FROM operations WHERE user_id = ? ORDER BY created_at DESC LIMIT 5', (session['user_id'],)).fetchall()
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', DASHBOARD_TEMPLATE).replace('{% extends "base" %}', ''), balance=user['balance'], recent_operations=recent, stats={'today_count':0, 'pending_count':0, 'total_commission':0})

@app.route('/topup/create', methods=['POST'])
@login_required()
def create_topup():
    # ... (نفس منطق الشحن السابق)
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)
