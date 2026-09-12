#!/bin/bash
# ==============================================================================
# Скрипт развертывания Игрового Хаба и 3D-игры UNLIMITED // RUSH
# Домен: game.dalazareva.ru
# ==============================================================================
set -e

echo "=== [1/5] Установка файлового менеджера для Cockpit ==="
curl -sSL https://github.com/45Drives/cockpit-navigator/releases/download/v0.5.10/cockpit-navigator_0.5.10-1focal_all.deb -o /tmp/cockpit-navigator.deb || true
if [ -f /tmp/cockpit-navigator.deb ]; then
    apt-get install -y /tmp/cockpit-navigator.deb || apt-get install -f -y
    rm -f /tmp/cockpit-navigator.deb
fi

echo "=== [2/5] Проверка Node.js и npm ==="
if ! command -v node &> /dev/null; then
    echo "Установка Node.js 20..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
fi
echo "Node.js: $(node -v), npm: $(npm -v)"

echo "=== [3/5] Скачивание и сборка UNLIMITED // RUSH из GitHub ==="
RUSH_DIR="/var/www/game.dalazareva.ru/backend"
mkdir -p /var/www/game.dalazareva.ru
rm -rf "$RUSH_DIR"

# Клонируем репозиторий гонки
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
if [ -n "$GITHUB_TOKEN" ]; then
    git clone "https://${GITHUB_TOKEN}@github.com/MicchHF/-yber-no-limited-rush.git" "$RUSH_DIR"
else
    git clone "https://github.com/MicchHF/-yber-no-limited-rush.git" "$RUSH_DIR" || true
fi

cd "$RUSH_DIR"
git config --global credential.helper store
npm install --ignore-scripts

# Сборка фронтенда и бэкенда игры
echo "Компиляция фронтенда UNLIMITED // RUSH..."
npx vite build

# Сборка бэкенда для лидербордов и облачных сохранений
echo "Компиляция бэкенда Node.js..."
npx esbuild server.ts --bundle --platform=node --format=cjs --packages=external --sourcemap --outfile=dist/server.cjs

# Публикуем скомпилированные файлы игры в /var/www/game.dalazareva.ru/rush/
rm -rf /var/www/game.dalazareva.ru/rush
mkdir -p /var/www/game.dalazareva.ru/rush
cp -r dist/* /var/www/game.dalazareva.ru/rush/

# Создаем папку для базы данных рекордов и сохранений
mkdir -p "$RUSH_DIR/data"
chown -R www-data:www-data "$RUSH_DIR"
chown -R www-data:www-data /var/www/game.dalazareva.ru

echo "=== [4/5] Настройка системной службы для лидербордов игры ==="
cat << 'EOF' > /etc/systemd/system/dalazareva-rush.service
[Unit]
Description=UNLIMITED // RUSH Game Leaderboards & API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/var/www/game.dalazareva.ru/backend
ExecStart=/usr/bin/node /var/www/game.dalazareva.ru/backend/dist/server.cjs
Restart=always
RestartSec=3
Environment=NODE_ENV=production
Environment=PORT=3000

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now dalazareva-rush.service
systemctl restart dalazareva-rush.service

echo "=== [5/5] Создание страницы Игрового Хаба (Главное меню) ==="
cat << 'EOF' > /var/www/game.dalazareva.ru/index.html
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>Игровой Хаб — dalazareva.ru</title>
    <meta name="description" content="Коллекция 3D и веб-игр для смартфонов и ПК. Без загрузок из App Store — сразу в браузере или на экран «Домой» с 60+ FPS.">
    <meta name="theme-color" content="#0d0f12">
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Unbounded:wght@600;700;800;900&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #090a0f;
            --card-bg: rgba(18, 21, 28, 0.75);
            --card-border: rgba(255, 255, 255, 0.09);
            --cyan: #00f2fe;
            --purple: #7928ca;
            --orange: #ff4757;
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            -webkit-tap-highlight-color: transparent;
        }

        body {
            background-color: var(--bg);
            background-image: 
                radial-gradient(circle at 10% 10%, rgba(0, 242, 254, 0.07) 0%, transparent 45%),
                radial-gradient(circle at 90% 90%, rgba(121, 40, 202, 0.08) 0%, transparent 45%),
                linear-gradient(180deg, #090a0f 0%, #0d1117 100%);
            color: var(--text-main);
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            padding: 24px 16px 40px;
        }

        .container {
            max-width: 960px;
            margin: 0 auto;
            width: 100%;
        }

        /* HEADER */
        header {
            text-align: center;
            margin-bottom: 30px;
            padding-top: 10px;
        }

        .top-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 6px 14px;
            border-radius: 999px;
            background: rgba(0, 242, 254, 0.08);
            border: 1px solid rgba(0, 242, 254, 0.25);
            color: var(--cyan);
            font-family: 'JetBrains Mono', monospace;
            font-size: 11px;
            letter-spacing: 1px;
            margin-bottom: 16px;
            text-transform: uppercase;
        }

        .pulse-dot {
            width: 7px;
            height: 7px;
            background: var(--cyan);
            border-radius: 50%;
            box-shadow: 0 0 8px var(--cyan);
            animation: pulse 1.8s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.3; transform: scale(0.8); }
        }

        h1 {
            font-family: 'Unbounded', sans-serif;
            font-weight: 900;
            font-size: clamp(28px, 6vw, 44px);
            letter-spacing: -1px;
            background: linear-gradient(135deg, #ffffff 40%, #00f2fe 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 12px;
        }

        .subtitle {
            color: var(--text-muted);
            font-size: 15px;
            max-width: 520px;
            margin: 0 auto 20px;
            line-height: 1.5;
        }

        /* TIP BANNER */
        .tip-banner {
            background: rgba(30, 41, 59, 0.5);
            border: 1px solid rgba(255, 255, 255, 0.08);
            backdrop-filter: blur(12px);
            border-radius: 16px;
            padding: 14px 18px;
            margin-bottom: 32px;
            display: flex;
            align-items: center;
            gap: 14px;
            font-size: 13.5px;
            color: #cbd5e1;
        }

        .tip-icon {
            font-size: 26px;
            flex-shrink: 0;
        }

        .tip-banner strong {
            color: #fff;
        }

        /* GRID */
        .games-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 24px;
            margin-bottom: 40px;
        }

        /* GAME CARD */
        .game-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 22px;
            overflow: hidden;
            backdrop-filter: blur(16px);
            transition: all 0.3s cubic-bezier(0.2, 0.8, 0.2, 1);
            display: flex;
            flex-direction: column;
            position: relative;
        }

        .game-card:hover {
            transform: translateY(-5px);
            border-color: rgba(0, 242, 254, 0.4);
            box-shadow: 0 16px 40px -12px rgba(0, 242, 254, 0.25);
        }

        .game-cover {
            height: 190px;
            background: linear-gradient(135deg, #091224 0%, #170b28 100%);
            position: relative;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }

        .cover-grid {
            position: absolute;
            inset: 0;
            background-image: 
                linear-gradient(rgba(0, 242, 254, 0.12) 1px, transparent 1px),
                linear-gradient(90deg, rgba(0, 242, 254, 0.12) 1px, transparent 1px);
            background-size: 24px 24px;
            perspective: 300px;
            transform: rotateX(50deg) scale(1.6);
            transform-origin: center bottom;
        }

        .hero-title {
            position: relative;
            font-family: 'Unbounded', sans-serif;
            font-size: 32px;
            font-weight: 900;
            letter-spacing: -0.5px;
            background: linear-gradient(135deg, #fff 20%, #00f2fe 80%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-shadow: 0 0 30px rgba(0, 242, 254, 0.4);
            z-index: 2;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .card-badge {
            position: absolute;
            top: 14px;
            right: 14px;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(8px);
            border: 1px solid rgba(0, 242, 254, 0.4);
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 700;
            color: #00f2fe;
            z-index: 3;
            display: flex;
            align-items: center;
            gap: 5px;
        }

        .game-body {
            padding: 22px;
            display: flex;
            flex-direction: column;
            flex: 1;
        }

        .game-title {
            font-family: 'Unbounded', sans-serif;
            font-size: 20px;
            font-weight: 800;
            color: #fff;
            margin-bottom: 8px;
        }

        .game-desc {
            color: var(--text-muted);
            font-size: 14px;
            line-height: 1.55;
            margin-bottom: 20px;
            flex: 1;
        }

        .game-pills {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
            margin-bottom: 22px;
        }

        .pill {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            padding: 4px 10px;
            font-size: 11.5px;
            color: #cbd5e1;
        }

        .btn-play-rush {
            background: linear-gradient(135deg, #00f2fe 0%, #4facfe 100%);
            color: #080c14;
            text-decoration: none;
            text-align: center;
            padding: 15px 22px;
            border-radius: 14px;
            font-family: 'Unbounded', sans-serif;
            font-size: 14px;
            font-weight: 800;
            letter-spacing: 0.5px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            box-shadow: 0 4px 16px rgba(0, 242, 254, 0.35);
            transition: all 0.2s ease;
        }

        .btn-play-rush:hover {
            box-shadow: 0 6px 24px rgba(0, 242, 254, 0.6);
            transform: translateY(-2px);
        }

        .btn-play-rush:active {
            transform: translateY(1px);
        }

        /* COMING SOON CARD */
        .card-soon {
            opacity: 0.65;
            border-style: dashed;
        }

        .card-soon:hover {
            opacity: 0.9;
            box-shadow: none;
            border-color: rgba(255, 255, 255, 0.25);
        }

        .btn-soon {
            background: rgba(255, 255, 255, 0.05);
            color: #64748b;
            border: 1px solid rgba(255, 255, 255, 0.08);
            cursor: not-allowed;
            padding: 15px;
            border-radius: 14px;
            font-family: 'Unbounded', sans-serif;
            font-size: 13px;
            font-weight: 700;
            text-align: center;
        }

        footer {
            margin-top: auto;
            text-align: center;
            color: var(--text-muted);
            font-size: 13px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            align-items: center;
        }

        footer a {
            color: #cbd5e1;
            text-decoration: none;
            transition: color 0.2s;
        }

        footer a:hover {
            color: var(--cyan);
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="top-badge">
                <span class="pulse-dot"></span>
                Web Arcade • 60–120 FPS
            </div>
            <h1>Игровой Хаб</h1>
            <p class="subtitle">Каталог мобильных 3D-игр без установки из App Store и Google Play. Нажмите на игру, чтобы запустить на полный экран!</p>
        </header>

        <div class="tip-banner">
            <span class="tip-icon">📱</span>
            <div>
                <strong>Как играть во весь экран без лагов браузера:</strong><br>
                На iPhone (Safari): нажмите <em>«Поделиться»</em> ➔ <em>«На экран „Домой“»</em>.<br>
                На Android (Chrome): выберите в меню <em>«Установить приложение»</em>.
            </div>
        </div>

        <div class="games-grid">
            <!-- GAME 1: UNLIMITED // RUSH -->
            <div class="game-card">
                <div class="game-cover">
                    <div class="cover-grid"></div>
                    <div class="hero-title">🏎️ RUSH</div>
                    <div class="card-badge">● 60 FPS • 3D</div>
                </div>
                <div class="game-body">
                    <h2 class="game-title">UNLIMITED // RUSH</h2>
                    <p class="game-desc">Киберпанк воксельная гонка в стиле TRON на изгибающейся 360° магнитной трассе. Без тормозов, максимальная скорость, битвы с боссами и глобальный лидерборд.</p>
                    <div class="game-pills">
                        <span class="pill">⚡ 3D Three.js</span>
                        <span class="pill">🏆 Лидерборды</span>
                        <span class="pill">🎮 Сенсорный руль</span>
                        <span class="pill">👾 Битвы с боссами</span>
                    </div>
                    <a href="/rush/" class="btn-play-rush">
                        <span>▶</span>
                        ИГРАТЬ В UNLIMITED // RUSH
                    </a>
                </div>
            </div>

            <!-- GAME 2: COMING SOON -->
            <div class="game-card card-soon">
                <div class="game-cover" style="background: linear-gradient(135deg, #0c1017 0%, #151922 100%);">
                    <div class="cover-grid" style="opacity: 0.05;"></div>
                    <div class="hero-title" style="color: #475569; -webkit-text-fill-color: #475569;">👾 GAME #2</div>
                    <div class="card-badge" style="border-color: rgba(255,255,255,0.1); color: #94a3b8;">В разработке</div>
                </div>
                <div class="game-body">
                    <h2 class="game-title">Новая игра</h2>
                    <p class="game-desc">Следующая игра появится прямо здесь в этом меню. Вы сможете запускать её в один клик с этого же домена.</p>
                    <div class="game-pills">
                        <span class="pill">⏳ Скоро</span>
                        <span class="pill">🎮 Arcade</span>
                    </div>
                    <div class="btn-soon">
                        СКОРО В ЭФИРЕ
                    </div>
                </div>
            </div>
        </div>

        <footer>
            <div>Проект команды <a href="https://dalazareva.ru">dalazareva.ru</a></div>
        </footer>
    </div>
</body>
</html>
EOF

echo "=== [6/6] Обновление конфигурации Nginx ==="
cat << 'EOF' > /etc/nginx/sites-available/game.dalazareva.ru
server {
    listen 80;
    listen [::]:80;
    server_name game.dalazareva.ru;

    root /var/www/game.dalazareva.ru;
    index index.html;

    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/svg+xml application/manifest+json;

    # Главная страница (Игровой Хаб / Меню игр)
    location / {
        try_files $uri $uri/ /index.html;
        add_header Cache-Control "no-cache";
    }

    # Иконки для iOS Safari (Safari запрашивает их с корня домена при добавлении на экран «Домой»)
    location = /apple-touch-icon.png {
        alias /var/www/game.dalazareva.ru/rush/apple-touch-icon.png;
    }
    location = /apple-touch-icon-precomposed.png {
        alias /var/www/game.dalazareva.ru/rush/apple-touch-icon.png;
    }
    location = /favicon.ico {
        alias /var/www/game.dalazareva.ru/rush/favicon.ico;
    }

    # Поддержка MIME-типа для манифеста PWA на iOS/Android
    location ~* \.webmanifest$ {
        default_type application/manifest+json;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        expires 0;
    }

    # Service Worker и регистратор — строгий no-cache для мгновенного обновления на смартфонах
    location ~* (sw\.js|registerSW\.js)$ {
        default_type application/javascript;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header Pragma "no-cache";
        expires 0;
    }

    # Редирект /rush на /rush/ для корректной работы PWA и относительных путей на iPhone
    location = /rush {
        return 301 /rush/;
    }

    # Сама 3D-игра UNLIMITED // RUSH
    location /rush/ {
        try_files $uri $uri/ /rush/index.html;
    }

    # API игры (Лидерборды, Облачные сохранения, Гонщики-призраки)
    location /api/ {
        proxy_pass http://127.0.0.1:3000/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_cache_bypass $http_upgrade;
    }

    location /rush/api/ {
        proxy_pass http://127.0.0.1:3000/rush/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_cache_bypass $http_upgrade;
    }

    # Кэширование ассетов и моделей 3D
    location ~* \.(jpg|jpeg|png|gif|ico|css|js|svg|webp|woff|woff2|mp3|ogg|wav)$ {
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }
}
EOF

nginx -t
systemctl reload nginx

# Выпуск SSL для game.dalazareva.ru если ещё не выпущен
certbot --nginx -d game.dalazareva.ru --non-interactive --agree-tos --email variskasosisovna@gmail.com --redirect || true

echo "=============================================================================="
echo "🎉 Готово! Игровой Хаб и игра UNLIMITED // RUSH успешно запущены!"
echo "Витрина игр: https://game.dalazareva.ru"
echo "Игра напрямую: https://game.dalazareva.ru/rush/"
echo "Файловый менеджер в Cockpit: вкладка «Navigator»"
echo "=============================================================================="
