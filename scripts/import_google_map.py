#!/usr/bin/env python3
"""
Скрипт импорта меток из Google My Maps (KML) в таблицу Supabase `Location`.
Категория: '📎 Другое'
Поддерживает работу через сессию Supabase (email + password) или прямой токен доступа.
"""

import sys
import os
import re
import json
import math
import argparse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://cwkgylbtcjfmweoldhyb.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_KnWO20wlfuWd0NYKMNKRvw_l1rttjaT")


def calc_dist(lat1, lon1, lat2, lon2):
    R = 6371e3
    p1 = lat1 * math.pi / 180
    p2 = lat2 * math.pi / 180
    dp = (lat2 - lat1) * math.pi / 180
    dl = (lon2 - lon1) * math.pi / 180
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def load_places_from_json(json_path="data/google_mymaps_locations.json"):
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def authenticate_supabase(email, password):
    url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
    headers = {
        "apikey": SUPABASE_KEY,
        "Content-Type": "application/json"
    }
    payload = json.dumps({"email": email, "password": password}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("access_token")
    except urllib.error.HTTPError as e:
        print(f"Ошибка аутентификации: {e.code} - {e.read().decode('utf-8')}")
        return None
    except Exception as e:
        print(f"Ошибка соединения при входе: {e}")
        return None


def fetch_existing_locations(access_token):
    url = f"{SUPABASE_URL}/rest/v1/Location?select=id,title,lat,lng,category"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {access_token}"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Предупреждение: не удалось получить существующие локации: {e}")
        return []


def insert_batch(batch, access_token):
    url = f"{SUPABASE_URL}/rest/v1/Location"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    payload = json.dumps(batch).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        return None, f"HTTP {e.code}: {err_msg}"
    except Exception as e:
        return None, str(e)


def main():
    parser = argparse.ArgumentParser(description="Импорт локаций из Google My Maps в Supabase")
    parser.add_argument("--email", help="Email администратора для входа в Supabase")
    parser.add_argument("--password", help="Пароль администратора")
    parser.add_argument("--token", help="JWT access_token напрямую (если уже есть)")
    parser.add_argument("--skip-duplicates", action="store_true", default=True, help="Пропускать дубликаты")
    parser.add_argument("--dry-run", action="store_true", help="Проверить данные без вставки в базу")

    args = parser.parse_args()

    places = load_places_from_json()
    if not places:
        print("Файл data/google_mymaps_locations.json не найден!")
        sys.exit(1)

    print(f"Загружено {len(places)} мест из подготовленного файла карты.")

    if args.dry_run:
        print("Режим DRY-RUN. Вставка в базу выполняться не будет.")
        print("Пример первой записи:")
        print(json.dumps(places[0], ensure_ascii=False, indent=2))
        return

    access_token = args.token
    if not access_token:
        if not args.email or not args.password:
            print("Для выполнения импорта укажите --email и --password администратора или --token.")
            print("Также вы можете запустить импорт в один клик прямо из панели управления admin.html!")
            sys.exit(1)
        print(f"Авторизация в Supabase как {args.email}...")
        access_token = authenticate_supabase(args.email, args.password)
        if not access_token:
            sys.exit(1)
        print("Авторизация успешна!")

    existing = fetch_existing_locations(access_token)
    print(f"Существующих меток в базе: {len(existing)}")

    to_insert = []
    skipped = 0

    for p in places:
        if args.skip_duplicates:
            is_dup = False
            for ex in existing:
                dist = calc_dist(p["lat"], p["lng"], ex["lat"], ex["lng"])
                if dist < 15 or (p["title"].lower().strip() == ex["title"].lower().strip() and dist < 200):
                    is_dup = True
                    break
            if is_dup:
                skipped += 1
                continue

        to_insert.append({
            "title": p["title"],
            "category": "📎 Другое",
            "extra_categories": p.get("extra_categories", []),
            "address": p.get("address", "Москва"),
            "lat": p["lat"],
            "lng": p["lng"],
            "description": p.get("description", ""),
            "images": p.get("images", []),
            "metro": p.get("metro", [])
        })

    print(f"Будет импортировано: {len(to_insert)} меток (пропущено дубликатов: {skipped})")

    batch_size = 20
    total_inserted = 0

    for i in range(0, len(to_insert), batch_size):
        batch = to_insert[i:i + batch_size]
        res, err = insert_batch(batch, access_token)
        if err:
            print(f"Ошибка при импорте пачки {i}..{i+len(batch)}: {err}. Пробуем по одной...")
            for single in batch:
                s_res, s_err = insert_batch([single], access_token)
                if not s_err:
                    total_inserted += 1
                else:
                    print(f"  Не удалось добавить '{single['title']}': {s_err}")
        else:
            total_inserted += len(batch)
            print(f"  Прогресс: {total_inserted} / {len(to_insert)}")

    print(f"\n✅ Импорт завершен! Успешно добавлено {total_inserted} меток в категорию '📎 Другое'.")


if __name__ == "__main__":
    main()
