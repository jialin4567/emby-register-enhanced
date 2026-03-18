import os
import re
import secrets
import sqlite3
import uuid
import hmac
import hashlib
import threading
from datetime import datetime, timedelta
from functools import wraps
from collections import defaultdict
import requests
from flask import (Flask, flash, redirect, render_template, request, session,
                   url_for, jsonify)
from flask_paginate import Pagination, get_page_args
from flask_wtf.csrf import CSRFProtect, generate_csrf
from flask_session import Session
from werkzeug.middleware.proxy_fix import ProxyFix

# ── Brute-force protection (in-memory, per-IP) ────────────
_login_attempts = defaultdict(list)
_login_lock = threading.Lock()
LOGIN_MAX_ATTEMPTS = 10
LOGIN_WINDOW_SECONDS = 300

def _check_rate_limit(ip: str) -> bool:
    now = datetime.utcnow()
    cutoff = now - timedelta(seconds=LOGIN_WINDOW_SECONDS)
    with _login_lock:
        _login_attempts[ip] = [t for t in _login_attempts[ip] if t > cutoff]
        if len(_login_attempts[ip]) >= LOGIN_MAX_ATTEMPTS:
            return False
        _login_attempts[ip].append(now)
        return True

app = Flask(__name__)

# ── 1. Reverse proxy fix: correctly read real client IP ──────
# x_for=1 means trust exactly ONE proxy hop (your Nginx/Cloudflare)
# Adjust to x_for=2 if you have Cloudflare -> Nginx -> app
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

SECRET_KEY_FROM_ENV = os.getenv('FLASK_SECRET_KEY')
if not SECRET_KEY_FROM_ENV:
    raise ValueError("错误: 必须设置 FLASK_SECRET_KEY 环境变量!")
if len(SECRET_KEY_FROM_ENV) < 32:
    raise ValueError("错误: FLASK_SECRET_KEY 长度不能少于32位!")
app.config['SECRET_KEY'] = SECRET_KEY_FROM_ENV
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=4)

# ── 2. Server-side session (filesystem) ─────────────────────
# Sessions stored in /app/data/flask_sessions — logout truly invalidates them
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = '/app/data/flask_sessions'
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_USE_SIGNER'] = True
# Cookie hardening: SameSite=Lax prevents CSRF on session cookie itself
# Set SESSION_COOKIE_SECURE=True if your deployment enforces HTTPS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True   # JS cannot read session cookie
# app.config['SESSION_COOKIE_SECURE'] = True   # Uncomment when using HTTPS
Session(app)

# ── 3. CSRF protection ──────────────────────────────────────
# All routes protected by default.
# API routes (/api/*) validate via X-CSRFToken header sent by frontend JS.
# This is the correct approach — no "exempt" backdoors.
csrf = CSRFProtect(app)

@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    # Expose CSRF token in a JS-readable cookie (not HttpOnly)
    # Frontend reads this and sends it as X-CSRFToken header on every API call
    response.set_cookie(
        'csrf_token', generate_csrf(),
        samesite='Lax',   # Lax: allows cookie on top-level nav, blocks cross-site POST
        httponly=False,   # Must be readable by JS
    )
    return response

DATABASE = '/app/data/tokens.db'
PER_PAGE = 15

_ADMIN_PASSWORD_RAW = os.getenv('ADMIN_PASSWORD', '')
# Support both plaintext (legacy) and pre-hashed passwords.
# To use a hash: run `python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('yourpassword'))"` 
# then set ADMIN_PASSWORD to the output string (starts with pbkdf2: or scrypt:).
_ADMIN_PASSWORD_IS_HASH = _ADMIN_PASSWORD_RAW.startswith(('pbkdf2:', 'scrypt:', 'bcrypt:'))
EMBY_SERVER_URL = os.getenv('EMBY_SERVER_URL', '').rstrip('/')
EMBY_API_KEY = os.getenv('EMBY_API_KEY')
_raw_copy_id = os.getenv('COPY_FROM_USER_ID', '')
try:
    COPY_FROM_USER_ID = str(uuid.UUID(_raw_copy_id))  # 自动转为带连字符的标准 UUID
except ValueError:
    COPY_FROM_USER_ID = _raw_copy_id  # 格式异常时原样保留，启动检查会拦截
PUBLIC_ACCESS_URL = os.getenv('PUBLIC_ACCESS_URL', 'YOUR_DOMAIN.com').rstrip('/')
EMBY_SERVER_URL_CLOUDFLARE = os.getenv('EMBY_SERVER_URL_CLOUDFLARE', '').rstrip('/')

if not all([_ADMIN_PASSWORD_RAW, EMBY_SERVER_URL, EMBY_API_KEY, COPY_FROM_USER_ID]):
    raise ValueError("请设置所有必需的环境变量: ADMIN_PASSWORD, EMBY_SERVER_URL, EMBY_API_KEY, COPY_FROM_USER_ID")


def _generate_signed_token(payload):
    signature = hmac.new(app.config['SECRET_KEY'].encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"

def _verify_signed_token(signed_token):
    if not signed_token or '.' not in signed_token:
        return None
    payload, signature = signed_token.rsplit('.', 1)
    expected_signature = hmac.new(app.config['SECRET_KEY'].encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
    if hmac.compare_digest(expected_signature, signature):
        return payload
    return None


def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db

def init_db():
    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
    with app.app_context():
        db = get_db()
        cursor = db.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                is_used BOOLEAN DEFAULT 0,
                registered_username TEXT,
                note TEXT
            )
        ''')
        for col in [('expires_at', 'TIMESTAMP'), ('note', 'TEXT')]:
            try:
                cursor.execute(f'ALTER TABLE tokens ADD COLUMN {col[0]} {col[1]}')
            except sqlite3.OperationalError:
                pass
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS registered_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                emby_user_id TEXT NOT NULL UNIQUE,
                username TEXT NOT NULL,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                is_locked BOOLEAN DEFAULT 0,
                last_renewed_at TIMESTAMP,
                token_used TEXT
            )
        ''')
        db.commit()
        db.close()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


def _emby_request(method, path, **kwargs):
    headers = {'X-Emby-Token': EMBY_API_KEY, 'Content-Type': 'application/json'}
    url = f"{EMBY_SERVER_URL}{path}"
    try:
        resp = requests.request(method, url, headers=headers, timeout=15, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else {}
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Emby API error [{method} {path}]: {type(e).__name__}")
        return None

def create_emby_user(username, password):
    user_data = _emby_request('POST', '/Users/New', json={
        "Name": username,
        "CopyFromUserId": COPY_FROM_USER_ID,
        "UserCopyOptions": ["UserConfiguration", "UserPolicy", "UserData"]
    })
    if not user_data:
        return None, "创建用户失败，请联系管理员。"
    user_id = user_data.get('Id')
    if not user_id:
        return None, "创建用户成功，但未获取到User ID。"

    # 主动从模板用户同步 Policy 和 Configuration，防止 Emby 静默忽略 CopyFromUserId
    template_user = _emby_request('GET', f'/Users/{COPY_FROM_USER_ID}')
    if template_user:
        policy = template_user.get('Policy', {})
        policy['IsDisabled'] = False  # 新用户强制启用
        _emby_request('POST', f'/Users/{user_id}/Policy', json=policy)
        configuration = template_user.get('Configuration', {})
        _emby_request('POST', f'/Users/{user_id}/Configuration', json=configuration)
    else:
        app.logger.warning(f"无法获取模板用户 {COPY_FROM_USER_ID} 的信息，新用户将使用默认设置")

    pw_result = _emby_request('POST', f'/Users/{user_id}/Password', json={
        "Id": user_id,
        "CurrentPw": "",
        "NewPw": password,
        "ResetPassword": False
    })
    if pw_result is None:
        return None, "用户已创建但设置密码失败，请联系管理员。"
    return user_id, None

def disable_emby_user(emby_user_id):
    user = _emby_request('GET', f'/Users/{emby_user_id}')
    if not user:
        return False
    policy = user.get('Policy', {})
    policy['IsDisabled'] = True
    return _emby_request('POST', f'/Users/{emby_user_id}/Policy', json=policy) is not None

def enable_emby_user(emby_user_id):
    user = _emby_request('GET', f'/Users/{emby_user_id}')
    if not user:
        return False
    policy = user.get('Policy', {})
    policy['IsDisabled'] = False
    return _emby_request('POST', f'/Users/{emby_user_id}/Policy', json=policy) is not None

def get_emby_sessions():
    return _emby_request('GET', '/Sessions') or []


# ===== ORIGINAL ROUTES =====

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        ip = request.remote_addr or '0.0.0.0'
        if not _check_rate_limit(ip):
            return render_template('login.html', error='尝试次数过多，请5分钟后再试'), 429
        candidate = request.form.get('password', '')
        if _ADMIN_PASSWORD_IS_HASH:
            from werkzeug.security import check_password_hash
            password_ok = check_password_hash(_ADMIN_PASSWORD_RAW, candidate)
        else:
            # Plaintext fallback for backward compatibility
            password_ok = hmac.compare_digest(candidate, _ADMIN_PASSWORD_RAW)
        if password_ok:
            session.permanent = True
            session['logged_in'] = True
            flash('登录成功!', 'success')
            # Validate next param to prevent open redirect
            next_url = request.args.get('next', '')
            if next_url and next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error='密码错误')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()   # server-side: destroys the session file, not just a cookie value
    flash('您已退出登录。', 'info')
    return redirect(url_for('login'))

@app.route('/admin')
@login_required
def admin():
    db = get_db()
    total = db.execute('SELECT COUNT(*) FROM tokens').fetchone()[0]
    page, per_page, offset = get_page_args(page_parameter='page', per_page_parameter='per_page', per_page=PER_PAGE)
    tokens_from_db = db.execute(
        'SELECT id, token, is_used, registered_username, expires_at, note FROM tokens ORDER BY created_at DESC LIMIT ? OFFSET ?',
        (per_page, offset)
    ).fetchall()
    db.close()

    pagination = Pagination(page=page, per_page=per_page, total=total, css_framework='bootstrap5', record_name='tokens')
    now = datetime.utcnow()
    processed_tokens = []
    for t in tokens_from_db:
        expires_at = t['expires_at']
        is_expired = False
        if expires_at and not t['is_used']:
            try:
                is_expired = datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S') < now
            except (ValueError, TypeError):
                pass
        processed_tokens.append({
            'id': t['id'],
            'full_signed_token': _generate_signed_token(t['token']),
            'is_used': t['is_used'],
            'username': t['registered_username'],
            'expires_at': expires_at,
            'is_expired': is_expired,
            'note': t['note'] or '',
        })
    return render_template('admin.html', tokens=processed_tokens, pagination=pagination, public_access_url=PUBLIC_ACCESS_URL)

@app.route('/admin/generate', methods=['POST'])
@login_required
def generate_token():
    validity = request.form.get('validity', 'permanent')
    note = request.form.get('note', '')[:200]
    try:
        count = min(max(int(request.form.get('count', 1)), 1), 50)
    except (ValueError, TypeError):
        count = 1
    expires_at = None
    if validity == '7d':
        expires_at = (datetime.utcnow() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
    elif validity == '30d':
        expires_at = (datetime.utcnow() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
    elif validity != 'permanent':
        flash('无效的有效期参数', 'danger')
        return redirect(url_for('admin'))
    db = get_db()
    for _ in range(count):
        nonce = secrets.token_urlsafe(16)
        db.execute('INSERT INTO tokens (token, expires_at, note) VALUES (?, ?, ?)', (nonce, expires_at, note))
    db.commit()
    db.close()
    flash(f'已生成 {count} 个 Token!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/delete/<int:token_id>', methods=['POST'])
@login_required
def delete_token(token_id):
    db = get_db()
    db.execute('DELETE FROM tokens WHERE id = ?', (token_id,))
    db.commit()
    db.close()
    flash('Token 已成功删除。', 'info')
    return redirect(url_for('admin'))

@app.route('/emby', methods=['GET', 'POST'])
def emby_register():
    error_msg_template = "您使用的注册链接无效、已被篡改或已过期。"
    full_token_str = request.form.get('token') if request.method == 'POST' else request.args.get('token')
    if full_token_str:
        full_token_str = full_token_str[:300]  # cap length to prevent ReDoS
    if not full_token_str:
        return render_template('error.html', error_message="链接不完整，缺少参数。")
    token_payload = _verify_signed_token(full_token_str)
    if not token_payload:
        return render_template('error.html', error_message=error_msg_template)
    db = get_db()
    token_data = db.execute('SELECT * FROM tokens WHERE token = ? AND is_used = 0', (token_payload,)).fetchone()
    if not token_data:
        db.close()
        return render_template('error.html', error_message=error_msg_template)
    if token_data['expires_at']:
        try:
            if datetime.strptime(token_data['expires_at'], '%Y-%m-%d %H:%M:%S') < datetime.utcnow():
                db.close()
                return render_template('error.html', error_message="此注册链接已过期。")
        except (ValueError, TypeError):
            pass
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if not re.match(r'^[a-zA-Z0-9]{4,32}$', username):
            db.close()
            return render_template('register.html', token=full_token_str, error="用户名不合法：长度需为4-32位，且只能包含英文字母和数字。")
        if len(password) < 6:
            db.close()
            return render_template('register.html', token=full_token_str, error="密码长度至少6位。")
        if len(password) > 32:
            db.close()
            return render_template('register.html', token=full_token_str, error="密码长度不能超过32位。")
        try:
            from zxcvbn import zxcvbn as _zxcvbn
            pw_result = _zxcvbn(password, user_inputs=[username])
            if pw_result['score'] < 2:  # 0=worst, 4=best; require at least 2
                warning = pw_result['feedback'].get('warning', '')
                db.close()
                hint = f"（{warning}）" if warning else ""
                return render_template('register.html', token=full_token_str,
                                       error=f"密码强度不足，请使用更复杂的密码{hint}")
        except ImportError:
            # Fallback to basic blacklist if zxcvbn unavailable
            weak_passwords = ['123456','123456789','12345678','1234567','123123',
                              'password','qwerty','abc123','111111','000000',
                              '1qaz2wsx','admin','root','888888','666666']
            if password.lower() in weak_passwords:
                db.close()
                return render_template('register.html', token=full_token_str,
                                       error="密码过于简单，请使用更安全的密码。")
        user_id, error_msg = create_emby_user(username, password)
        if not user_id:
            db.close()
            return render_template('register.html', token=full_token_str, error=error_msg)
        db.execute('UPDATE tokens SET is_used = 1, registered_username = ? WHERE id = ?', (username, token_data['id']))
        db.execute('INSERT OR IGNORE INTO registered_users (emby_user_id, username, token_used) VALUES (?, ?, ?)',
                   (user_id, username, token_payload))
        db.commit()
        db.close()
        return render_template('success.html', username=username, password=password,
                               emby_url=EMBY_SERVER_URL, emby_url_cloudflare=EMBY_SERVER_URL_CLOUDFLARE)
    db.close()
    return render_template('register.html', token=full_token_str)


# ===== NEW ROUTES =====

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/api/dashboard/stats')
@login_required
def api_dashboard_stats():
    sessions = get_emby_sessions()
    active_streams = [s for s in sessions if s.get('NowPlayingItem')]
    db = get_db()
    total_tokens = db.execute('SELECT COUNT(*) FROM tokens').fetchone()[0]
    used_tokens = db.execute('SELECT COUNT(*) FROM tokens WHERE is_used = 1').fetchone()[0]
    total_reg = db.execute('SELECT COUNT(*) FROM registered_users').fetchone()[0]
    locked_users = db.execute('SELECT COUNT(*) FROM registered_users WHERE is_locked = 1').fetchone()[0]
    now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    expired_users = db.execute(
        'SELECT COUNT(*) FROM registered_users WHERE expires_at IS NOT NULL AND expires_at < ?', (now_str,)
    ).fetchone()[0]
    db.close()
    media_type_count = {}
    streams_info = []
    for s in active_streams:
        item = s.get('NowPlayingItem', {})
        mtype = item.get('Type', 'Unknown')
        media_type_count[mtype] = media_type_count.get(mtype, 0) + 1
        streams_info.append({
            'user': s.get('UserName', ''),
            'title': item.get('Name', ''),
            'series': item.get('SeriesName', ''),
            'type': mtype,
            'client': s.get('Client', ''),
            'device': s.get('DeviceName', ''),
            'play_method': s.get('PlayState', {}).get('PlayMethod', '直接播放'),
        })
    return jsonify({
        'active_streams': len(active_streams),
        'total_sessions': len(sessions),
        'total_tokens': total_tokens,
        'used_tokens': used_tokens,
        'total_registered': total_reg,
        'locked_users': locked_users,
        'expired_users': expired_users,
        'media_type_count': media_type_count,
        'streams': streams_info,
    })

@app.route('/api/dashboard/trend')
@login_required
def api_dashboard_trend():
    db = get_db()
    labels, data = [], []
    for i in range(29, -1, -1):
        day = (datetime.utcnow() - timedelta(days=i)).strftime('%Y-%m-%d')
        count = db.execute("SELECT COUNT(*) FROM registered_users WHERE date(registered_at) = ?", (day,)).fetchone()[0]
        labels.append((datetime.utcnow() - timedelta(days=i)).strftime('%m/%d'))
        data.append(count)
    db.close()
    return jsonify({'labels': labels, 'data': data})

@app.route('/users')
@login_required
def users_page():
    return render_template('users.html')

@app.route('/api/users/list')
@login_required
def api_users_list():
    db = get_db()
    users = db.execute('SELECT * FROM registered_users ORDER BY registered_at DESC').fetchall()
    db.close()
    now = datetime.utcnow()
    result = []
    for u in users:
        expires_at = u['expires_at']
        is_expired = False
        if expires_at:
            try:
                is_expired = datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S') < now
            except (ValueError, TypeError):
                pass
        result.append({
            'id': u['id'],
            'emby_user_id': u['emby_user_id'],
            'username': u['username'],
            'registered_at': u['registered_at'] or '',
            'expires_at': expires_at or '永久',
            'is_expired': is_expired,
            'is_locked': bool(u['is_locked']),
            'last_renewed_at': u['last_renewed_at'] or '',
        })
    return jsonify(result)

@app.route('/api/users/renew', methods=['POST'])
@login_required
def api_users_renew():
    data = request.get_json()
    user_ids = [int(i) for i in data.get('user_ids', []) if str(i).isdigit()]
    if len(user_ids) > 500:
        return jsonify({'success': False, 'message': '单次最多操作500个用户'}), 400
    days = int(data.get('days', 30))
    if days < 1 or days > 3650:
        return jsonify({'success': False, 'message': '续期天数无效（1-3650天）'}), 400
    db = get_db()
    now = datetime.utcnow()
    renewed = 0
    for uid in user_ids:
        u = db.execute('SELECT * FROM registered_users WHERE id = ?', (uid,)).fetchone()
        if not u:
            continue
        current_expiry = None
        if u['expires_at']:
            try:
                current_expiry = datetime.strptime(u['expires_at'], '%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError):
                pass
        base = max(current_expiry, now) if current_expiry else now
        new_expiry = (base + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
        db.execute('UPDATE registered_users SET expires_at = ?, last_renewed_at = ?, is_locked = 0 WHERE id = ?',
                   (new_expiry, now.strftime('%Y-%m-%d %H:%M:%S'), uid))
        if u['is_locked']:
            enable_emby_user(u['emby_user_id'])
        renewed += 1
    db.commit()
    db.close()
    return jsonify({'success': True, 'renewed': renewed})

@app.route('/api/users/lock', methods=['POST'])
@login_required
def api_users_lock():
    data = request.get_json()
    user_ids = [int(i) for i in data.get('user_ids', []) if str(i).isdigit()]
    if len(user_ids) > 500:
        return jsonify({'success': False, 'message': '单次最多操作500个用户'}), 400
    action = data.get('action', 'lock')
    if action not in ('lock', 'unlock'):
        return jsonify({'success': False, 'message': '无效操作'}), 400
    db = get_db()
    processed = 0
    for uid in user_ids:
        u = db.execute('SELECT * FROM registered_users WHERE id = ?', (uid,)).fetchone()
        if not u:
            continue
        is_locked = 1 if action == 'lock' else 0
        db.execute('UPDATE registered_users SET is_locked = ? WHERE id = ?', (is_locked, uid))
        if action == 'lock':
            disable_emby_user(u['emby_user_id'])
        else:
            enable_emby_user(u['emby_user_id'])
        processed += 1
    db.commit()
    db.close()
    return jsonify({'success': True, 'processed': processed})

@app.route('/api/users/auto-lock-expired', methods=['POST'])
@login_required
def api_auto_lock_expired():
    db = get_db()
    now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    expired = db.execute(
        'SELECT * FROM registered_users WHERE expires_at IS NOT NULL AND expires_at < ? AND is_locked = 0', (now_str,)
    ).fetchall()
    locked = 0
    for u in expired:
        db.execute('UPDATE registered_users SET is_locked = 1 WHERE id = ?', (u['id'],))
        if disable_emby_user(u['emby_user_id']):
            locked += 1
    db.commit()
    db.close()
    return jsonify({'success': True, 'locked': locked})

# ===== NOTIFY PAGE + API =====

@app.route('/notify')
@login_required
def notify_page():
    env_vars = {
        'TG_BOT_TOKEN': bool(os.getenv('TG_BOT_TOKEN')),
        'WECOM_WEBHOOK': bool(os.getenv('WECOM_WEBHOOK')),
        'DINGTALK_WEBHOOK': bool(os.getenv('DINGTALK_WEBHOOK')),
        'SERVERCHAN_KEY': bool(os.getenv('SERVERCHAN_KEY')),
        'FEISHU_WEBHOOK': bool(os.getenv('FEISHU_WEBHOOK')),
    }
    return render_template('notify.html',
                           env_vars=env_vars,
                           schedule=os.getenv('REPORT_SCHEDULE', ''),
                           report_hour=os.getenv('REPORT_HOUR', '8'))

@app.route('/api/notify/test', methods=['POST'])
@login_required
def api_notify_test():
    from notify import broadcast
    results = broadcast("✅ Emby 管理系统通知测试成功！", title="Emby 测试")
    if not results:
        return jsonify({'success': False, 'message': '未配置任何推送渠道'})
    return jsonify({'success': True, 'channels': results})

@app.route('/api/notify/report', methods=['POST'])
@login_required
def api_notify_report():
    data = request.get_json() or {}
    period = data.get('period', 'daily')
    if period not in ('daily', 'weekly', 'monthly'):
        return jsonify({'success': False, 'message': '无效的报告类型'}), 400
    from reporter import build_report
    from notify import broadcast
    text = build_report(period)
    label = {'daily': '日报', 'weekly': '周报', 'monthly': '月报'}[period]
    results = broadcast(text, title=f"Emby {label}")
    if not results:
        return jsonify({'success': False, 'message': '未配置任何推送渠道'})
    return jsonify({'success': True, 'channels': results, 'preview': text[:200]})


# ===== APP STARTUP =====

def _start_services():
    try:
        from tgbot import start_bot
        start_bot()
    except Exception as e:
        app.logger.error(f"Bot start error: {e}")
    try:
        from scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        app.logger.error(f"Scheduler start error: {e}")

with app.app_context():
    _start_services()

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000)
