#!/bin/bash
# ==============================================================================
# Скрипт переноса Интерактивной Карты на поддомен map.dalazareva.ru / map.lazareva.ru
# ==============================================================================
set -e

echo "=== [1/5] Создание директории для карты /var/www/map.dalazareva.ru ==="
MAP_DIR="/var/www/map.dalazareva.ru"

if [ -d "/var/www/dalazareva.ru" ] && [ ! -d "$MAP_DIR" ]; then
    echo "Копируем текущие файлы карты и бота в $MAP_DIR..."
    cp -a /var/www/dalazareva.ru "$MAP_DIR"
elif [ ! -d "$MAP_DIR" ]; then
    echo "Клонируем репозиторий карты в $MAP_DIR..."
    mkdir -p "$MAP_DIR"
    git clone https://github.com/MicchHF/dalazareva-prod.git "$MAP_DIR"
fi

chown -R www-data:www-data "$MAP_DIR"
chmod -R 755 "$MAP_DIR"

echo "=== [2/5] Обновление URL в Telegram-боте на map.dalazareva.ru ==="
if [ -f "$MAP_DIR/.env" ]; then
    sed -i 's|WEBAPP_URL=.*|WEBAPP_URL=https://map.dalazareva.ru|g' "$MAP_DIR/.env"
else
    echo "WEBAPP_URL=https://map.dalazareva.ru" >> "$MAP_DIR/.env"
fi

# Обновляем systemd службу бота, если она указывает на старую папку
if [ -f /etc/systemd/system/dalazareva-bot.service ]; then
    sed -i 's|WorkingDirectory=/var/www/dalazareva.ru|WorkingDirectory=/var/www/map.dalazareva.ru|g' /etc/systemd/system/dalazareva-bot.service
    sed -i 's|ExecStart=/var/www/dalazareva.ru|ExecStart=/var/www/map.dalazareva.ru|g' /etc/systemd/system/dalazareva-bot.service
    systemctl daemon-reload
    systemctl restart dalazareva-bot || true
fi

echo "=== [3/5] Настройка Nginx для поддомена карты ==="
cat << 'EOF' > /etc/nginx/sites-available/map.dalazareva.ru
server {
    listen 80;
    listen [::]:80;
    server_name map.dalazareva.ru map.lazareva.ru;

    root /var/www/map.dalazareva.ru;
    index index.html;

    # Gzip сжатие
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/svg+xml application/manifest+json;

    location / {
        try_files $uri $uri/ /index.html;
        # Разрешаем открытие в Telegram WebApp и внутри фреймов
        add_header X-Frame-Options "ALLOWALL" always;
        add_header Access-Control-Allow-Origin "*" always;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
        add_header Access-Control-Allow-Headers "*" always;
    }

    # Кэширование статики и ассетов
    location ~* \.(jpg|jpeg|png|gif|ico|css|js|svg|webp|woff|woff2|kml|geojson)$ {
        expires 7d;
        add_header Cache-Control "public, no-transform";
        add_header Access-Control-Allow-Origin "*" always;
    }

    # PWA манифест
    location ~* \.(webmanifest|json)$ {
        add_header Cache-Control "no-cache";
        add_header Access-Control-Allow-Origin "*" always;
    }

    # Проксирование health-check бота
    location /health {
        proxy_pass http://127.0.0.1:10000/health;
        proxy_set_header Host $host;
    }
}
EOF

# Активируем конфигурацию
ln -sf /etc/nginx/sites-available/map.dalazareva.ru /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx

echo "=== [4/5] Выпуск SSL-сертификата Let's Encrypt ==="
# Пытаемся выпустить SSL для поддоменов
certbot --nginx -d map.dalazareva.ru --non-interactive --agree-tos --email variskasosisovna@gmail.com --redirect || {
    echo "Предупреждение: для map.dalazareva.ru сертификат не выпустился (возможно DNS еще обновляются)."
}

if host map.lazareva.ru >/dev/null 2>&1; then
    certbot --nginx -d map.lazareva.ru --non-interactive --agree-tos --email variskasosisovna@gmail.com --redirect || true
fi

echo "=============================================================================="
echo "🎉 Готово! Карта настроена на поддомене:"
echo "👉 https://map.dalazareva.ru"
echo "=============================================================================="
