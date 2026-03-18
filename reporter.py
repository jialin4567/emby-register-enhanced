"""
Report generator for daily / weekly / monthly pushes.
Called by the scheduler in scheduler.py.
"""
import sqlite3
import os
from datetime import datetime, timedelta
from collections import defaultdict

DATABASE = '/app/data/tokens.db'


def _get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db


def _emby_request(path):
    import requests
    emby_url = os.getenv("EMBY_SERVER_URL", "").rstrip("/")
    api_key = os.getenv("EMBY_API_KEY", "")
    try:
        r = requests.get(f"{emby_url}{path}",
                         headers={"X-Emby-Token": api_key},
                         timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _get_active_streams():
    sessions = _emby_request("/Sessions") or []
    return [s for s in sessions if s.get("NowPlayingItem")]


def _expiring_soon(days=3):
    db = _get_db()
    now = datetime.utcnow()
    deadline = (now + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    rows = db.execute("""
        SELECT username, expires_at FROM registered_users
        WHERE expires_at IS NOT NULL
          AND expires_at > ?
          AND expires_at <= ?
          AND is_locked = 0
        ORDER BY expires_at ASC
    """, (now_str, deadline)).fetchall()
    db.close()
    return rows


def _reg_count_since(since: datetime) -> int:
    db = _get_db()
    count = db.execute(
        "SELECT COUNT(*) FROM registered_users WHERE registered_at >= ?",
        (since.strftime("%Y-%m-%d %H:%M:%S"),)
    ).fetchone()[0]
    db.close()
    return count


def _token_stats():
    db = _get_db()
    total = db.execute("SELECT COUNT(*) FROM tokens").fetchone()[0]
    used = db.execute("SELECT COUNT(*) FROM tokens WHERE is_used=1").fetchone()[0]
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    expired_unused = db.execute(
        "SELECT COUNT(*) FROM tokens WHERE is_used=0 AND expires_at IS NOT NULL AND expires_at < ?",
        (now_str,)
    ).fetchone()[0]
    valid = total - used - expired_unused
    db.close()
    return {"total": total, "used": used, "valid": valid}


def _locked_and_expired_count():
    db = _get_db()
    locked = db.execute("SELECT COUNT(*) FROM registered_users WHERE is_locked=1").fetchone()[0]
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    expired = db.execute(
        "SELECT COUNT(*) FROM registered_users WHERE expires_at IS NOT NULL AND expires_at < ? AND is_locked=0",
        (now_str,)
    ).fetchone()[0]
    total = db.execute("SELECT COUNT(*) FROM registered_users").fetchone()[0]
    db.close()
    return {"total": total, "locked": locked, "expired_unlocked": expired}


def build_report(period: str) -> str:
    """period: 'daily' | 'weekly' | 'monthly'"""
    now = datetime.utcnow()
    period_map = {
        "daily":   ("日报", timedelta(days=1)),
        "weekly":  ("周报", timedelta(weeks=1)),
        "monthly": ("月报", timedelta(days=30)),
    }
    label, delta = period_map.get(period, ("报告", timedelta(days=1)))
    since = now - delta

    streams = _get_active_streams()
    new_reg = _reg_count_since(since)
    tokens = _token_stats()
    users = _locked_and_expired_count()
    expiring = _expiring_soon(days=3)

    server_name = ((_emby_request("/System/Info") or {}).get("ServerName") or "Emby Server")

    lines = [
        f"📊 <b>{server_name} · {label}</b>",
        f"🕐 {now.strftime('%Y-%m-%d %H:%M')} UTC",
        "",
        "━━━━━━━━━━━━━━━━━━",
        f"📺 当前在线播放：<b>{len(streams)}</b> 路",
    ]
    if streams:
        for s in streams[:5]:
            item = s.get("NowPlayingItem", {})
            title = item.get("SeriesName") or item.get("Name", "")
            lines.append(f"   · {s.get('UserName','')} — {title}")
        if len(streams) > 5:
            lines.append(f"   · 等共 {len(streams)} 路...")

    lines += [
        "",
        f"👥 用户总计：<b>{users['total']}</b>",
        f"   ✅ 正常：{users['total'] - users['locked'] - users['expired_unlocked']}",
        f"   ⏰ 待处理到期：{users['expired_unlocked']}",
        f"   🔒 已锁定：{users['locked']}",
        f"   🆕 本{label[:1]}新增注册：<b>{new_reg}</b>",
        "",
        f"🎟️ Token 状态：有效 <b>{tokens['valid']}</b> / 总计 {tokens['total']}",
    ]

    if expiring:
        lines += ["", "⚠️ <b>3天内即将到期：</b>"]
        for row in expiring:
            exp = row["expires_at"][:10]
            lines.append(f"   · {row['username']} ({exp})")

    lines += ["", "━━━━━━━━━━━━━━━━━━"]
    return "\n".join(lines)
