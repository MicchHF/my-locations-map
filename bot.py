import os
import re
import json
import secrets
import asyncio
from datetime import datetime, timedelta, timezone
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip() or "8981534227:AAGzsvm-znHtT-3cxm2UlFxFYribRnFHBU4"
SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip() or "https://cwkgylbtcjfmweoldhyb.supabase.co"
SUPABASE_KEY = (os.getenv("SUPABASE_KEY") or "").strip() or "sb_publishable_KnWO20wlfuWd0NYKMNKRvw_l1rttjaT"
WEBAPP_URL = (os.getenv("WEBAPP_URL") or "").strip() or "https://map.dalazareva.ru"
ADMIN_USERNAME = (os.getenv("ADMIN_USERNAME") or "").strip() or "dalazareva"
CHANNEL_USERNAME = (os.getenv("CHANNEL_USERNAME") or "dalazareva").lstrip('@')
CHANNEL_ID = (os.getenv("CHANNEL_ID") or "").strip()
CHANNEL_URL = (os.getenv("CHANNEL_URL") or f"https://t.me/{CHANNEL_USERNAME}").strip()

# -------------------------------------------------------------
# ПОДДЕРЖКА И АДМИНИСТРАТОРЫ
# -------------------------------------------------------------
# -5571470296 — группа закрытого чата поддержки dalazareva_help
# -5245526279 — группа отзывов и предложений локаций (feedback)
# 160737288 — Макс (@maksshlyapin)
# 723659507 — Даша (@dalazareva)
DEFAULT_SUPPORT_CHAT_ID = "-5571470296"
DEFAULT_FEEDBACK_CHAT_ID = "-5245526279"
DEFAULT_ADMIN_IDS = [160737288, 723659507, -5571470296, -5245526279]

SUPPORT_CHAT_ID = os.getenv("SUPPORT_CHAT_ID", "").strip() or DEFAULT_SUPPORT_CHAT_ID
FEEDBACK_CHAT_ID = os.getenv("FEEDBACK_CHAT_ID", "").strip() or DEFAULT_FEEDBACK_CHAT_ID
ADMIN_ID_ENV = os.getenv("ADMIN_ID", "").strip()

ADMIN_IDS = list(DEFAULT_ADMIN_IDS)
if ADMIN_ID_ENV and ADMIN_ID_ENV.lstrip('-').isdigit():
    try:
        a_int = int(ADMIN_ID_ENV)
        if a_int not in ADMIN_IDS:
            ADMIN_IDS.append(a_int)
    except Exception:
        pass

if SUPPORT_CHAT_ID and SUPPORT_CHAT_ID.lstrip('-').isdigit():
    try:
        s_int = int(SUPPORT_CHAT_ID)
        if s_int not in ADMIN_IDS:
            ADMIN_IDS.append(s_int)
    except Exception:
        pass

if FEEDBACK_CHAT_ID and FEEDBACK_CHAT_ID.lstrip('-').isdigit():
    try:
        f_int = int(FEEDBACK_CHAT_ID)
        if f_int not in ADMIN_IDS:
            ADMIN_IDS.append(f_int)
    except Exception:
        pass

# Хранилище состояний в памяти:
# Пользователи, нажавшие "Задать вопрос" и ожидающие ввода сообщения
SUPPORT_WAITING_USERS = {}  # {user_id: True}
# Пользователи, нажавшие "Написать отзыв" и ожидающие ввода отзыва
USER_REVIEW_WAITING = {}    # {user_id: True}
# Пользователи, нажавшие "Предложить локацию" и ожидающие ввода информации
USER_SUGGESTION_WAITING = {} # {user_id: True}
# Сопоставление ID сообщения в чате поддержки с ID пользователя для ответов через Reply
SUPPORT_REPLY_MAP = {}      # {admin_message_id: user_id}
# Администраторы/менеджеры, нажавшие кнопку "Ответить" и вводящие сообщение для пользователя
ADMIN_WAITING_REPLY = {}    # {admin_user_id: target_user_id}
# Администраторы/менеджеры, вводящие произвольное количество дней бонуса
ADMIN_WAITING_CUSTOM_DAYS = {}  # {admin_user_id: {"target_user_id": int, "ticket_msg_id": int}}
# Последнее неотправленное сообщение пользователя (на случай ввода без нажатия кнопки)
PENDING_SUPPORT_MESSAGE = {}  # {user_id: types.Message}
# Счетчик неотвеченных повторных отзывов пользователя (лимит: 1 повторный отзыв до ответа админа)
USER_UNANSWERED_REVIEWS = {}  # {user_id: int}
# Пользователи, чей отзыв находится на рассмотрении прямо сейчас
USER_PENDING_REVIEW_USERS = set()  # {user_id}
# Пользователи, отправившие первый отзыв
USER_FIRST_REVIEW_SUBMITTED = set()  # {user_id}
# Пользователи, уже получившие бонус за отзыв
USER_REVIEW_BONUS_AWARDED = set()  # {user_id}

# -------------------------------------------------------------
# СИСТЕМА УЧЕТА БОНУСОВ ЗА ОТЗЫВ (+7 ДНЕЙ) С ЗАЩИТОЙ ОТ АБУЗА
# -------------------------------------------------------------
REVIEW_REWARDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review_rewards.json")

def load_review_rewards() -> dict:
    """Загрузка базы уже выданных бонусов за отзывы."""
    if os.path.exists(REVIEW_REWARDS_FILE):
        try:
            with open(REVIEW_REWARDS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Ошибка чтения {REVIEW_REWARDS_FILE}: {e}")
    return {}

def save_review_rewards(data: dict):
    """Атомарная запись базы выданных бонусов."""
    try:
        with open(REVIEW_REWARDS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Ошибка сохранения {REVIEW_REWARDS_FILE}: {e}")

def init_review_state():
    """Инициализация оперативных кэш-множеств из review_rewards.json при запуске."""
    rewards = load_review_rewards()
    for uid_str, data in rewards.items():
        try:
            uid = int(uid_str)
        except Exception:
            continue
        if data.get("review_bonus") is True:
            USER_REVIEW_BONUS_AWARDED.add(uid)
            USER_FIRST_REVIEW_SUBMITTED.add(uid)
        elif data.get("first_review_submitted") is True:
            USER_FIRST_REVIEW_SUBMITTED.add(uid)
            # Если первый отзыв отправлен, но бонус еще не начислен - он на рассмотрении
            USER_PENDING_REVIEW_USERS.add(uid)

        unanswered = data.get("unanswered_reviews", 0)
        if unanswered > 0:
            USER_UNANSWERED_REVIEWS[uid] = unanswered
            USER_PENDING_REVIEW_USERS.add(uid)

init_review_state()

def has_user_received_review_bonus(user_id: int) -> bool:
    """Проверка: получал ли данный пользователь бонус за отзыв ранее."""
    if user_id in USER_REVIEW_BONUS_AWARDED:
        return True
    rewards = load_review_rewards()
    rec = rewards.get(str(user_id))
    if rec and rec.get("review_bonus") is True:
        USER_REVIEW_BONUS_AWARDED.add(user_id)
        return True
    return False

def has_user_submitted_first_review(user_id: int) -> bool:
    """Проверка: отправлял ли пользователь первый отзыв (или получал ли уже бонус)."""
    if user_id in USER_FIRST_REVIEW_SUBMITTED or user_id in USER_REVIEW_BONUS_AWARDED:
        return True
    rewards = load_review_rewards()
    rec = rewards.get(str(user_id))
    if rec and (rec.get("review_bonus") is True or rec.get("first_review_submitted") is True):
        USER_FIRST_REVIEW_SUBMITTED.add(user_id)
        return True
    return False

def is_user_review_pending(user_id: int) -> bool:
    """
    Проверка: ожидает ли отзыв пользователя ответа/проверки администратора прямо сейчас.
    Блокирует отправку любых новых отзывов до решения/ответа админа.
    """
    if user_id in USER_PENDING_REVIEW_USERS:
        return True
    if get_user_unanswered_reviews(user_id) >= 1:
        return True
    if has_user_submitted_first_review(user_id) and not has_user_received_review_bonus(user_id):
        return True
    return False

def mark_user_first_review_submitted(user_id: int):
    """Фиксация отправки первого отзыва пользователем с защитой от повторного спама."""
    USER_FIRST_REVIEW_SUBMITTED.add(user_id)
    USER_PENDING_REVIEW_USERS.add(user_id)
    USER_UNANSWERED_REVIEWS[user_id] = 1
    rewards = load_review_rewards()
    uid = str(user_id)
    rec = rewards.get(uid, {
        "telegram_id": user_id,
        "extra_bonus_days": 0,
        "extra_bonuses": []
    })
    rec["first_review_submitted"] = True
    rec["first_review_at"] = datetime.now(timezone.utc).isoformat()
    rec["unanswered_reviews"] = 1
    if "review_bonus" not in rec:
        rec["review_bonus"] = False
    rewards[uid] = rec
    save_review_rewards(rewards)

    # Безопасная синхронизация с Supabase (если колонка first_review_submitted добавлена в app_users)
    try:
        supabase.table('app_users').update({'first_review_submitted': True}).eq('telegram_id', user_id).execute()
    except Exception:
        pass

def get_user_unanswered_reviews(user_id: int) -> int:
    """Количество неотвеченных повторных отзывов пользователя (лимит 1)."""
    if user_id in USER_UNANSWERED_REVIEWS:
        return USER_UNANSWERED_REVIEWS[user_id]
    rewards = load_review_rewards()
    rec = rewards.get(str(user_id), {})
    cnt = rec.get("unanswered_reviews", 0)
    USER_UNANSWERED_REVIEWS[user_id] = cnt
    return cnt

def increment_user_unanswered_reviews(user_id: int) -> int:
    """Увеличение счетчика неотвеченных повторных отзывов."""
    cnt = get_user_unanswered_reviews(user_id) + 1
    USER_UNANSWERED_REVIEWS[user_id] = cnt
    USER_PENDING_REVIEW_USERS.add(user_id)
    rewards = load_review_rewards()
    uid = str(user_id)
    rec = rewards.get(uid, {
        "telegram_id": user_id,
        "extra_bonus_days": 0,
        "extra_bonuses": []
    })
    rec["unanswered_reviews"] = cnt
    rewards[uid] = rec
    save_review_rewards(rewards)
    return cnt

def reset_user_unanswered_reviews(user_id: int):
    """Сброс счетчика неотвеченных отзывов (когда админ ответил пользователю или начислил бонус)."""
    USER_UNANSWERED_REVIEWS[user_id] = 0
    USER_PENDING_REVIEW_USERS.discard(user_id)
    rewards = load_review_rewards()
    uid = str(user_id)
    if uid in rewards:
        rewards[uid]["unanswered_reviews"] = 0
        save_review_rewards(rewards)

def get_user_bonus_summary(user_id: int) -> dict:
    """Полная сводка бонусов пользователя: отзыв (+7) и доп. компенсации (+3)."""
    rewards = load_review_rewards()
    rec = rewards.get(str(user_id), {})
    has_review = bool(rec.get("review_bonus", False) or user_id in USER_REVIEW_BONUS_AWARDED)
    first_submitted = bool(rec.get("first_review_submitted", False) or user_id in USER_FIRST_REVIEW_SUBMITTED)
    extra_days = rec.get("extra_bonus_days", 0)
    extra_history = rec.get("extra_bonuses", [])
    return {
        "has_review_bonus": has_review,
        "first_review_submitted": first_submitted,
        "review_awarded_at": rec.get("awarded_at"),
        "review_awarded_by": rec.get("awarded_by_name"),
        "extra_days": extra_days,
        "extra_count": len(extra_history),
        "extra_history": extra_history
    }

def record_user_review_bonus(user_id: int, admin_id: int, admin_name: str, days: int = 7) -> dict:
    """Фиксация выданного бонуса за отзыв во избежание повторного начисления."""
    USER_REVIEW_BONUS_AWARDED.add(user_id)
    USER_FIRST_REVIEW_SUBMITTED.add(user_id)
    USER_PENDING_REVIEW_USERS.discard(user_id)
    USER_UNANSWERED_REVIEWS[user_id] = 0
    rewards = load_review_rewards()
    uid = str(user_id)
    rec = rewards.get(uid, {
        "telegram_id": user_id,
        "extra_bonus_days": 0,
        "extra_bonuses": []
    })
    rec["review_bonus"] = True
    rec["first_review_submitted"] = True
    rec["unanswered_reviews"] = 0
    rec["awarded_at"] = datetime.now(timezone.utc).isoformat()
    rec["awarded_by_id"] = admin_id
    rec["awarded_by_name"] = admin_name
    rec["days_added"] = days
    rewards[uid] = rec
    save_review_rewards(rewards)

    # Безопасная синхронизация с Supabase (если колонки существуют)
    try:
        supabase.table('app_users').update({'review_bonus': True, 'first_review_submitted': True}).eq('telegram_id', user_id).execute()
    except Exception:
        pass

    return rec

def record_user_extra_bonus(user_id: int, admin_id: int, admin_name: str, days: int = 3, reason: str = "Особый случай / компенсация") -> int:
    """
    Фиксация начисления дополнительного бонуса (напр. +3 дня при косяках / для радости)
    и инкремент общего счетчика выданных бонусных дней сверх отзыва.
    Возвращает суммарное количество выданных доп. бонусных дней.
    """
    rewards = load_review_rewards()
    uid = str(user_id)
    rec = rewards.get(uid, {
        "telegram_id": user_id,
        "review_bonus": False,
        "extra_bonus_days": 0,
        "extra_bonuses": []
    })
    current_extra = rec.get("extra_bonus_days", 0) + days
    rec["extra_bonus_days"] = current_extra
    if "extra_bonuses" not in rec:
        rec["extra_bonuses"] = []
    rec["extra_bonuses"].append({
        "days": days,
        "awarded_at": datetime.now(timezone.utc).isoformat(),
        "awarded_by_id": admin_id,
        "awarded_by_name": admin_name,
        "reason": reason
    })
    rewards[uid] = rec
    save_review_rewards(rewards)
    return current_extra

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


async def check_channel_subscription(bot_instance: Bot, user_id: int) -> bool:
    """
    Проверка подписки пользователя на Telegram-канал.
    Для публичных каналов бот проверяет членство по юзернейму @channel или числовому ID.
    """
    target_chat = CHANNEL_ID if CHANNEL_ID else f"@{CHANNEL_USERNAME}"
    try:
        member = await bot_instance.get_chat_member(chat_id=target_chat, user_id=user_id)
        if member.status in ("creator", "administrator", "member"):
            return True
        if member.status == "restricted" and getattr(member, 'is_member', True):
            return True
        return False
    except Exception as e:
        print(f"⚠️ Проверка подписки на канал {target_chat} для {user_id}: {e}")
        return False


def generate_access_code() -> str:
    """Генерация надежного уникального токена доступа формата dl_..."""
    return f"dl_{secrets.token_hex(12)}"


def parse_iso_datetime(dt_str: str):
    """Безопасный парсинг даты из ISO-формата Supabase с поддержкой временных зон."""
    if not dt_str:
        return None
    s = str(dt_str).replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        for fmt in ('%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
            try:
                dt = datetime.strptime(s, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                continue
    return None


USER_CACHE: dict[int, tuple[float, dict]] = {}

def invalidate_user_cache(tg_id: int):
    """Сброс локального кэша пользователя."""
    USER_CACHE.pop(tg_id, None)


def get_user_from_db(tg_id: int, force: bool = False):
    """Получение профиля пользователя из базы Supabase с быстрым кэшированием."""
    now = datetime.now(timezone.utc).timestamp()
    if not force and tg_id in USER_CACHE:
        cached_time, cached_data = USER_CACHE[tg_id]
        if (now - cached_time) < 15.0:
            return cached_data

    try:
        res = supabase.table('app_users').select('*').eq('telegram_id', tg_id).execute()
        if res.data and len(res.data) > 0:
            user = res.data[0]
            USER_CACHE[tg_id] = (now, user)
            return user
    except Exception as e:
        print(f"Ошибка запроса пользователя {tg_id}: {e}")
    return None


def is_user_banned(user: dict | None) -> bool:
    """Проверка, заблокирован ли пользователь администратором."""
    if not user:
        return False
    plan = str(user.get('plan') or '').lower()
    return plan == 'banned' or user.get('is_banned') is True


BANNED_MESSAGE = (
    "⛔️ <b>Ваш аккаунт заблокирован</b>\n\n"
    "Доступ к функциям бота, закрытой интерактивной карте и службе заботы ограничен администратором.\n\n"
    f"Если вы считаете, что блокировка произошла по ошибке, вы можете обратиться к автору проекта: @{ADMIN_USERNAME}"
)


# -------------------------------------------------------------
# ЗАЩИТА ОТ СПАМА В СЛУЖБУ ПОДДЕРЖКИ
# Ограничение: до 3 сообщений подряд без ответа администратора
# -------------------------------------------------------------
SUPPORT_UNANSWERED_COUNT: dict[int, int] = {}

def get_user_unanswered_support(user_id: int) -> int:
    return SUPPORT_UNANSWERED_COUNT.get(user_id, 0)

def increment_user_unanswered_support(user_id: int) -> int:
    cnt = SUPPORT_UNANSWERED_COUNT.get(user_id, 0) + 1
    SUPPORT_UNANSWERED_COUNT[user_id] = cnt
    return cnt

def reset_user_unanswered_support(user_id: int):
    SUPPORT_UNANSWERED_COUNT[user_id] = 0


def get_or_create_user(tg_user: types.User):
    """Получить существующего или создать нового пользователя."""
    user = get_user_from_db(tg_user.id)
    if user:
        # Если у старого пользователя нет токена — сгенерируем
        if not user.get('access_token'):
            token = generate_access_code()
            try:
                supabase.table('app_users').update({'access_token': token}).eq('telegram_id', tg_user.id).execute()
                user['access_token'] = token
                invalidate_user_cache(tg_user.id)
            except Exception as e:
                print(f"Ошибка обновления токена: {e}")
        return user

    # Создаем нового пользователя с тарифом 'trial' без даты истечения (требуется активация 7-дневного trial)
    token = generate_access_code()
    new_user = {
        'telegram_id': tg_user.id,
        'username': tg_user.username or '',
        'first_name': tg_user.first_name or 'Пользователь',
        'plan': 'trial',
        'expires_at': None,
        'access_token': token,
        'devices': [],
        'max_devices': 3,
        'favorites': []
    }
    try:
        res_insert = supabase.table('app_users').insert([new_user]).execute()
        created = res_insert.data[0] if res_insert.data else new_user
        invalidate_user_cache(tg_user.id)
        return created
    except Exception as e:
        print(f"Ошибка создания пользователя в Supabase: {e}")
        return new_user


def check_subscription_status(user: dict) -> dict:
    """
    Комплексная проверка статуса подписки пользователя.
    Иерархия уровней:
    - Уровень 0: Trial (пробный доступ 7 дней)
    - Уровень 1: Premium (основной платный тариф)
    - Уровень 2: Platinum (высший уровень), Supporter (ручной высший уровень), Lifetime (бессрочный высший уровень)
    """
    if not user:
        return {
            'has_access': False,
            'is_expired': False,
            'not_activated': True,
            'plan': 'trial',
            'tier_level': 0,
            'status_title': 'Trial (Не активирован)',
            'badge': '🎁 Trial не активирован',
            'days_left': 0,
            'date_str': '—'
        }

    raw_plan = (user.get('plan') or 'trial').lower()
    if raw_plan == 'banned' or user.get('is_banned') is True:
        return {
            'has_access': False,
            'is_expired': True,
            'not_activated': False,
            'is_banned': True,
            'plan': 'banned',
            'tier_level': 0,
            'status_title': '⛔️ Заблокирован',
            'badge': '⛔️ Аккаунт заблокирован',
            'days_left': 0,
            'date_str': 'Блокировка'
        }

    if raw_plan == 'free':
        plan = 'trial'
    elif raw_plan == 'vip':
        plan = 'premium'
    else:
        plan = raw_plan
    
    # Постоянный доступ (LIFETIME)
    if plan == 'lifetime' or user.get('is_lifetime') is True:
        return {
            'has_access': True,
            'is_expired': False,
            'not_activated': False,
            'plan': 'lifetime',
            'tier_level': 2,
            'status_title': 'LIFETIME (Навсегда ♾️)',
            'badge': '♾️ LIFETIME',
            'days_left': 9999,
            'date_str': 'Бессрочно'
        }

    expires_at_raw = user.get('expires_at') or user.get('access_until')
    
    # Ручной тариф Supporter
    if plan == 'supporter' and not expires_at_raw:
        return {
            'has_access': True,
            'is_expired': False,
            'not_activated': False,
            'plan': 'supporter',
            'tier_level': 2,
            'status_title': 'SUPPORTER 🌟',
            'badge': '🌟 Supporter',
            'days_left': 9999,
            'date_str': 'Бессрочно'
        }

    # Если дата не задана и это не lifetime/supporter — пробный период еще не активирован
    if not expires_at_raw:
        return {
            'has_access': False,
            'is_expired': False,
            'not_activated': True,
            'plan': plan,
            'tier_level': 0,
            'status_title': 'Trial (7 дней бесплатно)',
            'badge': '🎁 Доступно 7 дней Trial',
            'days_left': 0,
            'date_str': 'Не активирован'
        }

    exp_dt = parse_iso_datetime(expires_at_raw)
    if not exp_dt:
        return {
            'has_access': False,
            'is_expired': False,
            'not_activated': True,
            'plan': plan,
            'tier_level': 0,
            'status_title': 'Не активирован',
            'badge': '🎁 Доступно 7 дней Trial',
            'days_left': 0,
            'date_str': '—'
        }

    now = datetime.now(timezone.utc)
    diff = exp_dt - now
    date_str = exp_dt.strftime('%d.%m.%Y')

    # Срок истёк
    if diff.total_seconds() <= 0:
        tier = 2 if plan in ('platinum', 'supporter') else (1 if plan == 'premium' else 0)
        plan_titles = {
            'platinum': 'PLATINUM 💎',
            'supporter': 'SUPPORTER 🌟',
            'premium': 'PREMIUM ✨',
            'trial': 'Trial 🎁'
        }
        return {
            'has_access': False,
            'is_expired': True,
            'not_activated': False,
            'plan': plan,
            'tier_level': tier,
            'status_title': plan_titles.get(plan, 'PREMIUM ✨'),
            'badge': f'🔴 Истёк ({date_str})',
            'days_left': 0,
            'date_str': f'Истёк {date_str}'
        }

    # Подписка активна
    days_left = max(1, diff.days + 1)
    if plan == 'trial':
        title = 'Trial 🎁 (7 дней)'
        badge = f'🎁 Trial ({days_left} дн.)'
        tier = 0
    elif plan == 'platinum':
        title = 'PLATINUM 💎'
        badge = f'💎 Platinum ({days_left} дн.)'
        tier = 2
    elif plan == 'supporter':
        title = 'SUPPORTER 🌟'
        badge = f'🌟 Supporter ({days_left} дн.)'
        tier = 2
    elif plan == 'premium':
        title = 'PREMIUM ✨'
        badge = f'✨ Premium ({days_left} дн.)'
        tier = 1
    else:
        title = 'PREMIUM ✨'
        badge = f'🟢 Активна ({days_left} дн.)'
        tier = 1

    return {
        'has_access': True,
        'is_expired': False,
        'not_activated': False,
        'plan': plan,
        'tier_level': tier,
        'status_title': title,
        'badge': badge,
        'days_left': days_left,
        'date_str': date_str
    }


USER_ACTIVE_MENU: dict[int, int] = {}  # chat_id -> message_id


async def send_menu_message(
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup = None,
    trigger_message: types.Message = None,
    disable_web_page_preview: bool = True
) -> types.Message:
    """
    Отправляет сообщение с меню в самый низ чата, автоматически удаляя или закрывая клавиатуру
    предыдущего меню и сообщения-источника нажатия (если переход был сделан из сообщения выше по чату).
    Это гарантирует, что меню всегда следует строго внизу по логике сообщений и не застревает над ответами.
    """
    to_clean_ids = set()
    old_msg_id = USER_ACTIVE_MENU.get(chat_id)
    if old_msg_id:
        to_clean_ids.add(old_msg_id)
    if trigger_message and trigger_message.message_id:
        to_clean_ids.add(trigger_message.message_id)

    for mid in to_clean_ids:
        is_preserved = False
        if trigger_message and trigger_message.message_id == mid:
            txt = trigger_message.text or trigger_message.caption or ""
            if (
                "Большое спасибо за ваш отзыв" in txt
                or "Ваш вопрос передан" in txt
                or "Сообщение успешно передано" in txt
                or "Ответ службы поддержки" in txt
                or "Рады были помочь" in txt
            ):
                is_preserved = True

        if is_preserved:
            try:
                await bot.edit_message_reply_markup(chat_id=chat_id, message_id=mid, reply_markup=None)
            except Exception:
                pass
        else:
            try:
                await bot.delete_message(chat_id=chat_id, message_id=mid)
            except Exception:
                try:
                    await bot.edit_message_reply_markup(chat_id=chat_id, message_id=mid, reply_markup=None)
                except Exception:
                    pass

    msg = await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=disable_web_page_preview
    )
    if reply_markup:
        USER_ACTIVE_MENU[chat_id] = msg.message_id
    else:
        USER_ACTIVE_MENU.pop(chat_id, None)
    return msg


def build_main_keyboard(user: dict, sub_info: dict) -> InlineKeyboardMarkup:
    """
    Построение эргономичной клавиатуры главного меню:
    - Кнопка карты (WebApp)
    - Двойная кнопка в 1 строку: [💎 Подписка] и [📱 Сессии: X/Y]
    - Установка веб-приложения (iPhone / Android)
    - Частые вопросы & Поддержка
    - Ссылка на канал
    """
    devices = user.get('devices') or []
    max_devices = user.get('max_devices', 3)
    cur_sessions = len(devices)

    sessions_label = f"📱 Сессии: {cur_sessions}/{max_devices}"
    if cur_sessions >= max_devices:
        sessions_label = f"⚠️ Сессии: {cur_sessions}/{max_devices}"

    keyboard = [
        # 1. Главная кнопка открытия карты
        [InlineKeyboardButton(text="🗺️ Открыть карту в Telegram", web_app=WebAppInfo(url=WEBAPP_URL))],
        # 2. Двойная кнопка: статус подписки и счетчик сессий
        [
            InlineKeyboardButton(text="💎 Подписка", callback_data="menu_subscription"),
            InlineKeyboardButton(text=sessions_label, callback_data="menu_sessions")
        ],
        # 3. Инструкция для установки PWA веб-приложения (iPhone + Android)
        [InlineKeyboardButton(text="📲 Установить веб-приложение", callback_data="show_pwa_guide")],
        # 4. Предложить классную локацию в гид
        [InlineKeyboardButton(text="💌 Предложить локацию в гид", callback_data="suggest_location")],
        # 5. Частые вопросы и Поддержка
        [InlineKeyboardButton(text="❓ Частые вопросы & Поддержка", callback_data="menu_faq")],
        # 6. Канал автора
        [InlineKeyboardButton(text=f"📢 Канал @{CHANNEL_USERNAME}", url=CHANNEL_URL)]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


# -------------------------------------------------------------
# ХЕНДЛЕРЫ
# -------------------------------------------------------------

@dp.message(CommandStart())
@dp.message(Command("menu"))
@dp.message(Command("suggest"))
async def start_handler(message: types.Message):
    tg_user = message.from_user
    user = get_or_create_user(tg_user)
    first_name = tg_user.first_name or "друг"
    sub_info = check_subscription_status(user)

    cmd_text = (message.text or "").strip().lower()
    if cmd_text == "/suggest" or "suggest" in cmd_text:
        await suggest_location_handler(message)
        return

    # 1. Новый пользователь / Пробный период еще не активирован
    if sub_info['not_activated']:
        text = (
            f"Привет, <b>{first_name}</b>! ✨\n\n"
            f"Добро пожаловать в персональный гид по эстетичным кофейням, секретным дворикам, музеям и фото-спотам Москвы от <b>@{CHANNEL_USERNAME}</b> 📍\n\n"
            f"Внутри приложения:\n"
            f"▫️ <b>Интерактивная карта</b> с фильтрами по категориям и веткам метро\n"
            f"▫️ <b>Списки избранного</b>, быстрый поиск и прокладка маршрутов в один клик\n"
            f"▫️ <b>Авторские описания</b>, рекомендации и фото к каждой локации\n\n"
            f"🎁 <b>Вам доступен бесплатный пробный доступ на 7 дней за подписку на наш канал!</b>\n\n"
            f"1. Подпишитесь на канал <b>@{CHANNEL_USERNAME}</b> 📢\n"
            f"2. Нажмите кнопку <b>«Проверить подписку и активировать»</b> ниже — и карта сразу откроется!"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"📢 1. Подписаться на канал @{CHANNEL_USERNAME}", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="🎁 2. Проверить подписку и активировать", callback_data="activate_trial")],
            [InlineKeyboardButton(text="📍 Что внутри гида?", callback_data="about_guide")],
            [InlineKeyboardButton(text="💌 Предложить локацию в гид", callback_data="suggest_location")],
            [InlineKeyboardButton(text="❓ Частые вопросы & Поддержка", callback_data="menu_faq")]
        ])
        await send_menu_message(message.chat.id, text, reply_markup=kb)
        return

    # 2. Срок подписки или пробного периода истёк
    if sub_info['is_expired']:
        text = (
            f"Привет, <b>{first_name}</b>! ✨\n\n"
            f"⏳ <b>Срок действия вашего пробного периода (или подписки) истёк.</b>\n"
            f"Доступ к интерактивной карте закрыт 🔒\n\n"
            f"Чтобы продолжить пользоваться полным каталогом локаций, уютных кофеен и фото-спотов Москвы от <b>@{CHANNEL_USERNAME}</b>, оформите постоянную подписку ✨"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Продлить доступ / Купить подписку", url=f"https://t.me/{ADMIN_USERNAME}")],
            [InlineKeyboardButton(text="💎 Детали подписки", callback_data="menu_subscription")],
            [InlineKeyboardButton(text="💌 Предложить локацию в гид", callback_data="suggest_location")],
            [InlineKeyboardButton(text="❓ Частые вопросы & Поддержка", callback_data="menu_faq")],
            [InlineKeyboardButton(text=f"📢 Канал @{CHANNEL_USERNAME}", url=CHANNEL_URL)]
        ])
        await send_menu_message(message.chat.id, text, reply_markup=kb)
        return

    # 3. Активный пользователь
    text = (
        f"Привет, <b>{first_name}</b>! ✨\n\n"
        f"Добро пожаловать в гид по лучшим локациям Москвы от <b>@{CHANNEL_USERNAME}</b> 📍\n\n"
        f"Нажмите кнопку <b>«🗺️ Открыть карту в Telegram»</b> ниже, чтобы перейти к интерактивной карте и подборкам мест!"
    )
    kb = build_main_keyboard(user, sub_info)
    await send_menu_message(message.chat.id, text, reply_markup=kb)


@dp.callback_query(F.data == "activate_trial")
async def activate_trial_handler(callback: types.CallbackQuery):
    tg_user = callback.from_user
    user = get_or_create_user(tg_user)
    sub_info = check_subscription_status(user)

    if not sub_info['not_activated']:
        if sub_info['has_access']:
            await callback.answer("✅ У вас уже есть активная подписка!", show_alert=True)
        else:
            await callback.answer("⚠️ Пробный период уже был активирован ранее.", show_alert=True)
        return

    # Проверяем подписку на Telegram-канал
    is_sub = await check_channel_subscription(callback.bot, tg_user.id)
    if not is_sub:
        text_not_sub = (
            f"⚠️ <b>Подписка на канал @{CHANNEL_USERNAME} не найдена!</b>\n\n"
            f"🎁 Бесплатный пробный период на 7 дней доступен <b>только подписчикам канала</b>.\n\n"
            f"<b>Как активировать доступ:</b>\n"
            f"1. Перейдите в канал по кнопке ниже и нажмите <b>«Подписаться»</b>.\n"
            f"2. Затем вернитесь сюда и нажмите <b>«Проверить подписку и активировать»</b>."
        )
        kb_not_sub = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"📢 1. Подписаться на канал @{CHANNEL_USERNAME}", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="🔄 2. Проверить подписку и активировать", callback_data="activate_trial")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_start")]
        ])
        await send_menu_message(
            callback.message.chat.id,
            text_not_sub,
            reply_markup=kb_not_sub,
            trigger_message=callback.message
        )
        await callback.answer("⚠️ Сначала подпишитесь на канал!", show_alert=True)
        return

    # Подписка подтверждена — активируем 7 дней с текущего момента
    now = datetime.now(timezone.utc)
    exp_dt = now + timedelta(days=7)
    exp_iso = exp_dt.isoformat()

    try:
        supabase.table('app_users').update({
            'plan': 'trial',
            'expires_at': exp_iso,
            'devices': []
        }).eq('telegram_id', tg_user.id).execute()

        user['plan'] = 'trial'
        user['expires_at'] = exp_iso
        user['devices'] = []
    except Exception as e:
        print(f"Ошибка активации триала: {e}")
        await callback.answer("Ошибка при активации. Попробуйте еще раз.", show_alert=True)
        return

    await callback.answer("🎉 Спасибо за подписку! 7 дней активированы!", show_alert=False)

    date_str = exp_dt.strftime('%d.%m.%Y')
    text = (
        f"🎉 <b>Спасибо за подписку на канал!</b>\n\n"
        f"🎁 <b>Пробный период на 7 дней успешно активирован!</b>\n\n"
        f"🗓 Доступ открыт до: <b>{date_str}</b> (7 дней)\n\n"
        f"Вам открыты все локации, фильтры по линиям метро, режим «Рядом со мной» и персональное избранное ❤️\n\n"
        f"Открывайте карту прямо сейчас внутри Telegram или используйте как веб-приложение на смартфоне и ПК!"
    )
    updated_sub = check_subscription_status(user)
    kb = build_main_keyboard(user, updated_sub)
    await send_menu_message(
        callback.message.chat.id,
        text,
        reply_markup=kb,
        trigger_message=callback.message
    )


@dp.callback_query(F.data == "about_guide")
async def about_guide_handler(callback: types.CallbackQuery):
    text = (
        f"📍 <b>О гиде локаций @{CHANNEL_USERNAME}:</b>\n\n"
        f"Это интерактивная карта Москвы, собранная вручную с любовью к эстетике:\n\n"
        f"☕ <b>Кофейни & Завтраки:</b> спешелти-кофе, выпечка, лучший маття и красивые веранды.\n"
        f"📸 <b>Фото-споты:</b> секретные ракурсы, эстетичные дворики и атмосферные локации.\n"
        f"🏛 <b>Культура & Прогулки:</b> выставки, парки, старинные особняки и тихие переулки.\n"
        f"⚡ <b>Удобства:</b> поиск ближайших мест к вам, фильтрация по станциям метро и линиям, добавление в избранное."
    )
    user = get_or_create_user(callback.from_user)
    sub_info = check_subscription_status(user)

    if sub_info['not_activated']:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"📢 1. Подписаться на канал @{CHANNEL_USERNAME}", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="🎁 2. Проверить и активировать 7 дней", callback_data="activate_trial")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_start")]
        ])
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Главное меню", callback_data="back_to_start")]
        ])

    await send_menu_message(
        callback.message.chat.id,
        text,
        reply_markup=kb,
        trigger_message=callback.message
    )
    await callback.answer()


@dp.callback_query(F.data == "menu_subscription")
async def subscription_info_handler(callback: types.CallbackQuery):
    user = get_or_create_user(callback.from_user)
    sub_info = check_subscription_status(user)
    max_devices = user.get('max_devices', 3)
    cur_devices = len(user.get('devices') or [])

    if sub_info['is_expired']:
        date_label = f"Истёк ({sub_info['date_str'].replace('Истёк ', '')})"
    elif sub_info['not_activated']:
        date_label = "Не активирован"
    elif sub_info['date_str'] in ('Бессрочно', 'Бессрочно (Ручной)', 'Навсегда'):
        date_label = "Бессрочно ♾️"
    else:
        days = sub_info.get('days_left', 0)
        date_label = f"до {sub_info['date_str']} ({days} дн.)"

    text = (
        f"💎 <b>Информация о подписке:</b>\n\n"
        f"• <b>Тариф:</b> {sub_info['status_title']}\n"
        f"• <b>Срок действия:</b> {date_label}\n"
        f"• <b>Лимит сессий:</b> <b>{cur_devices} из {max_devices}</b>\n\n"
        f"💳 <i>По вопросам продления доступа или перехода на постоянный тариф напишите автору:</i>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Продлить / Купить подписку", url=f"https://t.me/{ADMIN_USERNAME}")],
        [InlineKeyboardButton(text="📱 Управление сессиями", callback_data="menu_sessions")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="back_to_start")]
    ])

    await send_menu_message(
        callback.message.chat.id,
        text,
        reply_markup=kb,
        trigger_message=callback.message
    )
    await callback.answer()


@dp.callback_query(F.data == "menu_sessions")
async def sessions_menu_handler(callback: types.CallbackQuery):
    tg_user = callback.from_user
    user = get_or_create_user(tg_user)
    token = user.get('access_token')

    # Загружаем свежие устройства
    fresh_user = get_user_from_db(tg_user.id) or user
    devices = fresh_user.get('devices') or []
    max_devices = fresh_user.get('max_devices', 3)
    cur_sessions = len(devices)

    direct_url = f"{WEBAPP_URL}?token={token}"

    limit_warning = ""
    if cur_sessions >= max_devices:
        limit_warning = (
            "⚠️ <b>Внимание: лимит сессий исчерпан!</b>\n"
            "Чтобы войти с нового устройства или браузера, нажмите кнопку <b>«Сбросить сессии»</b> ниже.\n\n"
        )

    text = (
        f"📱 <b>Управление сессиями (устройствами):</b>\n\n"
        f"• <b>Активных сессий:</b> <b>{cur_sessions} из {max_devices}</b>\n"
        f"{limit_warning}"
        f"Каждая сессия — это браузер или устройство, где вы открывали карту (Safari на iPhone, Chrome на ПК и т.д.).\n\n"
        f"🔑 <b>Ваш персональный ключ:</b>\n"
        f"<code>{token}</code>\n"
        f"<i>(нажмите на код для копирования)</i>\n\n"
        f"🔗 <b>Прямая ссылка для входа в 1 клик через браузер:</b>\n"
        f"<code>{direct_url}</code>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧭 Открыть в браузере / ПК", url=direct_url)],
        [InlineKeyboardButton(text=f"🔄 Сбросить сессии ({cur_sessions})", callback_data="reset_devices")],
        [InlineKeyboardButton(text="📲 Установить веб-приложение", callback_data="show_pwa_guide")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="back_to_start")]
    ])

    await send_menu_message(
        callback.message.chat.id,
        text,
        reply_markup=kb,
        trigger_message=callback.message,
        disable_web_page_preview=True
    )
    await callback.answer()


@dp.callback_query(F.data == "reset_devices")
async def reset_devices_handler(callback: types.CallbackQuery):
    try:
        supabase.table('app_users').update({'devices': []}).eq('telegram_id', callback.from_user.id).execute()
    except Exception as e:
        print(f"Ошибка сброса сессий: {e}")

    await callback.answer("✅ Все активные сессии успешно сброшены!", show_alert=True)

    # Перезагружаем меню сессий с обновленным счетчиком (0 из N)
    user = get_or_create_user(callback.from_user)
    user['devices'] = []
    token = user.get('access_token')
    max_devices = user.get('max_devices', 3)
    direct_url = f"{WEBAPP_URL}?token={token}"

    text = (
        f"📱 <b>Управление сессиями (устройствами):</b>\n\n"
        f"• <b>Активных сессий:</b> <b>0 из {max_devices}</b> (список очищен ✅)\n\n"
        f"Теперь вы можете свободно открыть карту на любом новом устройстве или компьютере.\n\n"
        f"🔑 <b>Ваш ключ:</b> <code>{token}</code>\n\n"
        f"🔗 <b>Прямая ссылка для входа:</b>\n<code>{direct_url}</code>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧭 Открыть в браузере / ПК", url=direct_url)],
        [InlineKeyboardButton(text="📲 Установить веб-приложение", callback_data="show_pwa_guide")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="back_to_start")]
    ])

    await send_menu_message(
        callback.message.chat.id,
        text,
        reply_markup=kb,
        trigger_message=callback.message,
        disable_web_page_preview=True
    )


@dp.message(Command("pwa"))
@dp.message(Command("ios"))
@dp.callback_query(F.data.in_(["show_pwa_guide", "show_ios_pwa_guide", "faq_pwa"]))
async def pwa_guide_handler(event: types.Message | types.CallbackQuery):
    tg_user = event.from_user
    user = get_or_create_user(tg_user)
    token = user.get('access_token')
    direct_url = f"{WEBAPP_URL}?token={token}"

    text = (
        f"📱 <b>Как установить веб-приложение на экран смартфона:</b>\n\n"
        f"<b>🍏 На iPhone (Apple Safari):</b>\n"
        f"1. Перейдите по вашей персональной ссылке в браузере <b>Safari</b>:\n"
        f"👉 <code>{direct_url}</code>\n"
        f"<i>(нажмите на ссылку выше для копирования или используйте кнопку ниже)</i>\n\n"
        f"2. Внизу экрана Safari нажмите кнопку <b>«Поделиться»</b> (квадрат со стрелочкой вверх ⎋).\n\n"
        f"3. В открывшемся меню выберите <b>«На экран „Домой“»</b> ➔ в правом верхнем углу нажмите <b>«Добавить»</b>.\n\n"
        f"<b>🤖 На Android (Google Chrome / Яндекс):</b>\n"
        f"1. Откройте персональную ссылку в браузере Chrome или Яндекс:\n"
        f"👉 <code>{direct_url}</code>\n\n"
        f"2. Нажмите на три точки <b>⋮</b> в верхнем правом углу браузера.\n\n"
        f"3. Выберите <b>«Добавить на главный экран»</b> или <b>«Установить приложение»</b>.\n\n"
        f"✨ <i>Иконка появится на рабочем столе и будет запускаться сразу на весь экран без рамок браузера и без повторного ввода ключей!</i>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧭 Открыть персональную ссылку", url=direct_url)],
        [InlineKeyboardButton(text="💬 Задать вопрос поддержке", callback_data="contact_support")],
        [InlineKeyboardButton(text="◀️ Назад к вопросам", callback_data="menu_faq")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
    ])

    if isinstance(event, types.CallbackQuery):
        await send_menu_message(
            event.message.chat.id,
            text,
            reply_markup=kb,
            trigger_message=event.message,
            disable_web_page_preview=True
        )
        await event.answer()
    else:
        await send_menu_message(event.chat.id, text, reply_markup=kb, disable_web_page_preview=True)


@dp.message(Command("web"))
@dp.message(Command("sessions"))
async def web_command_handler(message: types.Message):
    user = get_or_create_user(message.from_user)
    token = user.get('access_token')
    devices = user.get('devices') or []
    max_devices = user.get('max_devices', 3)
    cur_sessions = len(devices)
    direct_url = f"{WEBAPP_URL}?token={token}"

    text = (
        f"📱 <b>Управление сессиями (устройствами):</b>\n\n"
        f"• <b>Активных сессий:</b> <b>{cur_sessions} из {max_devices}</b>\n\n"
        f"🔑 <b>Персональный ключ:</b> <code>{token}</code>\n\n"
        f"🔗 <b>Вход в 1 клик через браузер / ПК:</b>\n<code>{direct_url}</code>"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧭 Открыть в браузере", url=direct_url)],
        [InlineKeyboardButton(text=f"🔄 Сбросить сессии ({cur_sessions})", callback_data="reset_devices")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="back_to_start")]
    ])
    await send_menu_message(message.chat.id, text, reply_markup=kb)


@dp.callback_query(F.data == "back_to_start")
async def back_to_start_handler(callback: types.CallbackQuery):
    user = get_or_create_user(callback.from_user)
    first_name = callback.from_user.first_name or "друг"
    sub_info = check_subscription_status(user)

    if sub_info['not_activated']:
        text = (
            f"Привет, <b>{first_name}</b>! ✨\n\n"
            f"Добро пожаловать в персональный гид по лучшим кофейням и локациям Москвы от <b>@{CHANNEL_USERNAME}</b> 📍\n\n"
            f"🎁 <b>Бесплатный пробный доступ на 7 дней выдаётся за подписку на наш канал!</b>\n\n"
            f"Подпишитесь на канал <b>@{CHANNEL_USERNAME}</b> и активируйте 7 дней доступа прямо сейчас."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"📢 1. Подписаться на канал @{CHANNEL_USERNAME}", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="🎁 2. Проверить подписку и активировать", callback_data="activate_trial")],
            [InlineKeyboardButton(text="📍 Что внутри гида?", callback_data="about_guide")],
            [InlineKeyboardButton(text="❓ Частые вопросы & Поддержка", callback_data="menu_faq")]
        ])
    elif sub_info['is_expired']:
        text = (
            f"Привет, <b>{first_name}</b>! ✨\n\n"
            f"⏳ <b>Срок действия пробного периода (или подписки) истёк.</b>\n"
            f"Доступ к интерактивной карте закрыт 🔒\n\n"
            f"Оформите постоянную подписку, чтобы продолжить исследовать лучшие локации Москвы ✨"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Продлить доступ / Купить подписку", url=f"https://t.me/{ADMIN_USERNAME}")],
            [InlineKeyboardButton(text="💎 Детали подписки", callback_data="menu_subscription")],
            [InlineKeyboardButton(text="❓ Частые вопросы & Поддержка", callback_data="menu_faq")],
            [InlineKeyboardButton(text=f"📢 Канал @{CHANNEL_USERNAME}", url=CHANNEL_URL)]
        ])
    else:
        text = (
            f"Привет, <b>{first_name}</b>! ✨\n\n"
            f"Добро пожаловать в гид по лучшим локациям Москвы от <b>@{CHANNEL_USERNAME}</b> 📍\n\n"
            f"Вы можете открыть карту внутри Telegram, установить её как веб-приложение на смартфон или открыть в браузере на ПК."
        )
        kb = build_main_keyboard(user, sub_info)

    await send_menu_message(
        callback.message.chat.id,
        text,
        reply_markup=kb,
        trigger_message=callback.message
    )
    await callback.answer()


# -------------------------------------------------------------
# РАЗДЕЛ FAQ (ЧАСТЫЕ ВОПРОСЫ) И ПОДДЕРЖКА
# -------------------------------------------------------------

@dp.message(Command("faq"))
@dp.message(Command("help"))
@dp.message(Command("support"))
@dp.callback_query(F.data == "menu_faq")
async def menu_faq_handler(event: types.Message | types.CallbackQuery):
    text = (
        f"❓ <b>База знаний и частые вопросы (FAQ)</b>\n\n"
        f"Здесь собраны ответы на самые частые вопросы по интерактивному гиду от <b>@{CHANNEL_USERNAME}</b>.\n\n"
        f"Выберите интересующий вас раздел или задайте вопрос поддержке:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📲 Установить веб-приложение", callback_data="show_pwa_guide")],
        [InlineKeyboardButton(text="💻 Как открыть на компьютере (ПК)", callback_data="faq_pc")],
        [InlineKeyboardButton(text="👥 Сессии и лимит устройств", callback_data="faq_devices")],
        [InlineKeyboardButton(text="💳 Тарифы и покупка доступа", callback_data="faq_payment")],
        [InlineKeyboardButton(text="🎁 Бонус +7 дней за отзыв", callback_data="faq_review")],
        [InlineKeyboardButton(text="🔄 Не загружается карта / белый экран", callback_data="faq_trouble")],
        [InlineKeyboardButton(text="💬 Задать свой вопрос поддержке", callback_data="contact_support")],
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="back_to_start")]
    ])
    if isinstance(event, types.CallbackQuery):
        await send_menu_message(
            event.message.chat.id,
            text,
            reply_markup=kb,
            trigger_message=event.message
        )
        await event.answer()
    else:
        await send_menu_message(event.chat.id, text, reply_markup=kb)


@dp.callback_query(F.data == "faq_pwa")
async def faq_pwa_handler(callback: types.CallbackQuery):
    user = get_or_create_user(callback.from_user)
    token = user.get('access_token')
    direct_url = f"{WEBAPP_URL}?token={token}"
    text = (
        f"📱 <b>Как установить веб-приложение на экран смартфона:</b>\n\n"
        f"<b>🍏 На iPhone (Apple Safari):</b>\n"
        f"1. Перейдите по вашей персональной ссылке в браузере <b>Safari</b>:\n"
        f"👉 <code>{direct_url}</code>\n"
        f"<i>(нажмите на ссылку выше для копирования или используйте кнопку ниже)</i>\n\n"
        f"2. Внизу экрана Safari нажмите кнопку <b>«Поделиться»</b> (квадрат со стрелочкой вверх ⎋).\n\n"
        f"3. В открывшемся меню выберите <b>«На экран „Домой“»</b> ➔ в правом верхнем углу нажмите <b>«Добавить»</b>.\n\n"
        f"<b>🤖 На Android (Google Chrome / Яндекс):</b>\n"
        f"1. Откройте персональную ссылку в браузере Chrome или Яндекс:\n"
        f"👉 <code>{direct_url}</code>\n\n"
        f"2. Нажмите на три точки <b>⋮</b> в верхнем правом углу браузера.\n\n"
        f"3. Выберите <b>«Добавить на главный экран»</b> или <b>«Установить приложение»</b>.\n\n"
        f"✨ <i>Иконка появится на рабочем столе и будет запускаться сразу на весь экран без рамок браузера и без повторного ввода ключей!</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧭 Открыть персональную ссылку", url=direct_url)],
        [InlineKeyboardButton(text="💬 Задать вопрос поддержке", callback_data="contact_support")],
        [InlineKeyboardButton(text="◀️ Назад к вопросам", callback_data="menu_faq")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
    ])
    await send_menu_message(
        callback.message.chat.id,
        text,
        reply_markup=kb,
        trigger_message=callback.message,
        disable_web_page_preview=True
    )
    await callback.answer()


@dp.callback_query(F.data == "faq_pc")
async def faq_pc_handler(callback: types.CallbackQuery):
    user = get_or_create_user(callback.from_user)
    token = user.get('access_token')
    direct_url = f"{WEBAPP_URL}?token={token}"
    text = (
        f"💻 <b>Как открыть карту на компьютере (ПК или Mac):</b>\n\n"
        f"1. Откройте в любом браузере (Chrome, Safari, Edge, Яндекс) вашу персональную ссылку:\n"
        f"👉 <code>{direct_url}</code>\n\n"
        f"2. Либо перейдите на <code>{WEBAPP_URL}</code> и, если сайт запросит код доступа, введите ваш персональный ключ:\n"
        f"🔑 <code>{token}</code>\n\n"
        f"✨ Все метки, избранное и фильтры автоматически синхронизируются!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🧭 Открыть в браузере", url=direct_url)],
        [InlineKeyboardButton(text="💬 Задать вопрос поддержке", callback_data="contact_support")],
        [InlineKeyboardButton(text="◀️ Назад к вопросам", callback_data="menu_faq")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
    ])
    await send_menu_message(
        callback.message.chat.id,
        text,
        reply_markup=kb,
        trigger_message=callback.message,
        disable_web_page_preview=True
    )
    await callback.answer()


@dp.callback_query(F.data == "faq_devices")
async def faq_devices_handler(callback: types.CallbackQuery):
    user = get_or_create_user(callback.from_user)
    max_devices = user.get('max_devices', 3)
    cur_devices = len(user.get('devices') or [])
    text = (
        f"👥 <b>Лимит устройств и управление сессиями:</b>\n\n"
        f"• По умолчанию одна подписка поддерживает до <b>{max_devices} активных устройств</b> одновременно (например, телефон, планшет и ноутбук).\n"
        f"• Сейчас у вас активно: <b>{cur_devices} из {max_devices}</b>.\n\n"
        f"🔄 <b>Что делать при смене телефона или входе с нового браузера:</b>\n"
        f"В любой момент вы можете нажать кнопку <b>«Сбросить сессии»</b> в разделе «📱 Сессии» этого бота. Старые устройства отключатся, и вы сможете войти заново."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Мои сессии", callback_data="menu_sessions")],
        [InlineKeyboardButton(text="💬 Задать вопрос поддержке", callback_data="contact_support")],
        [InlineKeyboardButton(text="◀️ Назад к вопросам", callback_data="menu_faq")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
    ])
    await send_menu_message(
        callback.message.chat.id,
        text,
        reply_markup=kb,
        trigger_message=callback.message
    )
    await callback.answer()


@dp.callback_query(F.data == "faq_payment")
async def faq_payment_handler(callback: types.CallbackQuery):
    text = (
        f"💳 <b>Тарифы и продление доступа:</b>\n\n"
        f"🎁 <b>Пробный доступ:</b> 7 дней бесплатно за подписку на канал @{CHANNEL_USERNAME}.\n\n"
        f"⭐️ <b>Бонус за отзыв:</b> +7 дней за развёрнутый отзыв о гиде и приложении! (начисляется один раз).\n\n"
        f"💎 <b>Доступные варианты подписки:</b>\n"
        f"• Месячный доступ\n"
        f"• Годовой доступ\n\n"
        f"Для оформления или продления напишите напрямую автору гида @{ADMIN_USERNAME} ✨"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Узнать про бонус +7 дней за отзыв", callback_data="faq_review")],
        [InlineKeyboardButton(text=f"💌 Написать Даше (@{ADMIN_USERNAME})", url=f"https://t.me/{ADMIN_USERNAME}")],
        [InlineKeyboardButton(text="💬 Задать вопрос поддержке", callback_data="contact_support")],
        [InlineKeyboardButton(text="◀️ Назад к вопросам", callback_data="menu_faq")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
    ])
    await send_menu_message(
        callback.message.chat.id,
        text,
        reply_markup=kb,
        trigger_message=callback.message
    )
    await callback.answer()


@dp.callback_query(F.data == "faq_review_pending_alert")
async def faq_review_pending_alert_handler(callback: types.CallbackQuery):
    await callback.answer("⏳ Ваш отзыв уже отправлен и ожидает проверки администратором!", show_alert=True)

@dp.callback_query(F.data == "faq_review")
async def faq_review_handler(callback: types.CallbackQuery):
    tg_user = callback.from_user
    user_id = tg_user.id
    already_awarded = has_user_received_review_bonus(user_id)
    already_submitted = has_user_submitted_first_review(user_id)
    is_pending = is_user_review_pending(user_id)

    if already_awarded:
        text = (
            f"🎁 <b>Бонус +7 дней за отзыв о гиде</b>\n\n"
            f"✅ <b>Статус:</b> Бонус +7 дней уже был успешно начислен на ваш аккаунт ранее!\n\n"
            f"Правилами проекта предусмотрено <b>однократное начисление бонуса</b> на один аккаунт, чтобы условия были справедливыми для всех пользователей.\n\n"
            f"Если у вас есть новые впечатления, предложения или пожелания по локациям, вы всегда можете написать нам — мы с радостью всё прочитаем! 💌"
        )
        if is_pending:
            review_btn = InlineKeyboardButton(text="⏳ Отзыв ожидает ответа команды", callback_data="leave_review")
        else:
            review_btn = InlineKeyboardButton(text="✍️ Написать тёплый отзыв", callback_data="leave_review")

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [review_btn],
            [InlineKeyboardButton(text="◀️ Назад к вопросам", callback_data="menu_faq")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
        ])
    elif already_submitted:
        text = (
            f"🎁 <b>Бонус +7 дней за отзыв о гиде</b>\n\n"
            f"⏳ <b>Статус:</b> Ваш первый отзыв уже отправлен и находится на проверке у команды гида!\n\n"
            f"После быстрой проверки администратор начислит вам <b>бонус +7 дней</b> прямо в этом диалоге 🎉\n\n"
            f"<i>(Начисление бонуса за отзыв происходит один раз на аккаунт. Дождитесь решения команды!)</i>"
        )
        review_btn = InlineKeyboardButton(text="⏳ Первый отзыв на проверке (+7 дней)", callback_data="faq_review_pending_alert")
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [review_btn],
            [InlineKeyboardButton(text="◀️ Назад к вопросам", callback_data="menu_faq")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
        ])
    else:
        text = (
            f"🎁 <b>Получите +7 дней к подписке за отзыв!</b>\n\n"
            f"Мы очень ценим искреннюю обратную связь и хотим, чтобы гид становился удобнее и интереснее с каждым обновлением ✨\n\n"
            f"<b>Как получить бонус +7 дней:</b>\n"
            f"1. Нажмите кнопку <b>«✍️ Написать отзыв (+7 дней)»</b> ниже.\n"
            f"2. Отправьте ваш развёрнутый отзыв <u>одним сообщением</u> прямо в чат бота (напишите, что вам понравилось, какие локации успели посетить, удобно ли пользоваться картой и фильтрами).\n"
            f"3. Наша команда проверит отзыв и начислит вам <b>+7 дней</b> к текущему тарифу или пробному периоду! 🎉\n\n"
            f"⚠️ <i>Обратите внимание: бонус за отзыв начисляется ровно <b>один раз</b> на один аккаунт.</i>"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Написать отзыв (+7 дней)", callback_data="leave_review")],
            [InlineKeyboardButton(text="◀️ Назад к вопросам", callback_data="menu_faq")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
        ])

    await send_menu_message(
        callback.message.chat.id,
        text,
        reply_markup=kb,
        trigger_message=callback.message
    )
    await callback.answer()


@dp.callback_query(F.data == "leave_review")
async def leave_review_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    already_awarded = has_user_received_review_bonus(user_id)
    already_submitted = has_user_submitted_first_review(user_id)
    is_pending = is_user_review_pending(user_id)

    # 1. Если первый отзыв уже отправлен и ожидает начисления бонуса
    if already_submitted and not already_awarded:
        await callback.answer("⏳ Ваш первый отзыв уже отправлен и ожидает проверки!", show_alert=True)
        text = (
            "⏳ <b>Ваш отзыв уже находится на проверке!</b>\n\n"
            "Вы уже отправили отзыв о гиде команде проекта 💌\n\n"
            "После быстрой проверки администратор начислит вам <b>бонус +7 дней</b> прямо в этот диалог 🎉\n\n"
            "Пожалуйста, дождитесь ответа команды гида!"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
        ])
        await send_menu_message(
            callback.message.chat.id,
            text,
            reply_markup=kb,
            trigger_message=callback.message
        )
        return

    # 2. Если уже есть отправленный отзыв на рассмотрении (лимит 1/1)
    if is_pending:
        await callback.answer("⏳ У вас уже есть отзыв на рассмотрении!", show_alert=True)
        text = (
            "⏳ <b>Лимит повторных отзывов (1/1)</b>\n\n"
            "Вы уже отправили отзыв команде гида, который ожидает рассмотрения 💌\n\n"
            "Пожалуйста, дождитесь ответа администратора прямо в этот диалог. "
            "Как только команда ответит вам, возможность отправить новое сообщение снова станет доступна!"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
        ])
        await send_menu_message(
            callback.message.chat.id,
            text,
            reply_markup=kb,
            trigger_message=callback.message
        )
        return

    USER_REVIEW_WAITING[user_id] = True
    SUPPORT_WAITING_USERS.pop(user_id, None)

    is_repeat = already_awarded or already_submitted
    bonus_hint = (
        "ℹ️ <i>Вы уже отправляли отзыв ранее (бонус +7 дней начисляется 1 раз на аккаунт). Ваше новое сообщение будет передано автору как тёплый отзыв!</i> ✨\n\n"
        if is_repeat else
        "🎁 <i>После быстрой проверки администратор начислит <b>+7 дней</b> к вашему доступу!</i>\n\n"
    )

    text = (
        f"✍️ <b>Напишите ваш отзыв о гиде</b>\n\n"
        f"Пожалуйста, напишите ваш отзыв <b>одним сообщением</b> прямо сюда в чат 💬\n\n"
        f"Расскажите, что вам больше всего понравилось, какие локации успели посетить и что было особенно удобно в карте.\n\n"
        f"{bonus_hint}"
        f"Ждём ваше сообщение! ✨"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в FAQ", callback_data="menu_faq")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_start")]
    ])
    await send_menu_message(
        callback.message.chat.id,
        text,
        reply_markup=kb,
        trigger_message=callback.message
    )
    await callback.answer()


@dp.callback_query(F.data == "faq_trouble")
async def faq_trouble_handler(callback: types.CallbackQuery):
    text = (
        f"🔄 <b>Что делать, если карта не загружается:</b>\n\n"
        f"1. <b>Проверьте интернет и VPN:</b> если включен сторонний VPN, попробуйте временно отключить его, так как Яндекс.Карты могут ограничивать доступ с зарубежных IP.\n"
        f"2. <b>Перезапустите страницу:</b> закройте Telegram Mini App и откройте снова кнопкой «Открыть карту».\n"
        f"3. <b>Очистите кэш</b> или откройте персональную ссылку в браузере Safari/Chrome.\n"
        f"4. <b>Сбросьте сессии:</b> если превышен лимит устройств, нажмите «Сбросить сессии» в меню «Сессии».\n\n"
        f"Если проблема сохраняется — нажмите кнопку ниже, чтобы описать ситуацию нашей поддержке."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Связаться с поддержкой", callback_data="contact_support")],
        [InlineKeyboardButton(text="◀️ Назад к вопросам", callback_data="menu_faq")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
    ])
    await send_menu_message(
        callback.message.chat.id,
        text,
        reply_markup=kb,
        trigger_message=callback.message
    )
    await callback.answer()


# -------------------------------------------------------------
# ДИАЛОГ С ПОДДЕРЖКОЙ (ЗАДАЧА ВОПРОСА И ОТВЕТ ЧЕРЕЗ REPLY)
# -------------------------------------------------------------

@dp.callback_query(F.data == "contact_support")
async def contact_support_handler(callback: types.CallbackQuery):
    tg_user = callback.from_user
    user = get_or_create_user(tg_user)
    if is_user_banned(user):
        await callback.answer("⛔️ Ваш аккаунт заблокирован администратором", show_alert=True)
        return

    unanswered_cnt = get_user_unanswered_support(tg_user.id)
    if unanswered_cnt >= 3:
        await callback.answer("⚠️ Вы уже отправили 3 сообщения в поддержку. Пожалуйста, дождитесь ответа специалиста!", show_alert=True)
        return

    SUPPORT_WAITING_USERS[tg_user.id] = True

    text = (
        f"💬 <b>Служба заботы и поддержки</b>\n\n"
        f"Пожалуйста, сформулируйте ваш вопрос или ответ <b>в одном сообщении</b> прямо сюда в чат ✍️\n\n"
        f"📷 <i>Вы можете прикрепить фото или скриншот к этому сообщению.</i>\n\n"
        f"⚠️ <b>Важно:</b> бот передаёт в группу поддержки ровно <u>одно сообщение</u>. Если вы хотите отправить несколько мыслей или фото, отправьте их одним сообщением либо нажимайте кнопку «💬 Дополнить вопрос» перед каждым следующим сообщением.\n\n"
        f"Даша или специалист поддержки ответит вам прямо в этот диалог с ботом!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить вопрос", callback_data="cancel_support")]
    ])

    msg_text = callback.message.text or callback.message.caption or ""
    # Если это сообщение с ответом поддержки или уведомлением - НЕ затираем его в чате!
    if "Ответ службы поддержки" in msg_text or "Ваш вопрос передан" in msg_text or "Сообщение успешно передано" in msg_text:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await send_menu_message(callback.message.chat.id, text, reply_markup=kb)
    else:
        await send_menu_message(callback.message.chat.id, text, reply_markup=kb, trigger_message=callback.message)
    await callback.answer()


@dp.callback_query(F.data == "cancel_support")
async def cancel_support_handler(callback: types.CallbackQuery):
    tg_user = callback.from_user
    SUPPORT_WAITING_USERS.pop(tg_user.id, None)
    USER_REVIEW_WAITING.pop(tg_user.id, None)
    USER_SUGGESTION_WAITING.pop(tg_user.id, None)
    await callback.answer("Ввод отменен")
    await back_to_start_handler(callback)


@dp.callback_query(F.data == "suggest_location")
async def suggest_location_callback_handler(callback: types.CallbackQuery):
    tg_user = callback.from_user
    user = get_or_create_user(tg_user)
    if is_user_banned(user):
        await callback.answer("⛔️ Ваш аккаунт заблокирован администратором", show_alert=True)
        return

    USER_SUGGESTION_WAITING[tg_user.id] = True

    text = (
        "📍 <b>Предложить локацию в гид</b> ✨\n\n"
        "Знаете классную авторскую кофейню, атмосферный дворик, необычный музей или фото-спот в Москве?\n\n"
        "Пожалуйста, пришлите <b>в одном сообщении</b> прямо сюда в чат ✍️:\n"
        "▫️ Название локации или заведения\n"
        "▫️ Адрес или ссылку на Яндекс Карты / 2ГИС / Telegram\n"
        "▫️ Почему это место классное и стоит вашего внимания\n"
        "▫️ <i>(по желанию) Прикрепите фото или скриншот!</i> 📸\n\n"
        "Даша и команда гида обязательно изучат ваше предложение и добавят на карту!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_support")]
    ])

    await send_menu_message(callback.message.chat.id, text, reply_markup=kb, trigger_message=callback.message)
    await callback.answer()


async def suggest_location_handler(message: types.Message):
    tg_user = message.from_user
    user = get_or_create_user(tg_user)
    if is_user_banned(user):
        await message.answer("⛔️ Ваш аккаунт заблокирован администратором")
        return

    USER_SUGGESTION_WAITING[tg_user.id] = True

    text = (
        "📍 <b>Предложить локацию в гид</b> ✨\n\n"
        "Знаете классную авторскую кофейню, атмосферный дворик, необычный музей или фото-спот в Москве?\n\n"
        "Пожалуйста, пришлите <b>в одном сообщении</b> прямо сюда в чат ✍️:\n"
        "▫️ Название локации или заведения\n"
        "▫️ Адрес или ссылку на Яндекс Карты / 2ГИС / Telegram\n"
        "▫️ Почему это место классное и стоит вашего внимания\n"
        "▫️ <i>(по желанию) Прикрепите фото или скриншот!</i> 📸\n\n"
        "Даша и команда гида обязательно изучат ваше предложение и добавят на карту!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel_support")]
    ])
    await send_menu_message(message.chat.id, text, reply_markup=kb)


def get_support_answer_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Задать вопрос / Ответить", callback_data="contact_support")],
        [InlineKeyboardButton(text="✅ Всё помогло, спасибо!", callback_data="support_resolved")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
    ])


@dp.callback_query(F.data == "support_resolved")
async def support_resolved_handler(callback: types.CallbackQuery):
    tg_user = callback.from_user
    user = get_or_create_user(tg_user)
    sub_info = check_subscription_status(user)
    user_name = tg_user.first_name or "Пользователь"
    username_str = f"@{tg_user.username}" if tg_user.username else f"ID {tg_user.id}"

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    reset_user_unanswered_support(tg_user.id)
    reset_user_unanswered_reviews(tg_user.id)
    await callback.answer("Спасибо за отзыв! ❤️")

    # Уведомляем группу поддержки о закрытии вопроса
    try:
        support_chat = int(SUPPORT_CHAT_ID) if (SUPPORT_CHAT_ID and SUPPORT_CHAT_ID.lstrip('-').isdigit()) else int(DEFAULT_SUPPORT_CHAT_ID)
        await bot.send_message(
            chat_id=support_chat,
            text=(
                f"🎉 <b>Вопрос решён!</b>\n\n"
                f"👤 <b>Пользователь:</b> {user_name} ({username_str})\n"
                f"🆔 <b>ID:</b> <code>{tg_user.id}</code>\n"
                f"Клиент нажал: <i>«✅ Всё помогло, спасибо!»</i> ❤️\n\n"
                f"#ticket_{tg_user.id} #resolved"
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"⚠️ Ошибка отправки уведомления о решении тикета: {e}")

    text = (
        "✨ <b>Рады были помочь!</b>\n\n"
        "Желаем самых ярких впечатлений, красивых локаций и отличного настроения! 🌿☀️\n"
        "Если появятся новые вопросы — мы всегда на связи.\n\n"
        "Вы можете вернуться к интерактивному гиду:"
    )
    kb = build_main_keyboard(user, sub_info)
    await send_menu_message(
        callback.message.chat.id,
        text,
        reply_markup=kb,
        trigger_message=callback.message
    )


async def deliver_admin_reply_to_user(target_user_id: int, message: types.Message):
    """
    Доставляет ответ службы поддержки пользователю:
    1. Автоматически закрывает/удаляет предыдущее активное меню над новым ответом,
       чтобы меню домой и навигация не оставались висеть выше ответа по логике сообщений.
    2. Отправляет ответ с удобной клавиатурой (Задать вопрос, Всё помогло, Главное меню).
    3. Сбрасывает счетчик спама/неотвеченных обращений.
    """
    old_menu_mid = USER_ACTIVE_MENU.pop(target_user_id, None)
    if old_menu_mid:
        try:
            await bot.delete_message(chat_id=target_user_id, message_id=old_menu_mid)
        except Exception:
            try:
                await bot.edit_message_reply_markup(chat_id=target_user_id, message_id=old_menu_mid, reply_markup=None)
            except Exception:
                pass

    ans_header = "💌 <b>Ответ службы поддержки:</b>\n\n"
    ans_footer = (
        "\n\n───\n"
        "👇 <i>Чтобы продолжить диалог или перейти к разделам гида, выберите действие:</i>"
    )
    user_kb = get_support_answer_kb()

    if message.text:
        await bot.send_message(
            chat_id=target_user_id,
            text=f"{ans_header}{message.text}{ans_footer}",
            parse_mode="HTML",
            reply_markup=user_kb
        )
    elif message.photo:
        await bot.send_photo(
            chat_id=target_user_id,
            photo=message.photo[-1].file_id,
            caption=f"{ans_header}{message.caption or ''}{ans_footer}".strip(),
            parse_mode="HTML",
            reply_markup=user_kb
        )
    elif message.voice:
        await bot.send_voice(
            chat_id=target_user_id,
            voice=message.voice.file_id,
            caption=f"{ans_header}{message.caption or ''}{ans_footer}".strip(),
            parse_mode="HTML",
            reply_markup=user_kb
        )
    elif message.document:
        await bot.send_document(
            chat_id=target_user_id,
            document=message.document.file_id,
            caption=f"{ans_header}{message.caption or ''}{ans_footer}".strip(),
            parse_mode="HTML",
            reply_markup=user_kb
        )
    else:
        await message.copy_to(chat_id=target_user_id, reply_markup=user_kb)

    reset_user_unanswered_support(target_user_id)
    reset_user_unanswered_reviews(target_user_id)


@dp.message(F.reply_to_message)
async def admin_reply_handler(message: types.Message):
    """
    Обработка ответа администратора через стандартный Reply на сообщение тикета.
    """
    admin_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id

    is_admin = (admin_id in ADMIN_IDS) or (chat_id in ADMIN_IDS) or (str(chat_id) in (str(SUPPORT_CHAT_ID), str(FEEDBACK_CHAT_ID), str(DEFAULT_SUPPORT_CHAT_ID), str(DEFAULT_FEEDBACK_CHAT_ID)))
    if not is_admin:
        return

    replied_msg = message.reply_to_message
    if not replied_msg:
        return

    target_user_id = SUPPORT_REPLY_MAP.get(replied_msg.message_id)

    # Если в памяти нет (бот перезапускался), извлекаем ID из тега #ticket_<ID> или <code><ID></code>
    if not target_user_id:
        target_text = (replied_msg.text or replied_msg.caption or "")
        match = re.search(r'#ticket_(\d+)', target_text)
        if not match:
            match = re.search(r'ID:\s*<code>(\d+)</code>', target_text)
        if not match:
            match = re.search(r'ID:\s*(\d+)', target_text)
        if match:
            target_user_id = int(match.group(1))

    if not target_user_id:
        return

    try:
        await deliver_admin_reply_to_user(target_user_id, message)
        await message.reply(f"✅ <b>Ответ успешно доставлен пользователю!</b>\n(ID: <code>{target_user_id}</code>)", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"⚠️ Ошибка доставки ответа пользователю {target_user_id}:\n<code>{e}</code>", parse_mode="HTML")


@dp.callback_query(F.data.startswith("support_reply_"))
async def callback_support_reply(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    try:
        target_user_id = int(callback.data.replace("support_reply_", ""))
    except ValueError:
        await callback.answer("Неверный ID пользователя", show_alert=True)
        return

    ADMIN_WAITING_REPLY[admin_id] = target_user_id

    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить ответ", callback_data="cancel_admin_reply")]
    ])
    prompt_msg = await callback.message.reply(
        f"✍️ <b>Режим ответа пользователю</b> (ID: <code>{target_user_id}</code>):\n\n"
        f"Отправьте текст, фото, документ или голосовое сообщение — бот мгновенно доставит его в диалог пользователю.\n\n"
        f"<i>💡 Совет: сделайте бота администратором группы или отправьте ответ через «Ответить» (Reply) на это сообщение.</i>\n"
        f"#ticket_{target_user_id}",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )
    SUPPORT_REPLY_MAP[prompt_msg.message_id] = target_user_id
    await callback.answer()


@dp.callback_query(F.data == "cancel_admin_reply")
async def cancel_admin_reply_handler(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    ADMIN_WAITING_REPLY.pop(admin_id, None)
    await callback.message.edit_text("❌ Ответ отменен.")
    await callback.answer()


def get_days_word(n: int) -> str:
    n_abs = abs(n)
    if n_abs % 10 == 1 and n_abs % 100 != 11:
        return "день"
    elif n_abs % 10 in [2, 3, 4] and not (n_abs % 100 in [12, 13, 14]):
        return "дня"
    else:
        return "дней"


def get_username_from_ticket_markup(reply_markup) -> str:
    if not reply_markup:
        return None
    for row in reply_markup.inline_keyboard:
        for btn in row:
            if btn.url and "t.me/" in btn.url:
                return btn.url.split("t.me/")[-1]
    return None


def build_ticket_keyboard(target_user_id: int, ticket_msg_id: int = 0, username: str = None) -> InlineKeyboardMarkup:
    summary = get_user_bonus_summary(target_user_id)
    already_awarded = summary['has_review_bonus']
    extra_days = summary['extra_days']

    buttons = []
    # Ряд 1: Быстрые бонусы (+7 за отзыв и +3 дня)
    bonus_row = []
    if already_awarded:
        bonus_row.append(InlineKeyboardButton(text="✅ Отзыв: +7", callback_data="bonus_already_granted"))
    else:
        bonus_row.append(InlineKeyboardButton(text="🎁 +7 дн.", callback_data=f"grant_review_bonus_{target_user_id}"))

    bonus_row.append(InlineKeyboardButton(text="⚡ +3 дн.", callback_data=f"grant_extra_bonus_{target_user_id}_3"))
    buttons.append(bonus_row)

    # Ряд 2: Выбор любого другого срока и просмотр истории бонусов
    row2 = [
        InlineKeyboardButton(text="➕ Другой срок", callback_data=f"cmenu_{target_user_id}"),
        InlineKeyboardButton(text=f"📊 Бонусы ({extra_days} дн.)", callback_data=f"view_bonus_history_{target_user_id}")
    ]
    buttons.append(row2)

    # Ряд 3: Ответ пользователю и Модерация (Бан/Разбан)
    target_user_profile = get_user_from_db(target_user_id)
    target_is_banned = is_user_banned(target_user_profile)
    ban_btn_text = "🟢 Разбанить" if target_is_banned else "⛔️ Забанить"
    ban_btn_data = f"support_unban_{target_user_id}" if target_is_banned else f"support_ban_{target_user_id}"

    buttons.append([
        InlineKeyboardButton(text="✏️ Ответить", callback_data=f"support_reply_{target_user_id}"),
        InlineKeyboardButton(text=ban_btn_text, callback_data=ban_btn_data)
    ])

    # Ряд 4: Профиль пользователя в Telegram
    if username:
        clean_user = username.lstrip('@')
        buttons.append([
            InlineKeyboardButton(text=f"👤 Профиль @{clean_user}", url=f"https://t.me/{clean_user}")
        ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.callback_query(F.data.startswith("support_ban_"))
async def callback_support_ban_prompt(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    is_admin = (admin_id in ADMIN_IDS) or (callback.message.chat.id in ADMIN_IDS) or (str(callback.message.chat.id) in (str(SUPPORT_CHAT_ID), str(FEEDBACK_CHAT_ID), str(DEFAULT_SUPPORT_CHAT_ID), str(DEFAULT_FEEDBACK_CHAT_ID)))
    if not is_admin:
        await callback.answer("Только для администраторов", show_alert=True)
        return

    target_id = int(callback.data.replace("support_ban_", ""))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⛔️ Да, заблокировать", callback_data=f"conf_ban_{target_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel_ban_{target_id}")
        ]
    ])
    await callback.message.reply(
        f"❓ <b>Подтверждение блокировки:</b>\n\n"
        f"Заблокировать пользователя ID <code>{target_id}</code>?\n"
        f"Он больше не сможет отправлять сообщения боту, писать в поддержку и открывать интерактивную карту.",
        parse_mode="HTML",
        reply_markup=kb
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("conf_ban_"))
async def callback_conf_ban(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    is_admin = (admin_id in ADMIN_IDS) or (callback.message.chat.id in ADMIN_IDS) or (str(callback.message.chat.id) in (str(SUPPORT_CHAT_ID), str(FEEDBACK_CHAT_ID), str(DEFAULT_SUPPORT_CHAT_ID), str(DEFAULT_FEEDBACK_CHAT_ID)))
    if not is_admin:
        await callback.answer("Только для администраторов", show_alert=True)
        return

    target_id = int(callback.data.replace("conf_ban_", ""))
    try:
        supabase.table('app_users').update({'plan': 'banned', 'devices': []}).eq('telegram_id', target_id).execute()
        invalidate_user_cache(target_id)
        SUPPORT_WAITING_USERS.pop(target_id, None)
        PENDING_SUPPORT_MESSAGE.pop(target_id, None)
        await callback.message.edit_text(
            f"⛔️ <b>Пользователь ID <code>{target_id}</code> заблокирован!</b>\n"
            f"Администратор: @{callback.from_user.username or callback.from_user.first_name}",
            parse_mode="HTML"
        )
        await callback.answer("Пользователь заблокирован!", show_alert=True)
    except Exception as e:
        await callback.message.edit_text(f"⚠️ Ошибка блокировки: {e}")


@dp.callback_query(F.data.startswith("support_unban_"))
async def callback_support_unban(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    is_admin = (admin_id in ADMIN_IDS) or (callback.message.chat.id in ADMIN_IDS) or (str(callback.message.chat.id) in (str(SUPPORT_CHAT_ID), str(FEEDBACK_CHAT_ID), str(DEFAULT_SUPPORT_CHAT_ID), str(DEFAULT_FEEDBACK_CHAT_ID)))
    if not is_admin:
        await callback.answer("Только для администраторов", show_alert=True)
        return

    target_id = int(callback.data.replace("support_unban_", ""))
    try:
        supabase.table('app_users').update({'plan': 'trial'}).eq('telegram_id', target_id).execute()
        invalidate_user_cache(target_id)
        reset_user_unanswered_support(target_id)
        await callback.message.reply(
            f"🟢 <b>Пользователь ID <code>{target_id}</code> разблокирован!</b>\n"
            f"Установлен базовый тариф.",
            parse_mode="HTML"
        )
        await callback.answer("Пользователь разблокирован!", show_alert=True)
    except Exception as e:
        await callback.message.reply(f"⚠️ Ошибка разблокировки: {e}", parse_mode="HTML")


@dp.callback_query(F.data.startswith("cancel_ban_"))
async def callback_cancel_ban(callback: types.CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("Отменено")


@dp.message(Command("ban"))
async def admin_ban_command(message: types.Message):
    admin_id = message.from_user.id if message.from_user else 0
    if admin_id not in ADMIN_IDS and str(message.chat.id) not in [str(a) for a in ADMIN_IDS]:
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.reply(
            "⚠️ <b>Использование:</b> <code>/ban &lt;telegram_id&gt;</code>\n"
            "Пример: <code>/ban 123456789</code>",
            parse_mode="HTML"
        )
        return

    target_id_str = parts[1].strip()
    if not target_id_str.isdigit():
        await message.reply("⚠️ ID пользователя должен быть числом.", parse_mode="HTML")
        return

    target_id = int(target_id_str)
    try:
        supabase.table('app_users').update({'plan': 'banned', 'devices': []}).eq('telegram_id', target_id).execute()
        invalidate_user_cache(target_id)
        SUPPORT_WAITING_USERS.pop(target_id, None)
        PENDING_SUPPORT_MESSAGE.pop(target_id, None)
        await message.reply(f"⛔️ <b>Пользователь ID <code>{target_id}</code> успешно заблокирован!</b>\nДоступ к боту и карте закрыт.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"⚠️ Ошибка блокировки пользователя: {e}", parse_mode="HTML")


@dp.message(Command("unban"))
async def admin_unban_command(message: types.Message):
    admin_id = message.from_user.id if message.from_user else 0
    if admin_id not in ADMIN_IDS and str(message.chat.id) not in [str(a) for a in ADMIN_IDS]:
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.reply(
            "⚠️ <b>Использование:</b> <code>/unban &lt;telegram_id&gt;</code>\n"
            "Пример: <code>/unban 123456789</code>",
            parse_mode="HTML"
        )
        return

    target_id_str = parts[1].strip()
    if not target_id_str.isdigit():
        await message.reply("⚠️ ID пользователя должен быть числом.", parse_mode="HTML")
        return

    target_id = int(target_id_str)
    try:
        supabase.table('app_users').update({'plan': 'trial'}).eq('telegram_id', target_id).execute()
        invalidate_user_cache(target_id)
        reset_user_unanswered_support(target_id)
        await message.reply(f"🟢 <b>Пользователь ID <code>{target_id}</code> успешно разблокирован!</b>\nУстановлен тариф Trial.", parse_mode="HTML")
    except Exception as e:
        await message.reply(f"⚠️ Ошибка разблокировки пользователя: {e}", parse_mode="HTML")


async def send_ticket_to_support(message: types.Message, tg_user: types.User, is_addition: bool = False, is_review: bool = False, is_repeat_review: bool = False, is_suggestion: bool = False):
    """
    Отправка обращения в закрытую группу поддержки (SUPPORT_CHAT_ID) или группу отзывов/предложений (FEEDBACK_CHAT_ID).
    Отзывы о гиде и предложения новых локаций направляются в чат FEEDBACK_CHAT_ID.
    Вопросы и дополнения в техподдержку направляются в SUPPORT_CHAT_ID.
    """
    user_id = tg_user.id
    user = get_or_create_user(tg_user)
    sub_info = check_subscription_status(user)
    cur_sessions = len(user.get('devices') or [])
    max_dev = user.get('max_devices', 3)
    user_name = tg_user.first_name or "Пользователь"
    username_str = f"@{tg_user.username}" if tg_user.username else "нет username"

    support_chat = int(SUPPORT_CHAT_ID) if (SUPPORT_CHAT_ID and SUPPORT_CHAT_ID.lstrip('-').isdigit()) else int(DEFAULT_SUPPORT_CHAT_ID)
    feedback_chat = int(FEEDBACK_CHAT_ID) if (FEEDBACK_CHAT_ID and FEEDBACK_CHAT_ID.lstrip('-').isdigit()) else int(DEFAULT_FEEDBACK_CHAT_ID)

    is_feedback_target = bool(is_review or is_suggestion)
    target_admin = feedback_chat if is_feedback_target else support_chat
    chat_label = "Feedback" if is_feedback_target else "Поддержка"
    ticket_type_label = 'предложение' if is_suggestion else ('повторный отзыв' if is_repeat_review else ('отзыв' if is_review else ('дополнение' if is_addition else 'новый')))
    print(f"📩 [{chat_label}] Отправка тикета ({ticket_type_label}) в чат ID: {target_admin} (SUPPORT={support_chat}, FEEDBACK={feedback_chat})")

    bonus_summary = get_user_bonus_summary(user_id)
    already_awarded = bonus_summary['has_review_bonus']
    extra_days = bonus_summary['extra_days']
    extra_count = bonus_summary['extra_count']

    extra_bonus_text = f"<b>{extra_days} дн.</b> (начислено {extra_count} раз)" if extra_days > 0 else "0 дн."

    if is_suggestion:
        header_title = "📍 <b>Предложение новой локации для гида!</b> #предложение_локации #feedback"
        bonus_status_line = "⚪ Предложение локации"
        content_label = "🗺️ <b>Описание места / адрес / ссылки:</b>\n"
        unanswered_badge = "Предложение локации ✨"
    elif is_review:
        if is_repeat_review:
            header_title = "💌 <b>Повторный отзыв о гиде</b> #отзыв #feedback"
            bonus_status_line = "❌ <b>ПОВТОРНЫЙ (бонус +7 уже учтен/выдан)</b>"
            content_label = "💬 <b>Текст повторного отзыва:</b>\n"
            unanswered_badge = "1/1 (лимит повторных отзывов ⛔️)"
        else:
            header_title = "🌟 <b>Первый отзыв о гиде (ПРЕТЕНДУЕТ НА +7 ДНЕЙ)</b> #отзыв #feedback"
            bonus_status_line = "🟢 <b>ПЕРВЫЙ ОТЗЫВ (+7 дней доступно к начислению!)</b>"
            content_label = "💬 <b>Текст первого отзыва:</b>\n"
            unanswered_badge = "1/1 (первый отзыв)"
    elif is_addition:
        header_title = "📩 <b>Дополнение к обращению в поддержку!</b>"
        bonus_status_line = "✅ Выдан (+7 дн.)" if already_awarded else "⚪ Не выдавался"
        content_label = "💬 <b>Дополнение:</b>\n"
        cur_unanswered = get_user_unanswered_support(user_id) + 1
        unanswered_badge = f"{cur_unanswered}/3" if cur_unanswered < 3 else f"<b>{cur_unanswered}/3 (ЛИМИТ 3/3 ДОСТИГНУТ ⛔️)</b>"
    else:
        header_title = "📩 <b>Новое обращение в поддержку!</b>"
        bonus_status_line = "✅ Выдан (+7 дн.)" if already_awarded else "⚪ Не выдавался"
        content_label = "💬 <b>Сообщение:</b>\n"
        cur_unanswered = get_user_unanswered_support(user_id) + 1
        unanswered_badge = f"{cur_unanswered}/3" if cur_unanswered < 3 else f"<b>{cur_unanswered}/3 (ЛИМИТ 3/3 ДОСТИГНУТ ⛔️)</b>"

    ticket_header = (
        f"{header_title}\n\n"
        f"👤 <b>От:</b> {user_name} ({username_str})\n"
        f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
        f"💎 <b>Тариф:</b> {sub_info['badge']} ({sub_info['date_str']})\n"
        f"⏳ <b>Сообщений подряд:</b> {unanswered_badge}\n"
        f"🎁 <b>Бонус за отзыв:</b> {bonus_status_line}\n"
        f"⚡ <b>Доп. бонусов (сверх отзыва):</b> {extra_bonus_text}\n"
        f"📱 <b>Сессии:</b> {cur_sessions}/{max_dev}\n\n"
        f"{content_label}"
    )
    feedback_tag = " #feedback" if is_feedback_target else ""
    ticket_footer = (
        f"\n\n<i>ℹ️ Нажмите «Ответить» (Reply) или кнопку ниже, чтобы отправить ответ пользователю.</i>\n"
        f"#ticket_{user_id}{feedback_tag}"
    )

    user_content = message.text or message.caption or "<i>[Вложение без текста]</i>"
    full_ticket_text = f"{ticket_header}{user_content}{ticket_footer}"

    ticket_kb = build_ticket_keyboard(user_id, 0, tg_user.username)

    if message.photo:
        sent = await bot.send_photo(
            chat_id=target_admin,
            photo=message.photo[-1].file_id,
            caption=full_ticket_text,
            parse_mode="HTML",
            reply_markup=ticket_kb
        )
    elif message.voice:
        sent = await bot.send_voice(
            chat_id=target_admin,
            voice=message.voice.file_id,
            caption=full_ticket_text,
            parse_mode="HTML",
            reply_markup=ticket_kb
        )
    elif message.document:
        sent = await bot.send_document(
            chat_id=target_admin,
            document=message.document.file_id,
            caption=full_ticket_text,
            parse_mode="HTML",
            reply_markup=ticket_kb
        )
    else:
        sent = await bot.send_message(
            chat_id=target_admin,
            text=full_ticket_text,
            parse_mode="HTML",
            reply_markup=ticket_kb
        )

    SUPPORT_REPLY_MAP[sent.message_id] = user_id
    return sent


@dp.callback_query(F.data.startswith("grant_review_bonus_"))
async def grant_review_bonus_handler(callback: types.CallbackQuery):
    """
    Начисление +7 дней за развернутый отзыв с полной защитой от абуза и повторного начисления.
    """
    admin_user = callback.from_user
    try:
        target_user_id = int(callback.data.replace("grant_review_bonus_", ""))
    except ValueError:
        await callback.answer("⚠️ Некорректный ID пользователя", show_alert=True)
        return

    # 1. СТРОГАЯ ЗАЩИТА ОТ АБУЗА: проверяем, не был ли уже выдан бонус ранее
    if has_user_received_review_bonus(target_user_id):
        await callback.answer(
            "⚠️ ВНИМАНИЕ: Этому пользователю уже был начислен бонус за отзыв ранее!\n\n"
            "Повторное начисление строго заблокировано системой защиты от абуза.",
            show_alert=True
        )
        # Убираем активную кнопку начисления из тикета
        try:
            cur_kb = callback.message.reply_markup.inline_keyboard if callback.message.reply_markup else []
            new_rows = []
            for row in cur_kb:
                new_row = []
                for btn in row:
                    if btn.callback_data and btn.callback_data.startswith("grant_review_bonus_"):
                        new_row.append(InlineKeyboardButton(text="⚠️ Бонус уже выдан ранее", callback_data="bonus_already_granted"))
                    else:
                        new_row.append(btn)
                if new_row:
                    new_rows.append(new_row)
            await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=new_rows))
        except Exception:
            pass
        return

    # 2. Мгновенная фиксация в локальной базе для защиты от race condition при повторных кликах
    admin_name = f"@{admin_user.username}" if admin_user.username else (admin_user.first_name or f"ID {admin_user.id}")
    record_user_review_bonus(target_user_id, admin_user.id, admin_name, days=7)

    # 3. Загружаем пользователя из Supabase
    target_user = get_user_from_db(target_user_id)
    if not target_user:
        await callback.answer("⚠️ Пользователь не найден в базе данных.", show_alert=True)
        return

    now = datetime.now(timezone.utc)
    cur_exp_raw = target_user.get('expires_at') or target_user.get('access_until')
    cur_exp = parse_iso_datetime(cur_exp_raw) if cur_exp_raw else None

    # Продлеваем: если текущая дата окончания в будущем, прибавляем +7 дней к ней, иначе от текущего момента
    if cur_exp and cur_exp > now:
        new_exp = cur_exp + timedelta(days=7)
    else:
        new_exp = now + timedelta(days=7)

    new_exp_iso = new_exp.isoformat()
    new_date_str = new_exp.strftime('%d.%m.%Y')

    update_payload = {'expires_at': new_exp_iso}
    if target_user.get('plan') in ('trial', 'free', None):
        update_payload['plan'] = 'trial'

    try:
        supabase.table('app_users').update(update_payload).eq('telegram_id', target_user_id).execute()
        target_user['expires_at'] = new_exp_iso
    except Exception as e:
        print(f"⚠️ Ошибка обновления expires_at в Supabase: {e}")
        await callback.answer("⚠️ Ошибка обновления даты в базе Supabase!", show_alert=True)
        return

    # 4. Отправляем пользователю личное поздравление с начислением бонуса и новой датой
    user_congrats_text = (
        f"🎉 <b>Вам начислен бонус +7 дней за развёрнутый отзыв!</b>\n\n"
        f"Даша и команда гида благодарят вас за тёплые слова и ценную обратную связь! ❤️\n\n"
        f"📅 <b>Доступ успешно продлён:</b> до <b>{new_date_str}</b>\n\n"
        f"Приятных и незабываемых прогулок по Москве! 📍"
    )
    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=user_congrats_text,
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"⚠️ Не удалось доставить сообщение пользователю {target_user_id}: {e}")

    # 5. Обновляем тикет в чате поддержки (аудит-запись и деактивация кнопки начисления)
    try:
        audit_note = (
            f"\n\n───\n"
            f"✅ <b>+7 дн. за отзыв</b> ({admin_name}) ➔ до {new_date_str}"
        )

        username = get_username_from_ticket_markup(callback.message.reply_markup) or target_user.get('username')
        new_ticket_kb = build_ticket_keyboard(target_user_id, callback.message.message_id, username)

        if callback.message.caption:
            await callback.message.edit_caption(
                caption=f"{callback.message.caption}{audit_note}",
                parse_mode="HTML",
                reply_markup=new_ticket_kb
            )
        elif callback.message.text:
            await callback.message.edit_text(
                text=f"{callback.message.text}{audit_note}",
                parse_mode="HTML",
                reply_markup=new_ticket_kb
            )
    except Exception as e:
        print(f"⚠️ Ошибка обновления сообщения тикета: {e}")

    await callback.answer(f"✅ Начислено +7 дн. (до {new_date_str})")


@dp.callback_query(F.data == "bonus_already_granted")
async def bonus_already_granted_handler(callback: types.CallbackQuery):
    await callback.answer(
        "ℹ️ Бонус +7 дней за отзыв уже был начислен этому пользователю ранее.\n"
        "Повторная выдача не требуется.",
        show_alert=True
    )


@dp.callback_query(F.data.startswith("grant_extra_bonus_"))
async def grant_extra_bonus_handler(callback: types.CallbackQuery):
    """
    Выдача бонуса на 3 дня (для особых случаев / компенсаций, чтобы радовать подписчиков).
    Автоматически ведёт счётчик выданных бонусных дней сверх отзыва для админов.
    """
    admin_user = callback.from_user
    data_parts = callback.data.split("_")
    # Формат callback_data: grant_extra_bonus_{target_user_id}_{bonus_days}
    try:
        target_user_id = int(data_parts[3])
        bonus_days = int(data_parts[4]) if len(data_parts) > 4 else 3
    except (IndexError, ValueError):
        await callback.answer("⚠️ Некорректный ID пользователя или параметры", show_alert=True)
        return

    admin_name = f"@{admin_user.username}" if admin_user.username else (admin_user.first_name or f"ID {admin_user.id}")

    # 1. Загружаем пользователя из базы данных Supabase
    target_user = get_user_from_db(target_user_id)
    if not target_user:
        await callback.answer("⚠️ Пользователь не найден в базе данных.", show_alert=True)
        return

    # 2. Фиксируем начисление в базе и инкрементируем счетчик бонусов (сверх отзыва)
    total_extra_days = record_user_extra_bonus(
        user_id=target_user_id,
        admin_id=admin_user.id,
        admin_name=admin_name,
        days=bonus_days,
        reason="Особый случай / компенсация"
    )

    now = datetime.now(timezone.utc)
    cur_exp_raw = target_user.get('expires_at') or target_user.get('access_until')
    cur_exp = parse_iso_datetime(cur_exp_raw) if cur_exp_raw else None

    # Продлеваем: если текущая дата окончания в будущем, прибавляем дни к ней, иначе от текущего момента
    if cur_exp and cur_exp > now:
        new_exp = cur_exp + timedelta(days=bonus_days)
    else:
        new_exp = now + timedelta(days=bonus_days)

    new_exp_iso = new_exp.isoformat()
    new_date_str = new_exp.strftime('%d.%m.%Y')

    update_payload = {'expires_at': new_exp_iso}
    if target_user.get('plan') in ('trial', 'free', None):
        update_payload['plan'] = 'trial'

    try:
        supabase.table('app_users').update(update_payload).eq('telegram_id', target_user_id).execute()
        target_user['expires_at'] = new_exp_iso
    except Exception as e:
        print(f"⚠️ Ошибка обновления expires_at в Supabase: {e}")
        await callback.answer("⚠️ Ошибка обновления даты в базе Supabase!", show_alert=True)
        return

    # 3. Отправляем пользователю короткое дружелюбное уведомление
    user_congrats_text = (
        f"🎁 <b>Вам начислен бонус: +{bonus_days} дня!</b> ✨\n\n"
        f"📅 Доступ продлён до <b>{new_date_str}</b>\n\n"
        f"Приятных прогулок! 📍"
    )
    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=user_congrats_text,
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"⚠️ Не удалось доставить сообщение пользователю {target_user_id}: {e}")

    # 4. Обновляем тикет в чате поддержки (лаконичный аудит без лишних строк и кнопка без дублирования счета)
    try:
        audit_note = (
            f"\n\n───\n"
            f"⚡ <b>+{bonus_days} дн.</b> ({admin_name}) ➔ до {new_date_str}"
        )

        username = get_username_from_ticket_markup(callback.message.reply_markup) or target_user.get('username')
        new_ticket_kb = build_ticket_keyboard(target_user_id, callback.message.message_id, username)

        if callback.message.caption:
            await callback.message.edit_caption(
                caption=f"{callback.message.caption}{audit_note}",
                parse_mode="HTML",
                reply_markup=new_ticket_kb
            )
        elif callback.message.text:
            await callback.message.edit_text(
                text=f"{callback.message.text}{audit_note}",
                parse_mode="HTML",
                reply_markup=new_ticket_kb
            )
    except Exception as e:
        print(f"⚠️ Ошибка обновления сообщения тикета: {e}")

    await callback.answer(f"✅ Начислено +{bonus_days} дн. (до {new_date_str})")


@dp.callback_query(F.data.startswith("cmenu_"))
async def custom_bonus_menu_handler(callback: types.CallbackQuery):
    """Меню выбора произвольного количества бонусных дней."""
    try:
        target_user_id = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        await callback.answer("⚠️ Ошибка: не найден ID пользователя", show_alert=True)
        return

    ticket_msg_id = callback.message.message_id
    menu_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="+1 день", callback_data=f"cask_{target_user_id}_1_{ticket_msg_id}"),
            InlineKeyboardButton(text="+5 дней", callback_data=f"cask_{target_user_id}_5_{ticket_msg_id}"),
            InlineKeyboardButton(text="+7 дней", callback_data=f"cask_{target_user_id}_7_{ticket_msg_id}"),
        ],
        [
            InlineKeyboardButton(text="+10 дней", callback_data=f"cask_{target_user_id}_10_{ticket_msg_id}"),
            InlineKeyboardButton(text="+14 дней", callback_data=f"cask_{target_user_id}_14_{ticket_msg_id}"),
            InlineKeyboardButton(text="+30 дней", callback_data=f"cask_{target_user_id}_30_{ticket_msg_id}"),
        ],
        [
            InlineKeyboardButton(text="✏️ Ввести другое число дней", callback_data=f"cinp_{target_user_id}_{ticket_msg_id}")
        ],
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"ccancel_{target_user_id}")
        ]
    ])

    await callback.message.reply(
        f"⚙️ <b>Выдача дней доступа для ID <code>{target_user_id}</code>:</b>\n"
        f"Выберите срок или нажмите «Ввести другое число дней»:",
        parse_mode="HTML",
        reply_markup=menu_kb
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("cask_"))
async def custom_ask_confirmation_handler(callback: types.CallbackQuery):
    """Запрос подтверждения перед начислением выбранного количества дней."""
    parts = callback.data.split("_")
    try:
        target_user_id = int(parts[1])
        days = int(parts[2])
        ticket_msg_id = int(parts[3])
    except (IndexError, ValueError):
        await callback.answer("⚠️ Некорректные параметры", show_alert=True)
        return

    days_word = get_days_word(days)
    confirm_text = (
        f"❓ <b>Подтверждение выдачи:</b>\n\n"
        f"Начислить <b>+{days} {days_word}</b> пользователю ID <code>{target_user_id}</code>?\n\n"
        f"💬 <b>Пользователю будет отправлено сообщение:</b>\n"
        f"<i>«🎁 <b>Вам начислен приятный бонус: +{days} {days_word} к доступу!</b> ✨\n\n"
        f"Даша и команда гида благодарят вас за то, что вы с нами! Мы ценим ваше доверие и хотим, чтобы приложение приносило только радость ❤️\n\n"
        f"📅 Доступ успешно продлён...»</i>\n\n"
        f"<b>Точно выдать?</b>"
    )
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=f"✅ Точно выдать +{days} дн.", callback_data=f"cdo_{target_user_id}_{days}_{ticket_msg_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"ccancel_{target_user_id}")
        ]
    ])
    await callback.message.edit_text(confirm_text, parse_mode="HTML", reply_markup=confirm_kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("cinp_"))
async def custom_input_prompt_handler(callback: types.CallbackQuery):
    """Перевод администратора в режим ручного ввода числа дней."""
    parts = callback.data.split("_")
    try:
        target_user_id = int(parts[1])
        ticket_msg_id = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer("⚠️ Некорректные параметры", show_alert=True)
        return

    admin_user = callback.from_user
    ADMIN_WAITING_CUSTOM_DAYS[admin_user.id] = {
        "target_user_id": target_user_id,
        "ticket_msg_id": ticket_msg_id
    }

    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"ccancel_{target_user_id}")]
    ])
    await callback.message.edit_text(
        f"✏️ <b>Введите количество дней</b> (целое положительное число, например <code>10</code> или <code>45</code>) в ответ на это сообщение:",
        parse_mode="HTML",
        reply_markup=cancel_kb
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("ccancel_"))
async def custom_cancel_handler(callback: types.CallbackQuery):
    """Отмена выдачи произвольного бонуса."""
    admin_user = callback.from_user
    ADMIN_WAITING_CUSTOM_DAYS.pop(admin_user.id, None)
    try:
        await callback.message.delete()
    except Exception:
        await callback.message.edit_text("❌ Выдача бонуса отменена.", reply_markup=None)
    await callback.answer("Отменено")


@dp.callback_query(F.data.startswith("cdo_"))
async def custom_do_grant_handler(callback: types.CallbackQuery):
    """Окончательное подтвержденное начисление произвольного бонуса."""
    parts = callback.data.split("_")
    try:
        target_user_id = int(parts[1])
        days = int(parts[2])
        ticket_msg_id = int(parts[3])
    except (IndexError, ValueError):
        await callback.answer("⚠️ Некорректные параметры", show_alert=True)
        return

    admin_user = callback.from_user
    admin_name = f"@{admin_user.username}" if admin_user.username else (admin_user.first_name or f"ID {admin_user.id}")

    target_user = get_user_from_db(target_user_id)
    if not target_user:
        await callback.answer("⚠️ Пользователь не найден в базе данных.", show_alert=True)
        return

    days_word = get_days_word(days)
    total_extra_days = record_user_extra_bonus(
        user_id=target_user_id,
        admin_id=admin_user.id,
        admin_name=admin_name,
        days=days,
        reason=f"Ручная выдача +{days} {days_word}"
    )

    now = datetime.now(timezone.utc)
    cur_exp_raw = target_user.get('expires_at') or target_user.get('access_until')
    cur_exp = parse_iso_datetime(cur_exp_raw) if cur_exp_raw else None

    if cur_exp and cur_exp > now:
        new_exp = cur_exp + timedelta(days=days)
    else:
        new_exp = now + timedelta(days=days)

    new_exp_iso = new_exp.isoformat()
    new_date_str = new_exp.strftime('%d.%m.%Y')

    update_payload = {'expires_at': new_exp_iso}
    if target_user.get('plan') in ('trial', 'free', None):
        update_payload['plan'] = 'trial'

    try:
        supabase.table('app_users').update(update_payload).eq('telegram_id', target_user_id).execute()
        target_user['expires_at'] = new_exp_iso
    except Exception as e:
        print(f"⚠️ Ошибка обновления expires_at: {e}")
        await callback.answer("⚠️ Ошибка обновления базы данных!", show_alert=True)
        return

    # Отправляем пользователю теплое полное сообщение (которое раньше было за 3 дня)
    user_congrats_text = (
        f"🎁 <b>Вам начислен приятный бонус: +{days} {days_word} к доступу!</b> ✨\n\n"
        f"Даша и команда гида благодарят вас за то, что вы с нами! Мы ценим ваше доверие и хотим, чтобы приложение приносило только радость ❤️\n\n"
        f"📅 <b>Доступ успешно продлён:</b> до <b>{new_date_str}</b>\n\n"
        f"Приятных и вдохновляющих прогулок по Москве! 📍"
    )
    try:
        await bot.send_message(
            chat_id=target_user_id,
            text=user_congrats_text,
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"⚠️ Ошибка отправки пользователю {target_user_id}: {e}")

    # Редактируем сообщение с подтверждением в чате админа
    confirm_done_text = (
        f"✅ <b>+{days} {days_word}</b> успешно начислено пользователю <code>{target_user_id}</code>!\n"
        f"👤 <b>Выдал:</b> {admin_name}\n"
        f"📅 <b>Новый срок:</b> до <b>{new_date_str}</b>"
    )
    try:
        await callback.message.edit_text(confirm_done_text, parse_mode="HTML", reply_markup=None)
    except Exception:
        pass

    # Если есть ID тикета, обновляем клавиатуру тикета (с новым счетчиком бонусов)
    if ticket_msg_id and ticket_msg_id > 0:
        try:
            chat_id = callback.message.chat.id
            username = target_user.get('username')
            updated_kb = build_ticket_keyboard(target_user_id, ticket_msg_id, username)
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=ticket_msg_id,
                reply_markup=updated_kb
            )
        except Exception as e:
            print(f"⚠️ Ошибка обновления тикета: {e}")

    await callback.answer(f"✅ Начислено +{days} {days_word}!", show_alert=True)


@dp.callback_query(F.data.startswith("view_bonus_history_"))
async def view_bonus_history_handler(callback: types.CallbackQuery):
    """Отображение подробной истории всех бонусов пользователя для администраторов."""
    try:
        target_user_id = int(callback.data.replace("view_bonus_history_", ""))
    except ValueError:
        await callback.answer("⚠️ Некорректный ID пользователя", show_alert=True)
        return

    summary = get_user_bonus_summary(target_user_id)
    review_status = "✅ Выдан (+7 дн.)" if summary["has_review_bonus"] else "⚪ Не выдавался"
    extra_days = summary["extra_days"]
    extra_count = summary["extra_count"]
    history = summary["extra_history"]

    history_lines = []
    for item in history[-5:]:
        dt_str = item.get("awarded_at", "")[:10]
        adm = item.get("awarded_by_name", "Админ")
        history_lines.append(f"• +{item.get('days', 3)} дн. ({dt_str}) — {adm}")

    history_text = "\n".join(history_lines) if history_lines else "Доп. бонусов не выдавалось"

    alert_text = (
        f"📊 Статистика бонусов ID {target_user_id}:\n\n"
        f"🎁 За отзыв (+7 дн.): {review_status}\n"
        f"⚡ Доп. бонусов (сверх отзыва): {extra_days} дн. (выдано раз: {extra_count})\n\n"
        f"История компенсаций:\n{history_text}"
    )

    await callback.answer(alert_text, show_alert=True)


@dp.message(Command("bonuses"))
@dp.message(Command("bonus_stats"))
async def admin_bonus_stats_command(message: types.Message):
    """Команда для администраторов: просмотр сводной статистики и счетчиков выданных бонусов."""
    rewards = load_review_rewards()
    total_reviews = sum(1 for r in rewards.values() if r.get("review_bonus", True))
    total_extra_days = sum(r.get("extra_bonus_days", 0) for r in rewards.values())
    total_extra_grants = sum(len(r.get("extra_bonuses", [])) for r in rewards.values())

    args = message.text.split()
    if len(args) > 1 and args[1].isdigit():
        uid = int(args[1])
        summary = get_user_bonus_summary(uid)
        rev_str = "✅ Выдан (+7 дн.)" if summary["has_review_bonus"] else "⚪ Не выдавался"
        e_days = summary["extra_days"]
        e_count = summary["extra_count"]

        hist_lines = [f"• +{h.get('days', 3)} дн. ({h.get('awarded_at', '')[:10]}) — {h.get('awarded_by_name', '')}" for h in summary['extra_history'][-5:]]
        hist_text = "\n".join(hist_lines) if hist_lines else "Доп. начислений нет"

        resp = (
            f"📊 <b>Бонусный профиль пользователя {uid}:</b>\n\n"
            f"🎁 <b>Бонус за отзыв:</b> {rev_str}\n"
            f"⚡ <b>Доп. дней бонуса:</b> <b>{e_days} дн.</b> (начислено {e_count} раз)\n\n"
            f"<b>История последних начислений:</b>\n{hist_text}"
        )
        await message.answer(resp, parse_mode="HTML")
        return

    top_extras = sorted(
        [r for r in rewards.values() if r.get("extra_bonus_days", 0) > 0],
        key=lambda x: x.get("extra_bonus_days", 0),
        reverse=True
    )[:5]

    top_lines = [f"• ID <code>{r.get('telegram_id')}</code>: <b>{r.get('extra_bonus_days')} дн.</b>" for r in top_extras]
    top_text = "\n".join(top_lines) if top_lines else "Пока нет выданных доп. бонусов"

    resp = (
        f"📊 <b>Сводная статистика бонусов:</b>\n\n"
        f"🎁 <b>Бонусов за отзывы (+7 дн.):</b> {total_reviews}\n"
        f"⚡ <b>Всего выдано доп. дней (сверх отзыва):</b> {total_extra_days} дн.\n"
        f"🎯 <b>Количество компенсаций/начислений:</b> {total_extra_grants} раз\n\n"
        f"🏆 <b>Топ пользователей по компенсациям:</b>\n{top_text}\n\n"
        f"<i>💡 Для проверки пользователя: <code>/bonuses &lt;user_id&gt;</code></i>"
    )
    await message.answer(resp, parse_mode="HTML")


@dp.callback_query(F.data == "send_pending_as_review")
async def send_pending_as_review_handler(callback: types.CallbackQuery):
    tg_user = callback.from_user
    user_id = tg_user.id
    pending_msg = PENDING_SUPPORT_MESSAGE.pop(user_id, None)

    if not pending_msg:
        await callback.answer("Сообщение уже передано или устарело", show_alert=False)
        await faq_review_handler(callback)
        return

    already_awarded = has_user_received_review_bonus(user_id)
    already_submitted = has_user_submitted_first_review(user_id)
    is_pending = is_user_review_pending(user_id)

    # 1. Если первый отзыв уже отправлен и ожидает проверки
    if already_submitted and not already_awarded:
        await callback.answer("⏳ Ваш первый отзыв уже на проверке (+7 дней)!", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
        await callback.message.answer(
            "⏳ <b>Ваш первый отзыв уже находится на проверке!</b>\n\n"
            "Вы уже отправили отзыв команде гида. Пожалуйста, дождитесь начисления бонуса администратором прямо в этот диалог 🎉",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
            ])
        )
        return

    # 2. Если уже есть отзыв на рассмотрении (лимит 1/1)
    if is_pending:
        await callback.answer("⏳ Лимит повторных отзывов (1/1). Ожидайте ответа команды!", show_alert=True)
        try:
            await callback.message.delete()
        except Exception:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
        await callback.message.answer(
            "⏳ <b>Лимит повторных отзывов (1/1)</b>\n\n"
            "Вы уже отправили отзыв, который ожидает рассмотрения командой гида 💌\n\n"
            "Пожалуйста, дождитесь ответа администратора прямо в этот диалог. "
            "Как только администратор ответит вам — возможность отправить новый отзыв возобновится!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
            ])
        )
        return

    is_repeat = already_awarded or already_submitted

    try:
        if not is_repeat:
            mark_user_first_review_submitted(user_id)
            await send_ticket_to_support(pending_msg, tg_user, is_review=True, is_repeat_review=False)
            ack_text = (
                f"✅ <b>Большое спасибо за ваш отзыв!</b> ❤️\n\n"
                f"Мы передали его команде гида. После быстрой проверки администратор начислит вам <b>бонус +7 дней</b> к доступу! 🎉"
            )
        else:
            increment_user_unanswered_reviews(user_id)
            await send_ticket_to_support(pending_msg, tg_user, is_review=True, is_repeat_review=True)
            ack_text = (
                f"✅ <b>Большое спасибо за ваш отзыв!</b> 💌\n\n"
                f"Мы передали его Даше и команде гида. Спасибо за вашу тёплую поддержку проекта! ✨\n\n"
                f"<i>(Напоминаем: бонус +7 дней начисляется 1 раз на аккаунт за первый отзыв)</i>"
            )

        try:
            await callback.message.delete()
        except Exception:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

        ack_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
        ])
        await callback.message.answer(ack_text, parse_mode="HTML", reply_markup=ack_kb)
        await callback.answer("Отзыв передан команде! 💌")
    except Exception as e:
        print(f"⚠️ Ошибка отправки отложенного отзыва: {e}")
        await callback.answer("Ошибка при отправке, попробуйте снова.", show_alert=True)


@dp.callback_query(F.data == "send_pending_to_support")
async def send_pending_to_support_handler(callback: types.CallbackQuery):
    tg_user = callback.from_user
    user = get_or_create_user(tg_user)
    if is_user_banned(user):
        await callback.answer("⛔️ Ваш аккаунт заблокирован", show_alert=True)
        return

    unanswered_cnt = get_user_unanswered_support(tg_user.id)
    if unanswered_cnt >= 3:
        await callback.answer("⚠️ Достигнут лимит (3/3). Ожидайте ответа поддержки!", show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.answer(
            "⚠️ <b>Лимит обращений исчерпан (3/3)</b>\n\n"
            "Вы уже отправили 3 сообщения в поддержку, ожидающих ответа.\n"
            "Пожалуйста, дождитесь ответа администратора перед отправкой новых обращений 🙏",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
            ])
        )
        return

    pending_msg = PENDING_SUPPORT_MESSAGE.pop(tg_user.id, None)

    if not pending_msg:
        await callback.answer("Сообщение уже передано или устарело", show_alert=False)
        await contact_support_handler(callback)
        return

    try:
        await send_ticket_to_support(pending_msg, tg_user, is_addition=True)
        new_cnt = increment_user_unanswered_support(tg_user.id)
        try:
            await callback.message.delete()
        except Exception:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

        if new_cnt >= 3:
            await callback.message.answer(
                "✅ <b>Сообщение успешно передано в поддержку! (3/3)</b>\n\n"
                "Мы добавили его к вашему обращению и скоро ответим прямо сюда 💌\n\n"
                "⏳ <i>Достигнут лимит 3 сообщений. Приём новых обращений возобновится сразу после ответа администратора!</i>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
                ])
            )
        else:
            await callback.message.answer(
                f"✅ <b>Сообщение успешно передано в поддержку!</b> ({new_cnt}/3)\n\n"
                f"Мы добавили его к вашему обращению и скоро ответим прямо сюда 💌\n\n"
                f"💡 <i>Если потребуется написать что-то ещё — обязательно снова нажмите кнопку <b>«💬 Дополнить вопрос»</b> перед отправкой сообщения:</i>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💬 Дополнить вопрос", callback_data="contact_support")],
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
                ])
            )
        await callback.answer("Передано в поддержку! 💌")
    except Exception as e:
        print(f"⚠️ Ошибка отправки отложенного тикета: {e}")
        await callback.answer("Ошибка при отправке, попробуйте снова.", show_alert=True)


@dp.callback_query(F.data == "cancel_pending_support")
async def cancel_pending_support_handler(callback: types.CallbackQuery):
    PENDING_SUPPORT_MESSAGE.pop(callback.from_user.id, None)
    await callback.answer("Отменено")
    await back_to_start_handler(callback)


@dp.message()
async def general_message_handler(message: types.Message):
    """
    Обработка входящих сообщений:
    1. Администратор вводит ответ пользователю (после нажатия кнопки «Ответить»).
    2. Пользователь ожидает отправки вопроса в поддержку — формируем тикет администратору.
    3. Обычный текст вне режима ввода — сохраняем и даем выбор отправить в поддержку или открыть меню.
    """
    tg_user = message.from_user
    if not tg_user:
        return
    user_id = tg_user.id

    # 1. Администратор отвечает на обращение через кнопку
    if user_id in ADMIN_WAITING_REPLY:
        target_user_id = ADMIN_WAITING_REPLY.pop(user_id)
        try:
            await deliver_admin_reply_to_user(target_user_id, message)
            await message.reply(f"✅ <b>Ответ успешно доставлен пользователю!</b>\n(ID: <code>{target_user_id}</code>)", parse_mode="HTML")
        except Exception as e:
            await message.reply(f"⚠️ Ошибка доставки ответа пользователю {target_user_id}:\n<code>{e}</code>", parse_mode="HTML")
        return

    # 2. Администратор вводит произвольное количество дней для бонуса
    if user_id in ADMIN_WAITING_CUSTOM_DAYS:
        state_data = ADMIN_WAITING_CUSTOM_DAYS.get(user_id, {})
        target_user_id = state_data.get("target_user_id")
        ticket_msg_id = state_data.get("ticket_msg_id", 0)
        raw_text = (message.text or "").strip()

        if not raw_text.isdigit() or int(raw_text) <= 0 or int(raw_text) > 3650:
            await message.reply(
                "⚠️ Пожалуйста, введите целое положительное число дней (например, <code>10</code> или <code>30</code>):",
                parse_mode="HTML"
            )
            return

        ADMIN_WAITING_CUSTOM_DAYS.pop(user_id, None)
        days = int(raw_text)
        days_word = get_days_word(days)

        confirm_text = (
            f"❓ <b>Подтверждение выдачи:</b>\n\n"
            f"Начислить <b>+{days} {days_word}</b> пользователю ID <code>{target_user_id}</code>?\n\n"
            f"💬 <b>Пользователю будет отправлено сообщение:</b>\n"
            f"<i>«🎁 <b>Вам начислен приятный бонус: +{days} {days_word} к доступу!</b> ✨\n\n"
            f"Даша и команда гида благодарят вас за то, что вы с нами! Мы ценим ваше доверие и хотим, чтобы приложение приносило только радость ❤️\n\n"
            f"📅 Доступ успешно продлён...»</i>\n\n"
            f"<b>Точно выдать?</b>"
        )
        confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=f"✅ Точно выдать +{days} дн.", callback_data=f"cdo_{target_user_id}_{days}_{ticket_msg_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data=f"ccancel_{target_user_id}")
            ]
        ])
        await message.reply(confirm_text, parse_mode="HTML", reply_markup=confirm_kb)
        return

    # Проверка на блокировку аккаунта
    user_db = get_or_create_user(tg_user)
    if is_user_banned(user_db):
        await message.answer(BANNED_MESSAGE, parse_mode="HTML")
        return

    # 2. Пользователь пишет отзыв о приложении
    if user_id in USER_REVIEW_WAITING:
        USER_REVIEW_WAITING.pop(user_id, None)

        is_repeat = has_user_submitted_first_review(user_id) or has_user_received_review_bonus(user_id)
        if is_repeat:
            unanswered_rev = get_user_unanswered_reviews(user_id)
            if unanswered_rev >= 1:
                await message.answer(
                    "⏳ <b>Лимит повторных отзывов (1/1)</b>\n\n"
                    "Вы уже отправили отзыв, ожидающий рассмотрения командой гида 💌\n\n"
                    "Пожалуйста, дождитесь ответа администратора прямо в этот диалог. "
                    "Как только администратор ответит вам — возможность отправить новый отзыв возобновится!",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
                    ])
                )
                return

        try:
            if not is_repeat:
                mark_user_first_review_submitted(user_id)
                await send_ticket_to_support(message, tg_user, is_review=True, is_repeat_review=False)
                ack_text = (
                    f"✅ <b>Большое спасибо за ваш отзыв!</b> ❤️\n\n"
                    f"Мы передали его команде гида. После быстрой проверки администратор начислит вам <b>бонус +7 дней</b> к доступу! 🎉"
                )
            else:
                increment_user_unanswered_reviews(user_id)
                await send_ticket_to_support(message, tg_user, is_review=True, is_repeat_review=True)
                ack_text = (
                    f"✅ <b>Большое спасибо за ваш отзыв!</b> 💌\n\n"
                    f"Мы передали его Даше и команде гида. Спасибо за вашу тёплую поддержку проекта! ✨\n\n"
                    f"<i>(Напоминаем: бонус +7 дней начисляется 1 раз на аккаунт за первый отзыв)</i>"
                )
            ack_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
            ])
            await message.answer(ack_text, parse_mode="HTML", reply_markup=ack_kb)
        except Exception as e:
            print(f"⚠️ Ошибка отправки отзыва: {e}")
            await message.answer(
                f"⚠️ Не удалось автоматически отправить отзыв.\n\n"
                f"Пожалуйста, напишите напрямую автору проекта: @{ADMIN_USERNAME}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=f"💌 Написать @{ADMIN_USERNAME}", url=f"https://t.me/{ADMIN_USERNAME}")]
                ])
            )
        return

    # 2.5 Пользователь отправляет предложение локации в гид
    if user_id in USER_SUGGESTION_WAITING:
        USER_SUGGESTION_WAITING.pop(user_id, None)
        try:
            await send_ticket_to_support(message, tg_user, is_suggestion=True)
            ack_text = (
                f"✅ <b>Большое спасибо за вашу рекомендацию!</b> 💌\n\n"
                f"Мы передали информацию Даше и команде гида. Мы обязательно изучим это место и добавим его на карту, если оно подходит по стилю и концепции проекта! ✨"
            )
            ack_kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🗺️ Открыть карту в Telegram", web_app=WebAppInfo(url=WEBAPP_URL))],
                [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
            ])
            await message.answer(ack_text, parse_mode="HTML", reply_markup=ack_kb)
        except Exception as e:
            print(f"⚠️ Ошибка отправки предложения локации: {e}")
            await message.answer(
                f"⚠️ Не удалось автоматически отправить предложение.\n\n"
                f"Пожалуйста, отправьте рекомендацию напрямую автору проекта: @{ADMIN_USERNAME}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=f"💌 Написать @{ADMIN_USERNAME}", url=f"https://t.me/{ADMIN_USERNAME}")]
                ])
            )
        return

    # 3. Пользователь пишет вопрос в поддержку (нажал кнопку «Задать вопрос» или «Дополнить»)
    if user_id in SUPPORT_WAITING_USERS:
        SUPPORT_WAITING_USERS.pop(user_id, None)
        unanswered_count = get_user_unanswered_support(user_id)
        if unanswered_count >= 3:
            await message.answer(
                "⚠️ <b>Лимит обращений исчерпан (3/3)</b>\n\n"
                "Вы уже отправили 3 сообщения в поддержку, которые ожидают ответа. "
                "Пожалуйста, дождитесь ответа администратора прямо в этот чат 💌\n\n"
                "Как только специалист ответит вам — приём сообщений возобновится!",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
                ])
            )
            return

        try:
            await send_ticket_to_support(message, tg_user, is_addition=False)
            new_cnt = increment_user_unanswered_support(user_id)
            if new_cnt >= 3:
                await message.answer(
                    "✅ <b>Ваш вопрос передан в поддержку! (3/3)</b>\n\n"
                    "Мы получили ваше обращение и скоро ответим прямо сюда, в этот диалог 💌\n\n"
                    "⏳ <i>Вы отправили 3 сообщения подряд. Приём новых сообщений временно приостановлен до ответа администратора. Мы уже изучаем ваши сообщения!</i>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
                    ])
                )
            else:
                await message.answer(
                    f"✅ <b>Ваш вопрос передан в поддержку!</b> ({new_cnt}/3)\n\n"
                    f"Мы получили ваше обращение и скоро ответим прямо сюда, в этот диалог 💌\n\n"
                    f"💡 <i>Если вы хотите что-то добавить к вопросу, пожалуйста, обязательно нажмите кнопку <b>«💬 Дополнить вопрос»</b> ниже перед отправкой следующего сообщения:</i>",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💬 Дополнить вопрос", callback_data="contact_support")],
                        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
                    ])
                )
        except Exception as e:
            print(f"⚠️ Ошибка отправки обращения в поддержку: {e}")
            await message.answer(
                f"⚠️ Не удалось автоматически отправить обращение в поддержку.\n\n"
                f"Пожалуйста, напишите напрямую автору проекта: @{ADMIN_USERNAME}",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=f"💌 Написать @{ADMIN_USERNAME}", url=f"https://t.me/{ADMIN_USERNAME}")]
                ])
            )
        return

    # 4. Пользователь отправил обычное текстовое сообщение или медиа вне активного ввода
    PENDING_SUPPORT_MESSAGE[user_id] = message
    unanswered_cnt = get_user_unanswered_support(user_id)

    short_snippet = ""
    if message.text:
        escaped_txt = message.text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        short_snippet = f"«<i>{escaped_txt[:120]}{'...' if len(escaped_txt) > 120 else ''}</i>»\n\n"
    elif message.photo:
        short_snippet = "<i>[Прикреплённая фотография/скриншот]</i>\n\n"
    elif message.voice:
        short_snippet = "<i>[Голосовое сообщение]</i>\n\n"
    elif message.document:
        short_snippet = "<i>[Документ/файл]</i>\n\n"

    is_first_review = not (has_user_submitted_first_review(user_id) or has_user_received_review_bonus(user_id))
    unanswered_rev = get_user_unanswered_reviews(user_id)
    review_blocked = (not is_first_review) and (unanswered_rev >= 1)

    if unanswered_cnt >= 3 and review_blocked:
        warn_text = (
            f"ℹ️ <b>Вы отправили сообщение в чат бота:</b>\n"
            f"{short_snippet}"
            f"⏳ <b>Все лимиты обращений исчерпаны:</b>\n"
            f"Все ваши предыдущие сообщения и отзыв уже переданы команде гида и ожидают ответа 💌\n\n"
            f"Пожалуйста, дождитесь ответа службы поддержки прямо в этот диалог перед отправкой новых сообщений 🙏"
        )
        warn_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_start")]
        ])
    elif unanswered_cnt >= 3:
        review_btn_title = "✍️ Отправить как первый отзыв (+7 дней)" if is_first_review else "✍️ Отправить как тёплый отзыв"
        warn_text = (
            f"ℹ️ <b>Вы отправили сообщение в чат бота:</b>\n"
            f"{short_snippet}"
            f"⏳ <b>Лимит обращений в поддержку (3/3):</b>\n"
            f"Вы уже отправили 3 сообщения, ожидающих ответа. Дождитесь ответа специалиста службы поддержки прямо в этот диалог 💌\n\n"
            f"Либо вы можете отправить это сообщение как отзыв о гиде:"
        )
        warn_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=review_btn_title, callback_data="send_pending_as_review")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_pending_support")]
        ])
    else:
        warn_text = (
            f"ℹ️ <b>Вы отправили сообщение в чат бота:</b>\n"
            f"{short_snippet}"
            f"Если вы хотите передать этот текст или фото команде гида, выберите действие:"
        )
        buttons = [
            [InlineKeyboardButton(text=f"💬 Отправить в поддержку ({unanswered_cnt}/3)", callback_data="send_pending_to_support")]
        ]
        if not review_blocked:
            review_btn_title = "✍️ Отправить как отзыв (+7 дней)" if is_first_review else "✍️ Отправить как тёплый отзыв"
            buttons.append([InlineKeyboardButton(text=review_btn_title, callback_data="send_pending_as_review")])
        buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_pending_support")])
        warn_kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await message.answer(warn_text, parse_mode="HTML", reply_markup=warn_kb)


# -------------------------------------------------------------
# ВЕБ-СЕРВЕР ДЛЯ ПОДДЕРЖАНИЯ АКТИВНОСТИ (HEALTH CHECK)
# -------------------------------------------------------------

async def handle_ping(request):
    return web.Response(text="Bot is running OK 24/7", status=200)

async def run_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    port = int(os.getenv("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Веб-сервер health-check запущен на порту {port}")


async def main():
    print("Запуск бота и сопутствующего веб-сервера...")
    await run_web_server()
    await bot.delete_webhook(drop_pending_updates=True)
    try:
        await bot.set_chat_menu_button(menu_button=types.MenuButtonWebApp(text="🗺️ Карта", web_app=WebAppInfo(url=WEBAPP_URL)))
        print(f"Кнопка меню обновлена на: {WEBAPP_URL}")
    except Exception as e:
        print(f"Не удалось обновить menu_button: {e}")
    print("Бот запущен и ожидает обновлений...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
