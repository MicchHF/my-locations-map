#!/usr/bin/env python3
"""
Скрипт синхронизации всех фотографий локаций на локальный сервер (Nginx SSD).
Скачивает все фотографии из базы данных Supabase в локальную папку:
/var/www/map.dalazareva.ru/photos/

Преимущества:
- Фотографии отдаются напрямую с локального сервера через Nginx по HTTP/2 за 1-2 миллисекунды.
- Никаких внешних зависимостей от сторонних CDN или ограничений провайдеров в РФ.
- Автоматический пропуск уже скачанных файлов (повторный запуск занимает 1 секунду).
"""

import os
import sys
import json
import urllib.request
import urllib.parse
import concurrent.futures

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").strip() or "https://cwkgylbtcjfmweoldhyb.supabase.co"
SUPABASE_KEY = (os.getenv("SUPABASE_KEY") or "").strip() or "sb_publishable_KnWO20wlfuWd0NYKMNKRvw_l1rttjaT"
PHOTOS_DIR = (os.getenv("PHOTOS_DIR") or "").strip() or "/var/www/map.dalazareva.ru/photos"

def fetch_all_photo_urls():
    print("🔍 Запрос списка локаций из базы данных Supabase...")
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/Location?select=id,title,images",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}"
        }
    )
    with urllib.request.urlopen(req) as resp:
        locations = json.loads(resp.read().decode("utf-8"))

    photo_tasks = []
    for loc in locations:
        images = loc.get("images") or []
        for img_url in images:
            if not img_url or not isinstance(img_url, str):
                continue
            if "location-photos/" in img_url:
                rel_path = img_url.split("location-photos/")[1]
                photo_tasks.append((img_url, rel_path))

    return photo_tasks

def download_photo(task):
    img_url, rel_path = task
    target_path = os.path.join(PHOTOS_DIR, rel_path)
    if os.path.exists(target_path) and os.path.getsize(target_path) > 0:
        return "skipped"

    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    tmp_path = target_path + ".tmp"

    try:
        # Quote URL path if necessary for special characters
        split_url = urllib.parse.urlsplit(img_url)
        quoted_path = urllib.parse.quote(split_url.path)
        safe_url = urllib.parse.urlunsplit((split_url.scheme, split_url.netloc, quoted_path, split_url.query, split_url.fragment))
        
        req = urllib.request.Request(safe_url, headers={"User-Agent": "Mozilla/5.0 (ServerSync)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            with open(tmp_path, "wb") as f:
                f.write(resp.read())
        os.replace(tmp_path, target_path)
        return "downloaded"
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return f"error ({img_url}): {e}"

def main():
    global PHOTOS_DIR
    if len(sys.argv) > 1:
        PHOTOS_DIR = sys.argv[1]
    elif os.path.exists("/var/www/map.dalazareva.ru"):
        PHOTOS_DIR = "/var/www/map.dalazareva.ru/photos"
    else:
        PHOTOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "photos")

    os.makedirs(PHOTOS_DIR, exist_ok=True)

    print(f"📁 Папка сохранения фото: {PHOTOS_DIR}")
    tasks = fetch_all_photo_urls()
    print(f"📊 Всего найдено фото в базе: {len(tasks)}")

    downloaded = 0
    skipped = 0
    errors = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        results = executor.map(download_photo, tasks)
        for i, res in enumerate(results, 1):
            if res == "downloaded":
                downloaded += 1
            elif res == "skipped":
                skipped += 1
            else:
                errors += 1
            if i % 50 == 0 or i == len(tasks):
                print(f"⏳ Прогресс: {i}/{len(tasks)} (Скачано: {downloaded}, Пропущено уже имеющихся: {skipped}, Ошибок: {errors})")

    print(f"\n🎉 Синхронизация завершена!")
    print(f"✅ Скачано новых: {downloaded}")
    print(f"⏩ Уже было на диске: {skipped}")
    if errors > 0:
        print(f"⚠️ Ошибок: {errors}")

if __name__ == "__main__":
    main()
