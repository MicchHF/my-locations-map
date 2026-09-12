#!/bin/bash
set -e

echo "=== Обновление проекта dalazareva.ru / map.dalazareva.ru ==="

# Разрешаем git работать без ошибок ownership
git config --global --add safe.directory '*' 2>/dev/null || true

REPO="https://github.com/MicchHF/my-locations-map.git"

DIRS=("/var/www/map.dalazareva.ru" "/var/www/dalazareva.ru" "/var/www/dalazareva-prod" "/root/dalazareva-prod" "/root/my-locations-map")

for DIR in "${DIRS[@]}"; do
    if [ -d "$DIR" ]; then
        echo "--> Обновление каталога: $DIR"
        cd "$DIR"
        
        if [ ! -d ".git" ]; then
            echo "Инициализация git в $DIR..."
            git init
            git remote add origin "$REPO" 2>/dev/null || git remote set-url origin "$REPO"
        else
            git remote set-url origin "$REPO"
        fi
        
        # Сохраняем .env перед очисткой, если он есть
        [ -f .env ] && cp .env /tmp/dalazareva_env_backup 2>/dev/null || true

        # Очищаем все конфликтующие файлы кроме .git, .env, photos и venv
        find . -maxdepth 1 ! -name '.git' ! -name '.env' ! -name 'photos' ! -name 'venv' ! -name '.' -exec rm -rf {} +

        # Принудительно затягиваем свежую ветку main с GitHub
        git fetch origin main
        git checkout -B main origin/main
        git reset --hard origin/main

        # Восстанавливаем .env
        [ -f /tmp/dalazareva_env_backup ] && cp /tmp/dalazareva_env_backup .env 2>/dev/null || true
        
        # Убеждаемся, что index.html - это интерактивная карта с полем авторизации и ботом
        git checkout origin/main -- index.html 2>/dev/null || true

        # Запуск синхронизации фото с Supabase на диск сервера (Nginx кэш)
        if [ -f "$DIR/sync_photos.py" ]; then
            echo "--> Синхронизация фото локаций на SSD сервера..."
            python3 "$DIR/sync_photos.py" "$DIR/photos" || true
        fi

        # Права для веб-сервера
        chown -R www-data:www-data "$DIR" 2>/dev/null || true
        chmod -R 755 "$DIR" 2>/dev/null || true
        echo "--> Каталог $DIR успешно синхронизирован с GitHub!"
    fi
done

# Перезапуск бота (если служба настроена)
if [ -f /etc/systemd/system/dalazareva-bot.service ]; then
    echo "--> Перезапуск Telegram-бота..."
    systemctl restart dalazareva-bot 2>/dev/null || true
fi

# Проверка и перезагрузка Nginx
if command -v nginx >/dev/null 2>&1; then
    # Отключаем конфликтующий дефолтный сайт
    rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
    
    # На обоих сайтах главной страницей должна быть интерактивная карта (index.html)
    for SITE_CONF in /etc/nginx/sites-available/dalazareva.ru /etc/nginx/sites-available/map.dalazareva.ru; do
        if [ -f "$SITE_CONF" ]; then
            sed -i 's|index taplink_index.html taplink.html index.html;|index index.html;|g' "$SITE_CONF"
        fi
    done
    echo "--> Перезагрузка Nginx..."
    nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true
fi

echo "=== ✅ Все обновления успешно применены! ==="
echo "ℹ️ Если на iPhone / Safari отображается ошибка 'не удалось установить безопасное соединение':"
echo "👉 Запустите: sudo bash fix_ssl_and_nginx.sh"
