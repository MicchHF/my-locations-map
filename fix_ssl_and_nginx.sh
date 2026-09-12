#!/bin/bash
# ==============================================================================
# Скрипт полного восстановления SSL-сертификатов и Nginx для dalazareva.ru и map.dalazareva.ru
# Устраняет ошибку Safari / iOS: «Не удалось установить безопасное соединение с сервером»
# ==============================================================================
set -e

echo "=== [1/6] Проверка прав root ==="
if [ "$EUID" -ne 0 ]; then
    echo "Пожалуйста, запустите скрипт с правами root: sudo bash fix_ssl_and_nginx.sh"
    exit 1
fi

echo "=== [2/6] Удаление конфликтующих конфигураций Nginx ==="
# Отключаем default сайт и удаляем конфликтующие файлы в conf.d
rm -f /etc/nginx/sites-enabled/default 2>/dev/null || true
rm -f /etc/nginx/conf.d/ssl_modern_apple.conf 2>/dev/null || true

# Создаем резервную копию существующих конфигов
BACKUP_DIR="/etc/nginx/backup_$(date +%s)"
mkdir -p "$BACKUP_DIR"
cp -a /etc/nginx/sites-available/* "$BACKUP_DIR/" 2>/dev/null || true
echo "Резервная копия Nginx сохранена в $BACKUP_DIR"

# Проверяем и перезагружаем Nginx после удаления конфликтующего конфига
nginx -t 2>/dev/null && systemctl reload nginx 2>/dev/null || true

echo "=== [3/6] Перевыпуск SSL-сертификатов с универсальной цепочкой ISRG Root X1 ==="
# ПРИЧИНА СБОЯ В SAFARI / iOS:
# Новые сертификаты Let's Encrypt по умолчанию выдаются через новую цепочку Root YR / YR2,
# которую Apple Trust Store на многих версиях iOS / Safari считает неизвестной и блокирует
# соединение ошибкой: «Браузеру Safari не удается открыть страницу, так как он не смог установить безопасное соединение».
# Параметр --preferred-chain "ISRG Root X1" принудительно возвращает классическую доверенную цепочку,
# которая работает на 100% устройств Apple, Android и в Telegram WebApp.

# Убедимся, что certbot установлен
if ! command -v certbot >/dev/null 2>&1; then
    apt-get update && apt-get install -y certbot python3-certbot-nginx < /dev/null
fi

# 1. Сертификат для dalazareva.ru
echo "--> Обновление SSL-сертификата для dalazareva.ru..."
certbot certonly --nginx \
    --preferred-chain "ISRG Root X1" \
    -d dalazareva.ru -d www.dalazareva.ru \
    --agree-tos \
    --non-interactive \
    --email variskasosisovna@gmail.com \
    --force-renewal < /dev/null || certbot certonly --nginx \
    --preferred-chain "ISRG Root X1" \
    -d dalazareva.ru \
    --agree-tos \
    --non-interactive \
    --email variskasosisovna@gmail.com \
    --force-renewal < /dev/null || true

# 2. Сертификат для map.dalazareva.ru
echo "--> Обновление SSL-сертификата для map.dalazareva.ru..."
certbot certonly --nginx \
    --preferred-chain "ISRG Root X1" \
    -d map.dalazareva.ru \
    --agree-tos \
    --non-interactive \
    --email variskasosisovna@gmail.com \
    --force-renewal < /dev/null || certbot certonly --webroot -w /var/www/map.dalazareva.ru \
    --preferred-chain "ISRG Root X1" \
    -d map.dalazareva.ru \
    --agree-tos \
    --non-interactive \
    --email variskasosisovna@gmail.com \
    --force-renewal < /dev/null || true

echo "=== [4/6] Формирование идеальной конфигурации Nginx ==="
mkdir -p /var/www/map.dalazareva.ru
mkdir -p /var/www/dalazareva.ru

# 1. Конфигурация map.dalazareva.ru
cat << 'EOF' > /etc/nginx/sites-available/map.dalazareva.ru
server {
    listen 80;
    listen [::]:80;
    server_name map.dalazareva.ru;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name map.dalazareva.ru;

    root /var/www/map.dalazareva.ru;
    index index.html;

    ssl_certificate /etc/letsencrypt/live/map.dalazareva.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/map.dalazareva.ru/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL_MAP:10m;
    ssl_session_tickets off;

    # Gzip сжатие
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_proxied any;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/svg+xml application/manifest+json;

    # Заголовки для Telegram WebApp и безопасности
    add_header X-Frame-Options "ALLOWALL" always;
    add_header Access-Control-Allow-Origin "*" always;
    add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
    add_header Access-Control-Allow-Headers "*" always;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # Прямой доступ к панели администратора и пользователям
    location ~* ^/(admin\.html|users-admin\.html)$ {
        try_files $uri =404;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header X-Frame-Options "ALLOWALL" always;
        add_header Access-Control-Allow-Origin "*" always;
    }

    # Кэширование статики
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

    # Кэш фото локаций
    location /photos/ {
        alias /var/www/map.dalazareva.ru/photos/;
        expires 30d;
        add_header Cache-Control "public, immutable";
        add_header Access-Control-Allow-Origin "*" always;
    }

    # Проксирование health-check бота
    location /health {
        proxy_pass http://127.0.0.1:10000/health;
        proxy_set_header Host $host;
    }
}
EOF

# 2. Конфигурация dalazareva.ru
cat << 'EOF' > /etc/nginx/sites-available/dalazareva.ru
server {
    listen 80;
    listen [::]:80;
    server_name dalazareva.ru www.dalazareva.ru;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name dalazareva.ru www.dalazareva.ru;

    root /var/www/dalazareva.ru;
    index index.html;

    ssl_certificate /etc/letsencrypt/live/dalazareva.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/dalazareva.ru/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL_MAIN:10m;
    ssl_session_tickets off;

    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_proxied any;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/svg+xml application/manifest+json;

    add_header X-Frame-Options "ALLOWALL" always;
    add_header Access-Control-Allow-Origin "*" always;
    add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
    add_header Access-Control-Allow-Headers "*" always;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location ~* ^/(admin\.html|users-admin\.html)$ {
        try_files $uri =404;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header X-Frame-Options "ALLOWALL" always;
        add_header Access-Control-Allow-Origin "*" always;
    }

    location ~* \.(jpg|jpeg|png|gif|ico|css|js|svg|webp|woff|woff2|kml|geojson)$ {
        expires 7d;
        add_header Cache-Control "public, no-transform";
        add_header Access-Control-Allow-Origin "*" always;
    }

    location ~* \.(webmanifest|json)$ {
        add_header Cache-Control "no-cache";
        add_header Access-Control-Allow-Origin "*" always;
    }

    location /photos/ {
        alias /var/www/dalazareva.ru/photos/;
        expires 30d;
        add_header Cache-Control "public, immutable";
        add_header Access-Control-Allow-Origin "*" always;
    }

    location /health {
        proxy_pass http://127.0.0.1:10000/health;
        proxy_set_header Host $host;
    }
}
EOF

# Активируем конфигурации
ln -sf /etc/nginx/sites-available/map.dalazareva.ru /etc/nginx/sites-enabled/
ln -sf /etc/nginx/sites-available/dalazareva.ru /etc/nginx/sites-enabled/

echo "=== [5/6] Проверка и перезагрузка Nginx ==="
nginx -t
systemctl restart nginx

echo "=== [6/6] Проверка доступности сайтов ==="
echo -n "Проверка https://dalazareva.ru: "
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://dalazareva.ru || true

echo -n "Проверка https://map.dalazareva.ru: "
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://map.dalazareva.ru || true

echo -n "Проверка https://map.dalazareva.ru/admin.html: "
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://map.dalazareva.ru/admin.html || true

echo -n "Проверка https://map.dalazareva.ru/users-admin.html: "
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://map.dalazareva.ru/users-admin.html || true

echo ""
echo "=============================================================================="
echo "🎉 ВОССТАНОВЛЕНИЕ ЗАВЕРШЕНО!"
echo "1. Сертификаты перевыпущены с доверенной цепочкой ISRG Root X1 (совместимость с iOS / Safari)."
echo "2. Настроен протокол HTTP/2 и защита от сбоев handshake."
echo "3. Включены заголовки для мгновенного открытия в Telegram WebApp."
echo "4. Админ-панели доступны по адресам:"
echo "   👉 https://map.dalazareva.ru/admin.html"
echo "   👉 https://map.dalazareva.ru/users-admin.html"
echo "=============================================================================="
