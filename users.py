import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
USERS_FILE = BASE_DIR / "users.json"

FREE_LIMIT = 100  # عدد التحليلات المجانية

def _load_users():
    if not USERS_FILE.exists():
        return {}
    try:
        with USERS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.exception("Failed to load users.json")
        return {}

def _save_users(data):
    try:
        with USERS_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("Failed to save users.json")

def get_user(user_id: int):
    users = _load_users()
    uid = str(user_id)
    if uid not in users:
        users[uid] = {
            "analyses_used": 0,
            "is_active": False,
            "created_at": datetime.utcnow().isoformat()
        }
        _save_users(users)
    return users[uid]

def can_analyze(user_id: int) -> tuple[bool, str]:
    """
    يرجع (مسموح؟, الرسالة)
    """
    user = get_user(user_id)

    if user.get("is_active"):
        return True, ""

    used = user.get("analyses_used", 0)
    if used < FREE_LIMIT:
        return True, ""

    return False, (
        "انتهت التحليلات المجانية (2 تحليلات).\n\n"
        "للتفعيل تواصل مع صاحب البوت."
    )

def increment_usage(user_id: int):
    users = _load_users()
    uid = str(user_id)
    if uid not in users:
        get_user(user_id)
        users = _load_users()

    if not users[uid].get("is_active"):
        users[uid]["analyses_used"] = users[uid].get("analyses_used", 0) + 1
        _save_users(users)

def activate_user(user_id: int):
    """تفعيل مستخدم يدوياً"""
    users = _load_users()
    uid = str(user_id)
    if uid not in users:
        get_user(user_id)
        users = _load_users()
    users[uid]["is_active"] = True
    _save_users(users)
    return True