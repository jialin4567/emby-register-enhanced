"""
Telegram Bot for Emby management.
Runs as a background thread using long-polling.
Only responds to TG_ADMIN_CHAT_ID.

Commands:
  /status         - server & stream overview
  /users          - list all registered users
  /expiring       - users expiring within 3 days
  /online         - current active streams
  /renew <name> <days> - renew user by days
  /lock <name>    - disable user on Emby
  /unlock <name>  - enable user on Emby
  /lockexpired    - lock all expired users
  /report         - send report now
  /help           - command list
"""
import os
import sqlite3
import threading
import logging
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
DATABASE = "/app/data/tokens.db"

# ── helpers ───────────────────────────────────────────────

def _get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db

def _emby_req(method, path, **kwargs):
    base = os.getenv("EMBY_SERVER_URL", "").rstrip("/")
    key  = os.getenv("EMBY_API_KEY", "")
    try:
        r = requests.request(method, f"{base}{path}",
                             headers={"X-Emby-Token": key, "Content-Type": "application/json"},
                             timeout=15, **kwargs)
        r.raise_for_status()
        return r.json() if r.content else {}
    except Exception as e:
        logger.error(f"Emby [{method} {path}]: {type(e).__name__}")
        return None

def _tg_send(token, chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10
        )
    except Exception as e:
        logger.error(f"TG send error: {e}")

def _disable_emby(emby_id):
    u = _emby_req("GET", f"/Users/{emby_id}")
    if not u: return False
    p = u.get("Policy", {}); p["IsDisabled"] = True
    return _emby_req("POST", f"/Users/{emby_id}/Policy", json=p) is not None

def _enable_emby(emby_id):
    u = _emby_req("GET", f"/Users/{emby_id}")
    if not u: return False
    p = u.get("Policy", {}); p["IsDisabled"] = False
    return _emby_req("POST", f"/Users/{emby_id}/Policy", json=p) is not None


# ── command handlers ──────────────────────────────────────

def cmd_help() -> str:
    return (
        "🤖 <b>Emby 管理 Bot</b>\n\n"
        "/status — 服务器概览\n"
        "/online — 当前在线播放\n"
        "/users  — 所有用户列表\n"
        "/expiring — 3天内到期用户\n"
        "/renew &lt;用户名&gt; &lt;天数&gt; — 续期\n"
        "/lock &lt;用户名&gt; — 锁定\n"
        "/unlock &lt;用户名&gt; — 解锁\n"
        "/lockexpired — 一键锁定所有到期\n"
        "/report — 立即发送报告\n"
    )


def cmd_status() -> str:
    sessions = _emby_req("GET", "/Sessions") or []
    active = [s for s in sessions if s.get("NowPlayingItem")]
    db = _get_db()
    total = db.execute("SELECT COUNT(*) FROM registered_users").fetchone()[0]
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    expired = db.execute(
        "SELECT COUNT(*) FROM registered_users WHERE expires_at IS NOT NULL AND expires_at < ? AND is_locked=0",
        (now_str,)
    ).fetchone()[0]
    locked = db.execute("SELECT COUNT(*) FROM registered_users WHERE is_locked=1").fetchone()[0]
    tokens_valid = db.execute(
        "SELECT COUNT(*) FROM tokens WHERE is_used=0 AND (expires_at IS NULL OR expires_at > ?)",
        (now_str,)
    ).fetchone()[0]
    db.close()
    info = (_emby_req("GET", "/System/Info") or {})
    return (
        f"📡 <b>{info.get('ServerName','Emby')} 状态</b>\n"
        f"版本：{info.get('Version','—')}\n\n"
        f"▶️ 正在播放：<b>{len(active)}</b> 路\n"
        f"👥 总用户：{total}  🔒 已锁：{locked}  ⚠️ 待锁到期：{expired}\n"
        f"🎟️ 可用Token：{tokens_valid}\n"
        f"🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC"
    )


def cmd_online() -> str:
    sessions = _emby_req("GET", "/Sessions") or []
    active = [s for s in sessions if s.get("NowPlayingItem")]
    if not active:
        return "📺 当前没有在线播放"
    lines = [f"📺 <b>当前在线 {len(active)} 路</b>"]
    for s in active:
        item = s.get("NowPlayingItem", {})
        title = item.get("SeriesName") or item.get("Name", "?")
        method = s.get("PlayState", {}).get("PlayMethod", "")
        lines.append(f"· <b>{s.get('UserName','?')}</b> — {title} [{method}] ({s.get('Client','')})")
    return "\n".join(lines)


def cmd_users() -> str:
    db = _get_db()
    users = db.execute(
        "SELECT username, expires_at, is_locked FROM registered_users ORDER BY registered_at DESC LIMIT 30"
    ).fetchall()
    db.close()
    if not users:
        return "👥 暂无注册用户"
    now = datetime.utcnow()
    lines = [f"👥 <b>用户列表（最近30条）</b>"]
    for u in users:
        if u["is_locked"]:
            icon = "🔒"
        elif u["expires_at"]:
            try:
                exp = datetime.strptime(u["expires_at"], "%Y-%m-%d %H:%M:%S")
                icon = "⚠️" if exp < now else "✅"
            except Exception:
                icon = "✅"
        else:
            icon = "✅"
        exp_str = u["expires_at"][:10] if u["expires_at"] else "永久"
        lines.append(f"{icon} {u['username']} — {exp_str}")
    return "\n".join(lines)


def cmd_expiring() -> str:
    db = _get_db()
    now = datetime.utcnow()
    deadline = (now + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    rows = db.execute("""
        SELECT username, expires_at FROM registered_users
        WHERE expires_at IS NOT NULL AND expires_at > ? AND expires_at <= ? AND is_locked=0
        ORDER BY expires_at ASC
    """, (now_str, deadline)).fetchall()
    db.close()
    if not rows:
        return "✅ 3天内没有即将到期的用户"
    lines = [f"⚠️ <b>3天内到期用户（{len(rows)}人）</b>"]
    for r in rows:
        lines.append(f"· {r['username']} — {r['expires_at'][:10]}")
    return "\n".join(lines)


def cmd_renew(username: str, days_str: str) -> str:
    import re as _re
    if not _re.match(r'^[a-zA-Z0-9]{1,32}$', username):
        return "❌ 用户名格式不合法"
    try:
        days = int(days_str)
        assert 1 <= days <= 3650
    except Exception:
        return "❌ 用法：/renew <用户名> <天数>  例如：/renew alice 30"
    db = _get_db()
    u = db.execute("SELECT * FROM registered_users WHERE username=?", (username,)).fetchone()
    if not u:
        db.close()
        return f"❌ 用户 <b>{username}</b> 不存在"
    now = datetime.utcnow()
    try:
        base = datetime.strptime(u["expires_at"], "%Y-%m-%d %H:%M:%S") if u["expires_at"] else now
        base = max(base, now)
    except Exception:
        base = now
    new_exp = (base + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE registered_users SET expires_at=?, last_renewed_at=?, is_locked=0 WHERE username=?",
               (new_exp, now.strftime("%Y-%m-%d %H:%M:%S"), username))
    db.commit()
    if u["is_locked"]:
        _enable_emby(u["emby_user_id"])
    db.close()
    return f"✅ <b>{username}</b> 已续期 {days} 天，到期：{new_exp[:10]}"


def cmd_lock(username: str) -> str:
    db = _get_db()
    u = db.execute("SELECT * FROM registered_users WHERE username=?", (username,)).fetchone()
    if not u:
        db.close()
        return f"❌ 用户 <b>{username}</b> 不存在"
    db.execute("UPDATE registered_users SET is_locked=1 WHERE username=?", (username,))
    db.commit()
    db.close()
    _disable_emby(u["emby_user_id"])
    return f"🔒 <b>{username}</b> 已锁定"


def cmd_unlock(username: str) -> str:
    db = _get_db()
    u = db.execute("SELECT * FROM registered_users WHERE username=?", (username,)).fetchone()
    if not u:
        db.close()
        return f"❌ 用户 <b>{username}</b> 不存在"
    db.execute("UPDATE registered_users SET is_locked=0 WHERE username=?", (username,))
    db.commit()
    db.close()
    _enable_emby(u["emby_user_id"])
    return f"🔓 <b>{username}</b> 已解锁"


def cmd_lock_expired() -> str:
    db = _get_db()
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    expired = db.execute(
        "SELECT * FROM registered_users WHERE expires_at IS NOT NULL AND expires_at < ? AND is_locked=0",
        (now_str,)
    ).fetchall()
    locked = 0
    for u in expired:
        db.execute("UPDATE registered_users SET is_locked=1 WHERE id=?", (u["id"],))
        if _disable_emby(u["emby_user_id"]):
            locked += 1
    db.commit()
    db.close()
    return f"🔒 已锁定 <b>{locked}</b> 个到期用户"


def cmd_report() -> str:
    from reporter import build_report
    return build_report("daily")


# ── dispatcher ────────────────────────────────────────────

def dispatch(text: str) -> str:
    text = text.strip()
    parts = text.split()
    cmd = parts[0].lower().split("@")[0] if parts else ""

    if cmd == "/help":    return cmd_help()
    if cmd == "/start":   return cmd_help()
    if cmd == "/status":  return cmd_status()
    if cmd == "/online":  return cmd_online()
    if cmd == "/users":   return cmd_users()
    if cmd == "/expiring": return cmd_expiring()
    if cmd == "/lockexpired": return cmd_lock_expired()
    if cmd == "/report":  return cmd_report()

    if cmd == "/renew":
        if len(parts) < 3:
            return "❌ 用法：/renew <用户名> <天数>"
        return cmd_renew(parts[1][:32], parts[2][:6])

    if cmd == "/lock":
        if len(parts) < 2:
            return "❌ 用法：/lock <用户名>"
        return cmd_lock(parts[1][:32])

    if cmd == "/unlock":
        if len(parts) < 2:
            return "❌ 用法：/unlock <用户名>"
        return cmd_unlock(parts[1][:32])

    return "❓ 未知指令，发送 /help 查看帮助"


# ── polling loop ──────────────────────────────────────────

def _poll_loop(token: str, admin_chat_id: str):
    offset = None
    logger.info("Telegram bot polling started")
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": ["message"]}
            if offset:
                params["offset"] = offset
            r = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params=params, timeout=40
            )
            data = r.json()
            if not data.get("ok"):
                import time; time.sleep(5); continue
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "")
                if not text or not chat_id:
                    continue
                # Security: only respond to admin
                if chat_id != admin_chat_id:
                    _tg_send(token, chat_id, "⛔ 无权限")
                    continue
                reply = dispatch(text)
                _tg_send(token, chat_id, reply)
        except Exception as e:
            logger.error(f"Bot poll error: {e}")
            import time; time.sleep(5)


def start_bot():
    """Start bot in background thread if configured."""
    token = os.getenv("TG_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TG_ADMIN_CHAT_ID", "").strip()
    if not token or not chat_id:
        logger.info("Telegram bot not configured, skipping")
        return
    t = threading.Thread(target=_poll_loop, args=(token, chat_id), daemon=True)
    t.start()
    logger.info("Telegram bot thread started")
