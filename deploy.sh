#!/bin/bash
# ==============================================================================
# Скрипт автоматического развертывания проекта dalazareva.ru на сервере Ubuntu
# ==============================================================================
set -e

echo "=== [1/5] Обновление системы и установка необходимых пакетов ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y nginx git python3 python3-pip python3-venv certbot python3-certbot-nginx curl ufw

echo "=== [2/5] Подготовка проекта из GitHub ==="
SITE_DIR="/var/www/dalazareva.ru"

# Разрешаем root работать с репозиторием
git config --global --add safe.directory "$SITE_DIR"

if [ -d "$SITE_DIR/.git" ]; then
    echo "Репозиторий уже есть, обновляем файлы..."
    cd "$SITE_DIR"
    git pull || true
else
    echo "Клонирование репозитория..."
    rm -rf "$SITE_DIR"
    if [ -n "$GITHUB_TOKEN" ]; then
        git clone "https://${GITHUB_TOKEN}@github.com/MicchHF/my-locations-map.git" "$SITE_DIR"
        git config --global credential.helper store
    else
        git clone https://github.com/MicchHF/my-locations-map.git "$SITE_DIR"
    fi
fi

chown -R www-data:www-data "$SITE_DIR"
chmod -R 755 "$SITE_DIR"

echo "=== [3/5] Настройка окружения Python для Telegram-бота ==="
cd "$SITE_DIR"
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install aiogram aiohttp supabase python-dotenv

# Создание службы автозапуска systemd для Telegram-бота
cat << 'EOF' > /etc/systemd/system/dalazareva-bot.service
[Unit]
Description=Daria Lazareva Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/var/www/dalazareva.ru
ExecStart=/var/www/dalazareva.ru/venv/bin/python3 bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable dalazareva-bot
systemctl restart dalazareva-bot

echo "=== [4/5] Настройка веб-сервера Nginx ==="
cat << 'EOF' > /etc/nginx/sites-available/dalazareva.ru
server {
    listen 80;
    listen [::]:80;
    server_name dalazareva.ru www.dalazareva.ru;

    root /var/www/dalazareva.ru;
    index taplink_index.html taplink.html index.html;

    # Сжатие gzip для быстрой загрузки
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/svg+xml;

    location / {
        try_files $uri $uri/ /taplink_index.html /index.html;
        # Разрешаем встраивание в Telegram WebApp
        add_header X-Frame-Options "ALLOWALL" always;
        add_header Access-Control-Allow-Origin "*" always;
    }

    # Кэширование статических файлов
    location ~* \.(jpg|jpeg|png|gif|ico|css|js|svg|webp|woff|woff2)$ {
        expires 7d;
        add_header Cache-Control "public, no-transform";
    }

    # Проксирование health-check бота
    location /health {
        proxy_pass http://127.0.0.1:10000/health;
        proxy_set_header Host $host;
    }
}
EOF

# Активация сайта
ln -sf /etc/nginx/sites-available/dalazareva.ru /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo "=== [5/5] Выпуск бесплатного SSL-сертификата Let's Encrypt ==="
# Попытка выпустить SSL (если DNS уже обновились)
certbot --nginx -d dalazareva.ru -d www.dalazareva.ru --non-interactive --agree-tos --email variskasosisovna@gmail.com --redirect || {
    echo "Внимание: DNS-записи еще обновляются у провайдеров."
    echo "Когда DNS обновятся (через 10-15 минут), выполните команду:"
    echo "certbot --nginx -d dalazareva.ru -d www.dalazareva.ru --agree-tos --email variskasosisovna@gmail.com --redirect"
}

echo "=============================================================================="
echo "🎉 Готово! Проект успешно развернут на сервере!"
echo "Статус бота можно проверить командой: systemctl status dalazareva-bot"
echo "=============================================================================="
