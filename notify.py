"""
Multi-channel notification module.
Supports: Telegram, 企业微信, 钉钉, Server酱, 飞书
Each channel is enabled only if its env vars are configured.
"""
import os
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
import logging

logger = logging.getLogger(__name__)


def _safe_post(url, **kwargs):
    try:
        r = requests.post(url, timeout=10, **kwargs)
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Notify POST failed [{url[:60]}]: {type(e).__name__}: {e}")
        return False


# ── Telegram ──────────────────────────────────────────────
def send_telegram(text: str, parse_mode: str = "HTML") -> bool:
    token = os.getenv("TG_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TG_ADMIN_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    return _safe_post(url, json={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    })


# ── 企业微信 ───────────────────────────────────────────────
def send_wecom(text: str) -> bool:
    webhook = os.getenv("WECOM_WEBHOOK", "").strip()
    if not webhook:
        return False
    return _safe_post(webhook, json={
        "msgtype": "text",
        "text": {"content": text}
    })


# ── 钉钉 ──────────────────────────────────────────────────
def send_dingtalk(text: str, title: str = "Emby 通知") -> bool:
    webhook = os.getenv("DINGTALK_WEBHOOK", "").strip()
    secret = os.getenv("DINGTALK_SECRET", "").strip()
    if not webhook:
        return False
    url = webhook
    if secret:
        ts = str(round(time.time() * 1000))
        sign_str = f"{ts}\n{secret}"
        sign = base64.b64encode(
            hmac.new(secret.encode(), sign_str.encode(), hashlib.sha256).digest()
        ).decode()
        url = f"{webhook}&timestamp={ts}&sign={urllib.parse.quote_plus(sign)}"
    return _safe_post(url, json={
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text}
    })


# ── Server酱 ──────────────────────────────────────────────
def send_serverchan(text: str, title: str = "Emby 通知") -> bool:
    key = os.getenv("SERVERCHAN_KEY", "").strip()
    if not key:
        return False
    # Support both SCT and old SC keys
    if key.startswith("SCT"):
        url = f"https://sctapi.ftqq.com/{key}.send"
    else:
        url = f"https://sc.ftqq.com/{key}.send"
    return _safe_post(url, data={"title": title, "desp": text})


# ── 飞书 ──────────────────────────────────────────────────
def send_feishu(text: str) -> bool:
    webhook = os.getenv("FEISHU_WEBHOOK", "").strip()
    if not webhook:
        return False
    return _safe_post(webhook, json={
        "msg_type": "text",
        "content": {"text": text}
    })


# ── Broadcast to all configured channels ──────────────────
def broadcast(text: str, title: str = "Emby 通知") -> dict:
    """Send to all configured channels. Returns {channel: bool}."""
    results = {}
    if os.getenv("TG_BOT_TOKEN") and os.getenv("TG_ADMIN_CHAT_ID"):
        results["telegram"] = send_telegram(text)
    if os.getenv("WECOM_WEBHOOK"):
        results["wecom"] = send_wecom(text)
    if os.getenv("DINGTALK_WEBHOOK"):
        results["dingtalk"] = send_dingtalk(text, title)
    if os.getenv("SERVERCHAN_KEY"):
        results["serverchan"] = send_serverchan(text, title)
    if os.getenv("FEISHU_WEBHOOK"):
        results["feishu"] = send_feishu(text)
    return results
