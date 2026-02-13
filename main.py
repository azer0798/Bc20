#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
نظام فليكسي - شحن رصيد الهواتف
Flask Application for Chargily API Integration
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

# إعدادات Chargily API
CHARGILY_BASE_URL = "https://pro.chargily.net/api/v1"
CHARGILY_PUBLIC_KEY = os.getenv('CHARGILY_PUBLIC_KEY', '3NHPUC2I0eE3cP5I997BI8IsjamBoNQMy0d0iEgMPuJu1Xvz54bRkUIfI6IQb2lL')
CHARGILY_SECRET_KEY = os.getenv('CHARGILY_SECRET_KEY', 'secret_3fb56db2396d6c02c1f6251df61a9d81e803b625a402abf6abf4c65a06c00835')
WEBHOOK_URL = os.getenv('WEBHOOK_URL', 'https://your-app.onrender.com/webhook/topup')

# ==================== قاعدة البيانات ====================
DATABASE = 'flexy.db'

def get_db():
    """الاتصال بقاعدة البيانات"""
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    """إنشاء جداول قاعدة البيانات"""
    db = get_db()
    cursor = db.cursor()
    
    # جدول المستخدمين
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT,
            role TEXT NOT NULL DEFAULT 'shop',
            balance REAL DEFAULT 0,
            commission_rate REAL DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # جدول العمليات
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS operations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_number TEXT UNIQUE NOT NULL,
            user_id INTEGER NOT NULL,
            customer_name TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            operator TEXT NOT NULL,
            mode TEXT,
            value INTEGER NOT NULL,
            cost REAL NOT NULL,
            commission REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # جدول الودائع
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            created_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # إنشاء حساب الإدمن الافتراضي
    admin_password = hashlib.sha256('admin123'.encode()).hexdigest()
    try:
        cursor.execute('''
            INSERT INTO users (username, password, full_name, role, is_active)
            VALUES ('admin', ?, 'المدير', 'admin', 1)
        ''', (admin_password,))
    except sqlite3.IntegrityError:
        pass  # الإدمن موجود مسبقاً
    
    db.commit()
    db.close()

# ==================== المساعدات ====================
def login_required(role=None):
    """تأكيد تسجيل الدخول"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if role and session.get('role') != role:
                flash('غير مصرح لك بالوصول', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def generate_request_number():
    """توليد رقم طلب فريد"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random = secrets.token_hex(4).upper()
    return f"REQ-{timestamp}-{random}"

def calculate_cost(operator, value, mode=None):
    """حساب التكلفة مع الخصم"""
    # نسب الخصم من API (يمكن جلبها من قاعدة البيانات)
    discounts = {
        'ooredoo': 2.5,
        'djezzy': 2.0,
        'mobilis': 2.0
    }
    
    discount = discounts.get(operator, 0)
    if mode:
        discount = 1.5  # خصم الباقات
    
    cost = value * (1 - discount / 100)
    return round(cost, 2)

def call_chargily_api(endpoint, method='GET', data=None):
    """استدعاء Chargily API"""
    url = f"{CHARGILY_BASE_URL}{endpoint}"
    headers = {
        'X-Authorization': CHARGILY_PUBLIC_KEY,
        'Content-Type': 'application/json'
    }
    
    try:
        if method == 'GET':
            response = requests.get(url, headers=headers, timeout=10)
        elif method == 'POST':
            response = requests.post(url, headers=headers, json=data, timeout=10)
        
        if response.status_code in [200, 201]:
            return True, response.json()
        else:
            error_msg = response.json().get('message', 'خطأ غير معروف')
            return False, error_msg
    except Exception as e:
        return False, str(e)

# ==================== القوالب HTML ====================
BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}نظام فليكسي{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css">
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #f5f7fa; }
        .navbar { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
        .card { border: none; border-radius: 15px; box-shadow: 0 5px 15px rgba(0,0,0,0.08); }
        .btn-primary { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border: none; }
        .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4); }
        .stat-card { transition: all 0.3s ease; }
        .stat-card:hover { transform: translateY(-5px); box-shadow: 0 10px 25px rgba(0,0,0,0.1); }
        .table { border-radius: 10px; overflow: hidden; }
        .badge { padding: 8px 15px; border-radius: 20px; }
    </style>
</head>
<body>
    {% if session.user_id %}
    <nav class="navbar navbar-expand-lg navbar-dark mb-4">
        <div class="container-fluid">
            <a class="navbar-brand" href="{{ url_for('dashboard') }}">
                <i class="bi bi-lightning-charge-fill"></i> نظام فليكسي
            </a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav me-auto">
                    <li class="nav-item">
                        <a class="nav-link" href="{{ url_for('dashboard') }}">
                            <i class="bi bi-speedometer2"></i> الرئيسية
                        </a>
                    </li>
                    {% if session.role == 'admin' %}
                    <li class="nav-item">
                        <a class="nav-link" href="{{ url_for('admin_users') }}">
                            <i class="bi bi-people"></i> المستخدمين
                        </a>
                    </li>
                    {% endif %}
                    <li class="nav-item">
                        <a class="nav-link" href="{{ url_for('operations') }}">
                            <i class="bi bi-clock-history"></i> العمليات
                        </a>
                    </li>
                </ul>
                <ul class="navbar-nav">
                    <li class="nav-item">
                        <span class="navbar-text text-white me-3">
                            <i class="bi bi-person-circle"></i> {{ session.username }}
                        </span>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="{{ url_for('logout') }}">
                            <i class="bi bi-box-arrow-right"></i> خروج
                        </a>
                    </li>
                </ul>
            </div>
        </div>
    </nav>
    {% endif %}

    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
        {% for category, message in messages %}
        <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
            {{ message }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
        {% endif %}
        {% endwith %}

        {% block content %}{% endblock %}
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
'''

LOGIN_TEMPLATE = '''
{% extends "base.html" %}
{% block title %}تسجيل الدخول - نظام فليكسي{% endblock %}
{% block content %}
<div class="row justify-content-center mt-5">
    <div class="col-md-5">
        <div class="card">
            <div class="card-body p-5">
                <div class="text-center mb-4">
                    <i class="bi bi-lightning-charge-fill" style="font-size: 4rem; color: #667eea;"></i>
                    <h3 class="mt-3">نظام فليكسي</h3>
                    <p class="text-muted">شحن رصيد الهواتف</p>
                </div>
                <form method="POST">
                    <div class="mb-3">
                        <label class="form-label">اسم المستخدم</label>
                        <input type="text" name="username" class="form-control" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">كلمة المرور</label>
                        <input type="password" name="password" class="form-control" required>
                    </div>
                    <button type="submit" class="btn btn-primary w-100">
                        <i class="bi bi-box-arrow-in-right"></i> دخول
                    </button>
                </form>
                <div class="text-center mt-3">
                    <small class="text-muted">
                        الحساب الافتراضي: admin / admin123
                    </small>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
'''

DASHBOARD_TEMPLATE = '''
{% extends "base.html" %}
{% block title %}لوحة التحكم{% endblock %}
{% block content %}
<h2 class="mb-4">
    <i class="bi bi-speedometer2"></i> لوحة التحكم
</h2>

<!-- إحصائيات -->
<div class="row g-4 mb-4">
    <div class="col-md-3">
        <div class="card stat-card bg-primary text-white">
            <div class="card-body">
                <h6>الرصيد المتاح</h6>
                <h2>{{ "%.2f"|format(balance) }} د.ج</h2>
                <i class="bi bi-wallet2 position-absolute" style="font-size: 3rem; opacity: 0.2; left: 20px; top: 20px;"></i>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card stat-card bg-success text-white">
            <div class="card-body">
                <h6>عمليات اليوم</h6>
                <h2>{{ stats.today_count }}</h2>
                <i class="bi bi-graph-up position-absolute" style="font-size: 3rem; opacity: 0.2; left: 20px; top: 20px;"></i>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card stat-card bg-warning text-white">
            <div class="card-body">
                <h6>قيد الانتظار</h6>
                <h2>{{ stats.pending_count }}</h2>
                <i class="bi bi-clock-history position-absolute" style="font-size: 3rem; opacity: 0.2; left: 20px; top: 20px;"></i>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card stat-card bg-info text-white">
            <div class="card-body">
                <h6>العمولة المكتسبة</h6>
                <h2>{{ "%.2f"|format(stats.total_commission) }} د.ج</h2>
                <i class="bi bi-trophy position-absolute" style="font-size: 3rem; opacity: 0.2; left: 20px; top: 20px;"></i>
            </div>
        </div>
    </div>
</div>

<!-- نموذج شحن جديد -->
<div class="card mb-4">
    <div class="card-header bg-gradient text-white" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
        <h5 class="mb-0"><i class="bi bi-plus-circle"></i> طلب شحن جديد</h5>
    </div>
    <div class="card-body">
        <form method="POST" action="{{ url_for('create_topup') }}" id="topupForm">
            <div class="row g-3">
                <div class="col-md-4">
                    <label class="form-label">اسم العميل</label>
                    <input type="text" name="customer_name" class="form-control" required>
                </div>
                <div class="col-md-4">
                    <label class="form-label">رقم الهاتف</label>
                    <input type="tel" name="phone_number" class="form-control" placeholder="555123456" required>
                </div>
                <div class="col-md-4">
                    <label class="form-label">المتعامل</label>
                    <select name="operator" class="form-select" id="operatorSelect" required>
                        <option value="">اختر المتعامل</option>
                        <option value="ooredoo">أوريدو (Ooredoo)</option>
                        <option value="djezzy">جيزي (Djezzy)</option>
                        <option value="mobilis">موبيليس (Mobilis)</option>
                    </select>
                </div>
                <div class="col-md-4">
                    <label class="form-label">القيمة (دج)</label>
                    <input type="number" name="value" class="form-control" min="10" max="5000" value="100" id="valueInput" required>
                </div>
                <div class="col-md-4">
                    <label class="form-label">الباقة (اختياري)</label>
                    <select name="mode" class="form-select">
                        <option value="">شحن عادي</option>
                        <option value="normal">عادي</option>
                        <option value="flexy">فليكسي</option>
                    </select>
                </div>
                <div class="col-md-4">
                    <label class="form-label">التكلفة التقديرية</label>
                    <input type="text" class="form-control" id="costDisplay" readonly value="0.00 د.ج">
                </div>
            </div>
            <div class="mt-3">
                <button type="submit" class="btn btn-primary btn-lg">
                    <i class="bi bi-lightning-charge"></i> تنفيذ الشحن
                </button>
            </div>
        </form>
    </div>
</div>

<!-- آخر العمليات -->
<div class="card">
    <div class="card-header">
        <h5 class="mb-0"><i class="bi bi-list-check"></i> آخر العمليات</h5>
    </div>
    <div class="card-body">
        <div class="table-responsive">
            <table class="table table-hover">
                <thead>
                    <tr>
                        <th>رقم الطلب</th>
                        <th>العميل</th>
                        <th>الهاتف</th>
                        <th>المتعامل</th>
                        <th>القيمة</th>
                        <th>الحالة</th>
                        <th>التاريخ</th>
                    </tr>
                </thead>
                <tbody>
                    {% for op in recent_operations %}
                    <tr>
                        <td><code>{{ op.request_number }}</code></td>
                        <td>{{ op.customer_name }}</td>
                        <td>{{ op.phone_number }}</td>
                        <td>
                            {% if op.operator == 'ooredoo' %}
                            <span class="badge bg-danger">أوريدو</span>
                            {% elif op.operator == 'djezzy' %}
                            <span class="badge bg-warning">جيزي</span>
                            {% else %}
                            <span class="badge bg-info">موبيليس</span>
                            {% endif %}
                        </td>
                        <td>{{ op.value }} د.ج</td>
                        <td>
                            {% if op.status == 'sent' %}
                            <span class="badge bg-success">تم</span>
                            {% elif op.status == 'pending' %}
                            <span class="badge bg-warning">قيد الانتظار</span>
                            {% elif op.status == 'failed' %}
                            <span class="badge bg-danger">فشل</span>
                            {% else %}
                            <span class="badge bg-secondary">{{ op.status }}</span>
                            {% endif %}
                        </td>
                        <td>{{ op.created_at[:16] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
// حساب التكلفة التقديرية
document.addEventListener('DOMContentLoaded', function() {
    const operatorSelect = document.getElementById('operatorSelect');
    const valueInput = document.getElementById('valueInput');
    const costDisplay = document.getElementById('costDisplay');
    
    function calculateCost() {
        const operator = operatorSelect.value;
        const value = parseFloat(valueInput.value) || 0;
        
        const discounts = {
            'ooredoo': 2.5,
            'djezzy': 2.0,
            'mobilis': 2.0
        };
        
        const discount = discounts[operator] || 0;
        const cost = value * (1 - discount / 100);
        costDisplay.value = cost.toFixed(2) + ' د.ج';
    }
    
    operatorSelect.addEventListener('change', calculateCost);
    valueInput.addEventListener('input', calculateCost);
});
</script>
{% endblock %}
'''

ADMIN_USERS_TEMPLATE = '''
{% extends "base.html" %}
{% block title %}إدارة المستخدمين{% endblock %}
{% block content %}
<h2 class="mb-4">
    <i class="bi bi-people"></i> إدارة المستخدمين
</h2>

<!-- إضافة مستخدم جديد -->
<div class="card mb-4">
    <div class="card-header bg-primary text-white">
        <h5 class="mb-0"><i class="bi bi-person-plus"></i> إضافة مستخدم جديد</h5>
    </div>
    <div class="card-body">
        <form method="POST" action="{{ url_for('admin_add_user') }}">
            <div class="row g-3">
                <div class="col-md-3">
                    <label class="form-label">اسم المستخدم</label>
                    <input type="text" name="username" class="form-control" required>
                </div>
                <div class="col-md-3">
                    <label class="form-label">كلمة المرور</label>
                    <input type="password" name="password" class="form-control" required>
                </div>
                <div class="col-md-3">
                    <label class="form-label">الاسم الكامل</label>
                    <input type="text" name="full_name" class="form-control" required>
                </div>
                <div class="col-md-3">
                    <label class="form-label">رقم الهاتف</label>
                    <input type="tel" name="phone" class="form-control">
                </div>
                <div class="col-md-4">
                    <label class="form-label">نسبة العمولة (%)</label>
                    <input type="number" name="commission_rate" class="form-control" step="0.1" value="0" required>
                </div>
                <div class="col-md-4">
                    <label class="form-label">الرصيد الابتدائي (د.ج)</label>
                    <input type="number" name="initial_balance" class="form-control" step="0.01" value="0" required>
                </div>
                <div class="col-md-4">
                    <label class="form-label">&nbsp;</label>
                    <button type="submit" class="btn btn-primary w-100">
                        <i class="bi bi-plus-circle"></i> إضافة
                    </button>
                </div>
            </div>
        </form>
    </div>
</div>

<!-- قائمة المستخدمين -->
<div class="card">
    <div class="card-header">
        <h5 class="mb-0"><i class="bi bi-list"></i> المستخدمين المسجلين</h5>
    </div>
    <div class="card-body">
        <div class="table-responsive">
            <table class="table table-hover">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>اسم المستخدم</th>
                        <th>الاسم الكامل</th>
                        <th>الهاتف</th>
                        <th>الرصيد</th>
                        <th>العمولة %</th>
                        <th>الحالة</th>
                        <th>إجراءات</th>
                    </tr>
                </thead>
                <tbody>
                    {% for user in users %}
                    <tr>
                        <td>{{ user.id }}</td>
                        <td>
                            {% if user.role == 'admin' %}
                            <span class="badge bg-danger">{{ user.username }}</span>
                            {% else %}
                            {{ user.username }}
                            {% endif %}
                        </td>
                        <td>{{ user.full_name }}</td>
                        <td>{{ user.phone or '-' }}</td>
                        <td><strong>{{ "%.2f"|format(user.balance) }} د.ج</strong></td>
                        <td>{{ user.commission_rate }}%</td>
                        <td>
                            {% if user.is_active %}
                            <span class="badge bg-success">نشط</span>
                            {% else %}
                            <span class="badge bg-secondary">معطل</span>
                            {% endif %}
                        </td>
                        <td>
                            {% if user.role != 'admin' %}
                            <button class="btn btn-sm btn-success" data-bs-toggle="modal" data-bs-target="#addBalanceModal{{ user.id }}">
                                <i class="bi bi-cash-coin"></i> رصيد
                            </button>
                            <button class="btn btn-sm btn-warning" data-bs-toggle="modal" data-bs-target="#editUserModal{{ user.id }}">
                                <i class="bi bi-pencil"></i>
                            </button>
                            {% endif %}
                        </td>
                    </tr>

                    <!-- Modal إضافة رصيد -->
                    <div class="modal fade" id="addBalanceModal{{ user.id }}" tabindex="-1">
                        <div class="modal-dialog">
                            <div class="modal-content">
                                <div class="modal-header">
                                    <h5 class="modal-title">إضافة رصيد - {{ user.full_name }}</h5>
                                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                                </div>
                                <form method="POST" action="{{ url_for('admin_add_balance', user_id=user.id) }}">
                                    <div class="modal-body">
                                        <div class="mb-3">
                                            <label class="form-label">المبلغ (د.ج)</label>
                                            <input type="number" name="amount" class="form-control" step="0.01" required>
                                        </div>
                                        <div class="mb-3">
                                            <label class="form-label">ملاحظة</label>
                                            <textarea name="note" class="form-control" rows="2"></textarea>
                                        </div>
                                    </div>
                                    <div class="modal-footer">
                                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">إلغاء</button>
                                        <button type="submit" class="btn btn-success">إضافة الرصيد</button>
                                    </div>
                                </form>
                            </div>
                        </div>
                    </div>

                    <!-- Modal تعديل مستخدم -->
                    <div class="modal fade" id="editUserModal{{ user.id }}" tabindex="-1">
                        <div class="modal-dialog">
                            <div class="modal-content">
                                <div class="modal-header">
                                    <h5 class="modal-title">تعديل - {{ user.full_name }}</h5>
                                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                                </div>
                                <form method="POST" action="{{ url_for('admin_edit_user', user_id=user.id) }}">
                                    <div class="modal-body">
                                        <div class="mb-3">
                                            <label class="form-label">الاسم الكامل</label>
                                            <input type="text" name="full_name" class="form-control" value="{{ user.full_name }}" required>
                                        </div>
                                        <div class="mb-3">
                                            <label class="form-label">نسبة العمولة (%)</label>
                                            <input type="number" name="commission_rate" class="form-control" step="0.1" value="{{ user.commission_rate }}" required>
                                        </div>
                                        <div class="mb-3">
                                            <label class="form-label">الحالة</label>
                                            <select name="is_active" class="form-select">
                                                <option value="1" {% if user.is_active %}selected{% endif %}>نشط</option>
                                                <option value="0" {% if not user.is_active %}selected{% endif %}>معطل</option>
                                            </select>
                                        </div>
                                    </div>
                                    <div class="modal-footer">
                                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">إلغاء</button>
                                        <button type="submit" class="btn btn-primary">حفظ التعديلات</button>
                                    </div>
                                </form>
                            </div>
                        </div>
                    </div>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endblock %}
'''

OPERATIONS_TEMPLATE = '''
{% extends "base.html" %}
{% block title %}سجل العمليات{% endblock %}
{% block content %}
<h2 class="mb-4">
    <i class="bi bi-clock-history"></i> سجل العمليات
</h2>

<div class="card">
    <div class="card-body">
        <div class="table-responsive">
            <table class="table table-hover">
                <thead>
                    <tr>
                        <th>رقم الطلب</th>
                        <th>العميل</th>
                        <th>الهاتف</th>
                        <th>المتعامل</th>
                        <th>القيمة</th>
                        <th>التكلفة</th>
                        <th>العمولة</th>
                        <th>الحالة</th>
                        <th>التاريخ</th>
                    </tr>
                </thead>
                <tbody>
                    {% for op in operations %}
                    <tr>
                        <td><code>{{ op.request_number }}</code></td>
                        <td>{{ op.customer_name }}</td>
                        <td>{{ op.phone_number }}</td>
                        <td>
                            {% if op.operator == 'ooredoo' %}
                            <span class="badge bg-danger">أوريدو</span>
                            {% elif op.operator == 'djezzy' %}
                            <span class="badge bg-warning">جيزي</span>
                            {% else %}
                            <span class="badge bg-info">موبيليس</span>
                            {% endif %}
                        </td>
                        <td>{{ op.value }} د.ج</td>
                        <td>{{ "%.2f"|format(op.cost) }} د.ج</td>
                        <td class="text-success">+{{ "%.2f"|format(op.commission) }} د.ج</td>
                        <td>
                            {% if op.status == 'sent' %}
                            <span class="badge bg-success"><i class="bi bi-check-circle"></i> تم</span>
                            {% elif op.status == 'pending' %}
                            <span class="badge bg-warning"><i class="bi bi-clock"></i> قيد الانتظار</span>
                            {% elif op.status == 'failed' %}
                            <span class="badge bg-danger"><i class="bi bi-x-circle"></i> فشل</span>
                            {% else %}
                            <span class="badge bg-secondary">{{ op.status }}</span>
                            {% endif %}
                        </td>
                        <td>{{ op.created_at[:16] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endblock %}
'''

# ==================== المسارات ====================
@app.route('/')
def index():
    """الصفحة الرئيسية"""
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """تسجيل الدخول"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        db = get_db()
        user = db.execute(
            'SELECT * FROM users WHERE username = ? AND password = ?',
            (username, password_hash)
        ).fetchone()
        db.close()
        
        if user:
            if not user['is_active']:
                flash('حسابك معطل. يرجى التواصل مع الإدارة', 'danger')
                return redirect(url_for('login'))
            
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session.permanent = True
            flash(f'مرحباً {user["full_name"]}', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'danger')
    
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', LOGIN_TEMPLATE))

@app.route('/logout')
def logout():
    """تسجيل الخروج"""
    session.clear()
    flash('تم تسجيل الخروج بنجاح', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required()
def dashboard():
    """لوحة التحكم"""
    db = get_db()
    user_id = session['user_id']
    
    # جلب معلومات المستخدم
    user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    
    # إحصائيات
    today = datetime.now().strftime('%Y-%m-%d')
    stats = {
        'today_count': db.execute(
            'SELECT COUNT(*) as count FROM operations WHERE user_id = ? AND DATE(created_at) = ?',
            (user_id, today)
        ).fetchone()['count'],
        'pending_count': db.execute(
            'SELECT COUNT(*) as count FROM operations WHERE user_id = ? AND status = "pending"',
            (user_id,)
        ).fetchone()['count'],
        'total_commission': db.execute(
            'SELECT COALESCE(SUM(commission), 0) as total FROM operations WHERE user_id = ? AND status = "sent"',
            (user_id,)
        ).fetchone()['total']
    }
    
    # آخر العمليات
    recent_operations = db.execute(
        'SELECT * FROM operations WHERE user_id = ? ORDER BY created_at DESC LIMIT 10',
        (user_id,)
    ).fetchall()
    
    db.close()
    
    return render_template_string(
        BASE_TEMPLATE.replace('{% block content %}{% endblock %}', DASHBOARD_TEMPLATE),
        balance=user['balance'],
        stats=stats,
        recent_operations=recent_operations
    )

@app.route('/topup/create', methods=['POST'])
@login_required()
def create_topup():
    """إنشاء طلب شحن جديد"""
    db = get_db()
    user_id = session['user_id']
    
    # بيانات الطلب
    customer_name = request.form.get('customer_name')
    phone_number = request.form.get('phone_number')
    operator = request.form.get('operator')
    mode = request.form.get('mode') or None
    value = int(request.form.get('value'))
    
    # حساب التكلفة
    cost = calculate_cost(operator, value, mode)
    
    # التحقق من الرصيد
    user = db.execute('SELECT balance, commission_rate FROM users WHERE id = ?', (user_id,)).fetchone()
    if user['balance'] < cost:
        db.close()
        flash('رصيدك غير كافٍ لإتمام العملية', 'danger')
        return redirect(url_for('dashboard'))
    
    # توليد رقم الطلب
    request_number = generate_request_number()
    
    # حساب العمولة
    commission = value * (user['commission_rate'] / 100)
    
    # حفظ في قاعدة البيانات
    db.execute('''
        INSERT INTO operations (request_number, user_id, customer_name, phone_number, operator, mode, value, cost, commission, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
    ''', (request_number, user_id, customer_name, phone_number, operator, mode, value, cost, commission))
    
    # خصم من الرصيد
    db.execute('UPDATE users SET balance = balance - ? WHERE id = ?', (cost, user_id))
    db.commit()
    
    # استدعاء Chargily API
    api_data = {
        'request_number': request_number,
        'customer_name': customer_name,
        'phone_number': phone_number,
        'value': value,
        'operator': operator,
        'mode': mode or 'normal',
        'country_code': 'DZ',
        'webhook_url': WEBHOOK_URL,
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    success, result = call_chargily_api('/topup/requests', 'POST', api_data)
    
    if success:
        flash(f'تم إرسال طلب الشحن بنجاح - رقم الطلب: {request_number}', 'success')
    else:
        # إرجاع المبلغ في حالة الفشل
        db.execute('UPDATE users SET balance = balance + ? WHERE id = ?', (cost, user_id))
        db.execute('UPDATE operations SET status = "failed" WHERE request_number = ?', (request_number,))
        db.commit()
        flash(f'فشل إرسال الطلب: {result}', 'danger')
    
    db.close()
    return redirect(url_for('dashboard'))

@app.route('/operations')
@login_required()
def operations():
    """سجل العمليات"""
    db = get_db()
    user_id = session['user_id']
    
    if session['role'] == 'admin':
        ops = db.execute('SELECT * FROM operations ORDER BY created_at DESC LIMIT 100').fetchall()
    else:
        ops = db.execute('SELECT * FROM operations WHERE user_id = ? ORDER BY created_at DESC LIMIT 100', (user_id,)).fetchall()
    
    db.close()
    
    return render_template_string(
        BASE_TEMPLATE.replace('{% block content %}{% endblock %}', OPERATIONS_TEMPLATE),
        operations=ops
    )

@app.route('/admin/users')
@login_required(role='admin')
def admin_users():
    """إدارة المستخدمين (للإدمن فقط)"""
    db = get_db()
    users = db.execute('SELECT * FROM users ORDER BY id').fetchall()
    db.close()
    
    return render_template_string(
        BASE_TEMPLATE.replace('{% block content %}{% endblock %}', ADMIN_USERS_TEMPLATE),
        users=users
    )

@app.route('/admin/users/add', methods=['POST'])
@login_required(role='admin')
def admin_add_user():
    """إضافة مستخدم جديد"""
    db = get_db()
    
    username = request.form.get('username')
    password = request.form.get('password')
    full_name = request.form.get('full_name')
    phone = request.form.get('phone')
    commission_rate = float(request.form.get('commission_rate', 0))
    initial_balance = float(request.form.get('initial_balance', 0))
    
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    try:
        db.execute('''
            INSERT INTO users (username, password, full_name, phone, commission_rate, balance)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (username, password_hash, full_name, phone, commission_rate, initial_balance))
        db.commit()
        flash(f'تم إضافة المستخدم {full_name} بنجاح', 'success')
    except sqlite3.IntegrityError:
        flash('اسم المستخدم موجود مسبقاً', 'danger')
    
    db.close()
    return redirect(url_for('admin_users'))

@app.route('/admin/users/<int:user_id>/balance', methods=['POST'])
@login_required(role='admin')
def admin_add_balance(user_id):
    """إضافة رصيد لمستخدم"""
    db = get_db()
    
    amount = float(request.form.get('amount'))
    note = request.form.get('note', '')
    
    # إضافة الرصيد
    db.execute('UPDATE users SET balance = balance + ? WHERE id = ?', (amount, user_id))
    
    # تسجيل الإيداع
    db.execute('''
        INSERT INTO deposits (user_id, amount, note, created_by)
        VALUES (?, ?, ?, ?)
    ''', (user_id, amount, note, session['user_id']))
    
    db.commit()
    
    user = db.execute('SELECT full_name FROM users WHERE id = ?', (user_id,)).fetchone()
    db.close()
    
    flash(f'تم إضافة {amount:.2f} د.ج إلى حساب {user["full_name"]}', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/<int:user_id>/edit', methods=['POST'])
@login_required(role='admin')
def admin_edit_user(user_id):
    """تعديل مستخدم"""
    db = get_db()
    
    full_name = request.form.get('full_name')
    commission_rate = float(request.form.get('commission_rate'))
    is_active = int(request.form.get('is_active'))
    
    db.execute('''
        UPDATE users SET full_name = ?, commission_rate = ?, is_active = ?
        WHERE id = ?
    ''', (full_name, commission_rate, is_active, user_id))
    
    db.commit()
    db.close()
    
    flash('تم تحديث بيانات المستخدم', 'success')
    return redirect(url_for('admin_users'))

@app.route('/webhook/topup', methods=['POST'])
def webhook_topup():
    """استقبال Webhook من Chargily"""
    try:
        # التحقق من التوقيع
        signature = request.headers.get('X-Signature', '')
        payload = request.get_json()
        
        expected_signature = hmac.new(
            CHARGILY_SECRET_KEY.encode(),
            request.get_data(),
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(signature, expected_signature):
            return jsonify({'error': 'Invalid signature'}), 401
        
        # معالجة الـ payload
        operation_data = payload.get('payload', {})
        request_number = operation_data.get('request_number')
        status = operation_data.get('status')
        
        db = get_db()
        
        # تحديث حالة العملية
        db.execute('''
            UPDATE operations SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE request_number = ?
        ''', (status, request_number))
        
        # في حالة الفشل، إرجاع المبلغ
        if status in ['failed', 'rejected', 'expired']:
            operation = db.execute(
                'SELECT user_id, cost FROM operations WHERE request_number = ?',
                (request_number,)
            ).fetchone()
            
            if operation:
                db.execute(
                    'UPDATE users SET balance = balance + ? WHERE id = ?',
                    (operation['cost'], operation['user_id'])
                )
        
        # في حالة النجاح، إضافة العمولة
        elif status == 'sent':
            operation = db.execute(
                'SELECT user_id, commission FROM operations WHERE request_number = ?',
                (request_number,)
            ).fetchone()
            
            if operation and operation['commission'] > 0:
                # يمكن إضافة نظام نقاط أو مكافآت هنا
                pass
        
        db.commit()
        db.close()
        
        return jsonify({'status': 'ok'}), 200
        
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/balance')
@login_required()
def api_balance():
    """API للحصول على رصيد Chargily"""
    success, result = call_chargily_api('/user/balance', 'GET')
    if success:
        balance_dzd = result.get('balance', 0) / 100
        return jsonify({'balance': balance_dzd, 'status': 'success'})
    else:
        return jsonify({'error': result, 'status': 'error'}), 400

# ==================== تشغيل التطبيق ====================
if __name__ == '__main__':
    init_db()
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.getenv('DEBUG', 'False') == 'True')
