#!/bin/bash
# ==============================================================================
# Скрипт развертывания Центра Управления ИИ-Агентами (AI Dev Hub)
# Домен: hub.dalazareva.ru
# ==============================================================================
set -e

echo "=== [1/5] Создание каталога и окружения AI Dev Hub ==="
HUB_DIR="/var/www/hub.dalazareva.ru"
mkdir -p "$HUB_DIR"
mkdir -p "$HUB_DIR/public"
mkdir -p "$HUB_DIR/backups"
mkdir -p "$HUB_DIR/logs"

# Проверка Python 3 и venv
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv git curl -qq

cd "$HUB_DIR"
if [ ! -d "venv" ]; then
    echo "Создание виртуального окружения Python..."
    python3 -m venv venv
fi

echo "Установка библиотек (FastAPI, Uvicorn, aiohttp)..."
./venv/bin/pip install --upgrade pip -q
./venv/bin/pip install fastapi uvicorn aiohttp python-dotenv -q

# 2. Создание файла конфигурации .env
if [ ! -f "$HUB_DIR/.env" ]; then
    cat << 'EOF' > "$HUB_DIR/.env"
# Порт сервиса
PORT=4000
# PIN-код для входа в веб-панель
ADMIN_PIN=2026
# Ключ Gemini API (если есть, вставьте сюда)
GEMINI_API_KEY=
EOF
fi

echo "=== [2/5] Создание бэкенда AI Dev Hub (Python / FastAPI) ==="
cat << 'EOF' > "$HUB_DIR/server.py"
import os
import sys
import json
import time
import shutil
import asyncio
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import aiohttp
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="AI Dev Hub", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ADMIN_PIN = os.getenv("ADMIN_PIN", "2026")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
PROJECTS_CONFIG_FILE = Path("/var/www/hub.dalazareva.ru/projects.json")
BACKUPS_DIR = Path("/var/www/hub.dalazareva.ru/backups")
BACKUPS_DIR.mkdir(parents=True, exist_ok=True)

# Исходный список известных проектов
DEFAULT_PROJECTS = [
    {
        "id": "map",
        "name": "Карта локаций",
        "badge": "React & Mapbox",
        "domain": "map.dalazareva.ru",
        "url": "https://map.dalazareva.ru",
        "path": "/var/www/map.dalazareva.ru",
        "service": "dalazareva-bot",
        "icon": "📍",
        "description": "Интерактивная карта Москвы, Supabase, бот и админка"
    },
    {
        "id": "game",
        "name": "3D Игра UNLIMITED // RUSH",
        "badge": "Three.js & Node",
        "domain": "game.dalazareva.ru",
        "url": "https://game.dalazareva.ru",
        "path": "/var/www/game.dalazareva.ru",
        "service": "dalazareva-rush",
        "icon": "🏎️",
        "description": "Игровой хаб, воксельная киберпанк-гонка и лидерборды"
    },
    {
        "id": "landing",
        "name": "Таплинк-Визитка",
        "badge": "HTML & CSS",
        "domain": "dalazareva.ru",
        "url": "https://dalazareva.ru",
        "path": "/var/www/dalazareva.ru",
        "service": "nginx",
        "icon": "🌸",
        "description": "Главная персональная страница Даши Лазаревой"
    }
]

def load_projects() -> List[Dict[str, Any]]:
    if not PROJECTS_CONFIG_FILE.exists():
        save_projects(DEFAULT_PROJECTS)
        return DEFAULT_PROJECTS
    try:
        with open(PROJECTS_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return DEFAULT_PROJECTS

def save_projects(projects: List[Dict[str, Any]]):
    with open(PROJECTS_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(projects, f, ensure_ascii=False, indent=2)

def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    token = authorization.replace("Bearer ", "").strip()
    if token != ADMIN_PIN:
        raise HTTPException(status_code=403, detail="Неверный PIN-код")
    return True

# --- МОДЕЛИ ДАННЫХ ---
class LoginRequest(BaseModel):
    pin: str

class FileEditRequest(BaseModel):
    path: str
    content: str
    backup: bool = True

class AgentChatRequest(BaseModel):
    project_id: str
    message: str
    agent_type: str = "coder" # coder | designer | devops | scout
    history: List[Dict[str, str]] = []

class AddProjectRequest(BaseModel):
    name: str
    path: str
    domain: Optional[str] = ""
    description: Optional[str] = ""
    icon: Optional[str] = "📁"

# --- ЭНДПОИНТЫ ---

@app.post("/api/auth/login")
def login(req: LoginRequest):
    if req.pin == ADMIN_PIN:
        return {"ok": True, "token": ADMIN_PIN}
    raise HTTPException(status_code=403, detail="Неверный PIN-код доступа")

@app.get("/api/projects")
def get_projects(auth: bool = Depends(verify_token)):
    projects = load_projects()
    for p in projects:
        p["exists"] = os.path.isdir(p.get("path", ""))
    return {"projects": projects}

@app.post("/api/projects")
def add_project(req: AddProjectRequest, auth: bool = Depends(verify_token)):
    projects = load_projects()
    p_id = req.name.lower().replace(" ", "-")[:16]
    new_p = {
        "id": p_id,
        "name": req.name,
        "badge": "Custom",
        "domain": req.domain,
        "url": f"https://{req.domain}" if req.domain else "",
        "path": req.path,
        "service": "",
        "icon": req.icon or "📁",
        "description": req.description
    }
    projects.append(new_p)
    save_projects(projects)
    return {"ok": True, "project": new_p}

@app.get("/api/projects/{project_id}/tree")
def get_project_tree(project_id: str, auth: bool = Depends(verify_token)):
    projects = load_projects()
    proj = next((p for p in projects if p["id"] == project_id), None)
    if not proj or not os.path.isdir(proj["path"]):
        raise HTTPException(status_code=404, detail="Проект не найден на диске")
    
    base = Path(proj["path"])
    ignore_dirs = {".git", "node_modules", "venv", "__pycache__", "dist", ".cache"}
    
    items = []
    try:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            rel_dir = os.path.relpath(root, base)
            for f in sorted(files):
                if f.endswith((".pyc", ".png", ".jpg", ".jpeg", ".ico", ".woff", ".woff2")):
                    continue
                rel_path = f if rel_dir == "." else os.path.join(rel_dir, f)
                full_p = os.path.join(root, f)
                try:
                    size = os.path.getsize(full_p)
                except Exception:
                    size = 0
                items.append({"path": rel_path, "size": size})
                if len(items) >= 150:
                    break
            if len(items) >= 150:
                break
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
        
    return {"files": items}

@app.get("/api/projects/{project_id}/file")
def read_project_file(project_id: str, path: str = Query(...), auth: bool = Depends(verify_token)):
    projects = load_projects()
    proj = next((p for p in projects if p["id"] == project_id), None)
    if not proj:
        raise HTTPException(status_code=404, detail="Проект не найден")
    
    file_path = (Path(proj["path"]) / path).resolve()
    if not str(file_path).startswith(str(Path(proj["path"]).resolve())):
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    if not file_path.exists() or file_path.is_dir():
        raise HTTPException(status_code=404, detail="Файл не найден")
        
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read(150000)
        return {"path": path, "content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/{project_id}/file")
def save_project_file(project_id: str, req: FileEditRequest, auth: bool = Depends(verify_token)):
    projects = load_projects()
    proj = next((p for p in projects if p["id"] == project_id), None)
    if not proj:
        raise HTTPException(status_code=404, detail="Проект не найден")
    
    file_path = (Path(proj["path"]) / req.path).resolve()
    if not str(file_path).startswith(str(Path(proj["path"]).resolve())):
        raise HTTPException(status_code=403, detail="Доступ запрещён")
        
    # Бэкап перед сохранением
    if req.backup and file_path.exists():
        ts = int(time.time())
        b_file = BACKUPS_DIR / f"{project_id}_{ts}_{Path(req.path).name}.bak"
        shutil.copy2(file_path, b_file)
        
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(req.content)
        
    return {"ok": True, "path": req.path}

@app.get("/api/system/status")
def get_system_status(auth: bool = Depends(verify_token)):
    services = ["nginx", "dalazareva-bot", "dalazareva-rush", "fail2ban"]
    status_map = {}
    for s in services:
        cmd = ["systemctl", "is-active", s]
        res = subprocess.run(cmd, capture_output=True, text=True)
        status_map[s] = res.stdout.strip() == "active"
        
    # Disk & Memory
    df_res = subprocess.run(["df", "-h", "/"], capture_output=True, text=True)
    df_line = df_res.stdout.split("\n")[1].split() if len(df_res.stdout.split("\n")) > 1 else []
    
    mem_res = subprocess.run(["free", "-m"], capture_output=True, text=True)
    mem_lines = mem_res.stdout.split("\n")
    mem_info = mem_lines[1].split() if len(mem_lines) > 1 else []
    
    return {
        "services": status_map,
        "disk": {
            "total": df_line[1] if len(df_line) > 1 else "?",
            "used": df_line[2] if len(df_line) > 2 else "?",
            "avail": df_line[3] if len(df_line) > 3 else "?",
            "percent": df_line[4] if len(df_line) > 4 else "?"
        },
        "memory": {
            "total_mb": mem_info[1] if len(mem_info) > 1 else "?",
            "used_mb": mem_info[2] if len(mem_info) > 2 else "?",
            "free_mb": mem_info[3] if len(mem_info) > 3 else "?"
        },
        "time": datetime.now().strftime("%H:%M:%S")
    }

@app.post("/api/system/restart/{service_name}")
def restart_service(service_name: str, auth: bool = Depends(verify_token)):
    allowed = {"nginx", "dalazareva-bot", "dalazareva-rush", "fail2ban"}
    if service_name not in allowed:
        raise HTTPException(status_code=400, detail="Недопустимое имя службы")
    subprocess.run(["systemctl", "restart", service_name])
    return {"ok": True, "service": service_name}

@app.post("/api/agent/chat")
async def agent_chat(req: AgentChatRequest, auth: bool = Depends(verify_token)):
    projects = load_projects()
    proj = next((p for p in projects if p["id"] == req.project_id), None)
    if not proj:
        raise HTTPException(status_code=404, detail="Проект не найден")
    
    # Собираем контекст проекта
    p_path = Path(proj["path"])
    file_list = []
    if p_path.exists():
        for r, dirs, files in os.walk(p_path):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "venv", "dist"}]
            for f in files:
                if f.endswith((".ts", ".tsx", ".js", ".html", ".css", ".py", ".json", ".sh")):
                    file_list.append(os.path.relpath(os.path.join(r, f), p_path))
                    if len(file_list) > 30:
                        break
            if len(file_list) > 30:
                break

    system_prompt = f"""Ты — автономный Senior AI Инженер-Разработчик и DevOps на сервере проектов dalazareva.ru.
Твоя цель: помогать владельцу развивать, чинить и изменять проекты прямо на сервере.
Текущий активный проект:
- Название: {proj['name']}
- Каталог на сервере: {proj['path']}
- Домен: {proj.get('domain', 'нет')}
- Системная служба: {proj.get('service', 'нет')}
- Ключевые файлы проекта: {', '.join(file_list[:20])}

Твоя роль ({req.agent_type}):
- Отвечай точно, профессионально, дружелюбно на русском языке.
- Если задача требует изменить код, укажи точное имя файла и покажи готовый обновленный блок кода или diff.
- Предложи пользователю команду или покажи, как ты готов это применить.
- Учитывай специфику (мобильный Safari, WebGL/Three.js, Telegram WebApp, Nginx).
"""

    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    
    if gemini_key:
        try:
            models = ["gemini-3.8-flash", "gemini-3.6-flash"]
            last_err = None
            for m in models:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={gemini_key}"
                payload = {
                    "contents": [
                        {"role": "user", "parts": [{"text": system_prompt + "\n\nПользователь: " + req.message}]}
                    ]
                }
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(url, json=payload, timeout=35) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                reply_text = data['candidates'][0]['content']['parts'][0]['text']
                                return {"reply": reply_text}
                            else:
                                err_text = await resp.text()
                                last_err = f"HTTP {resp.status}: {err_text[:200]}"
                except Exception as e:
                    last_err = str(e)
            
            if last_err:
                print(f"[Agent Gemini Error] {last_err}", file=sys.stderr)
        except Exception as e:
            print(f"[Agent Error] {e}", file=sys.stderr)

    # Интеллектуальный ответ по умолчанию (если ключ ещё не заполнен)
    reply_text = f"🤖 **Агент {req.agent_type.upper()} принял задачу для проекта «{proj['name']}»!**\n\n" \
                 f"Каталог проекта: `{proj['path']}`\n" \
                 f"Обнаружено файлов в проекте: {len(file_list)}\n\n" \
                 f"Запрос: *\"{req.message}\"*\n\n" \
                 f"💡 Для активации полноценной генерации кода через нейросеть Gemini, укажите `GEMINI_API_KEY` в файле `/var/www/hub.dalazareva.ru/.env` и перезапустите службу."
    return {"reply": reply_text, "files_detected": file_list[:8]}

# Статика фронтенда
app.mount("/", StaticFiles(directory="/var/www/hub.dalazareva.ru/public", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=4000)
EOF

echo "=== [3/5] Создание адаптивного веб-интерфейса AI Dev Hub ==="
cat << 'EOF' > "$HUB_DIR/public/index.html"
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>AI Studio Dev Hub — Управление проектами</title>
    
    <meta name="theme-color" content="#0a0d14">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="apple-mobile-web-app-title" content="AI Dev Hub">
    
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;600&family=Unbounded:wght@600;700;800&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    fontFamily: {
                        sans: ['"Plus Jakarta Sans"', 'sans-serif'],
                        mono: ['"JetBrains Mono"', 'monospace'],
                        display: ['Unbounded', 'sans-serif']
                    },
                    colors: {
                        hub: {
                            bg: '#080a0f',
                            card: '#10141d',
                            border: 'rgba(255,255,255,0.08)',
                            cyan: '#00f2fe',
                            rose: '#f43f5e',
                            purple: '#a855f7'
                        }
                    }
                }
            }
        }
    </script>
    <style>
        * { -webkit-tap-highlight-color: transparent; }
        body { background-color: #080a0f; color: #f1f5f9; min-height: 100dvh; }
        .glass { background: rgba(16, 20, 29, 0.8); backdrop-filter: blur(16px); border: 1px solid rgba(255,255,255,0.07); }
        .custom-scroll::-webkit-scrollbar { width: 4px; height: 4px; }
        .custom-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); border-radius: 4px; }
    </style>
</head>
<body class="flex flex-col h-screen overflow-hidden text-sm">

    <!-- LOGIN OVERLAY -->
    <div id="loginModal" class="fixed inset-0 z-50 bg-[#080a0f]/95 backdrop-blur-xl flex items-center justify-center p-4">
        <div class="glass max-w-sm w-full p-8 rounded-3xl text-center shadow-2xl">
            <div class="w-16 h-16 mx-auto mb-4 rounded-2xl bg-gradient-to-tr from-cyan-500 to-indigo-500 flex items-center justify-center text-3xl shadow-lg shadow-cyan-500/20">⚡</div>
            <h1 class="font-display font-bold text-xl mb-1 text-white">AI Dev Hub</h1>
            <p class="text-xs text-slate-400 mb-6">Вход в студию управления проектами</p>
            <form onsubmit="handleLogin(event)" class="space-y-4">
                <input type="password" id="pinInput" placeholder="Введите PIN-код" autofocus
                    class="w-full text-center tracking-widest text-lg px-4 py-3 rounded-xl bg-slate-900/80 border border-slate-700 text-white focus:outline-none focus:border-cyan-400 transition" />
                <button type="submit" class="w-full py-3.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 font-bold text-slate-950 hover:brightness-110 active:scale-[0.98] transition">
                    Войти в систему
                </button>
            </form>
            <div class="mt-4 text-[11px] text-slate-500">По умолчанию PIN: 2026</div>
        </div>
    </div>

    <!-- TOP HEADER -->
    <header class="h-14 border-b border-white/5 glass flex items-center justify-between px-4 sm:px-6 shrink-0 z-20">
        <div class="flex items-center gap-3">
            <div class="w-8 h-8 rounded-xl bg-gradient-to-tr from-cyan-400 to-blue-600 flex items-center justify-center font-bold text-slate-950">⚡</div>
            <div>
                <span class="font-display font-bold text-sm text-white tracking-wide">AI DEV HUB</span>
                <span class="hidden sm:inline-block ml-2 text-[11px] px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">Multi-Project</span>
            </div>
        </div>

        <!-- ACTIVE PROJECT BADGE -->
        <div class="flex items-center gap-2">
            <div class="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-slate-900 border border-white/10 text-xs cursor-pointer hover:border-cyan-500/40 transition" onclick="toggleProjectDrawer()">
                <span id="headerProjectIcon">📍</span>
                <span id="headerProjectName" class="font-semibold text-white">Карта локаций</span>
                <span class="text-slate-500 text-[10px]">▼</span>
            </div>
            <button onclick="checkHealth()" class="p-2 rounded-xl bg-slate-900 border border-white/10 text-slate-400 hover:text-white" title="Проверить сервисы">🔄</button>
        </div>
    </header>

    <!-- MAIN WORKSPACE -->
    <div class="flex-1 flex overflow-hidden">
        
        <!-- SIDEBAR: PROJECTS LIST (DESKTOP) -->
        <aside id="sidebarProjects" class="hidden md:flex flex-col w-72 border-r border-white/5 glass p-3 gap-2 shrink-0">
            <div class="text-[11px] font-bold uppercase tracking-wider text-slate-500 px-3 py-1">Ваши проекты</div>
            <div id="projectsList" class="flex-1 space-y-1.5 overflow-y-auto custom-scroll">
                <!-- Заполняется динамически -->
            </div>
            
            <!-- SYSTEM STATS MINI -->
            <div class="p-3 rounded-2xl bg-slate-900/60 border border-white/5 space-y-2 text-[11px]">
                <div class="flex justify-between items-center text-slate-400">
                    <span>Диск</span>
                    <span id="statDisk" class="text-white font-mono">-</span>
                </div>
                <div class="flex justify-between items-center text-slate-400">
                    <span>Память</span>
                    <span id="statMem" class="text-white font-mono">-</span>
                </div>
                <div class="flex gap-1.5 pt-1 border-t border-white/5">
                    <span id="dotNginx" class="w-2 h-2 rounded-full bg-emerald-400 inline-block" title="Nginx"></span>
                    <span id="dotBot" class="w-2 h-2 rounded-full bg-emerald-400 inline-block" title="Bot"></span>
                    <span id="dotRush" class="w-2 h-2 rounded-full bg-emerald-400 inline-block" title="Rush Game"></span>
                    <span class="text-[10px] text-slate-500 ml-auto">Службы 24/7</span>
                </div>
            </div>
        </aside>

        <!-- CENTER: CHAT & AGENT WORKSPACE -->
        <main class="flex-1 flex flex-col bg-[#090c12] relative overflow-hidden">
            
            <!-- SUB-HEADER: AGENT TYPE TABS -->
            <div class="h-11 border-b border-white/5 px-4 flex items-center justify-between gap-2 shrink-0 bg-slate-950/40">
                <div class="flex gap-1 overflow-x-auto custom-scroll py-1">
                    <button onclick="setAgent('coder')" id="tabCoder" class="px-3 py-1 rounded-lg text-xs font-semibold bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">🛠️ Программист</button>
                    <button onclick="setAgent('designer')" id="tabDesigner" class="px-3 py-1 rounded-lg text-xs font-semibold text-slate-400 hover:text-white">🎨 UX / UI</button>
                    <button onclick="setAgent('devops')" id="tabDevops" class="px-3 py-1 rounded-lg text-xs font-semibold text-slate-400 hover:text-white">🚀 DevOps & Nginx</button>
                    <button onclick="openFilesModal()" class="px-3 py-1 rounded-lg text-xs font-semibold text-slate-400 hover:text-white">📂 Файлы</button>
                </div>
                <a id="projectExternalLink" href="https://map.dalazareva.ru" target="_blank" class="text-xs text-cyan-400 hover:underline flex items-center gap-1">
                    <span>Открыть сайт</span> ↗
                </a>
            </div>

            <!-- CHAT MESSAGES STREAM -->
            <div id="chatStream" class="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4 custom-scroll">
                <!-- Приветственное сообщение -->
                <div class="flex gap-3 max-w-2xl">
                    <div class="w-8 h-8 rounded-xl bg-gradient-to-tr from-cyan-400 to-indigo-500 flex items-center justify-center shrink-0 text-slate-950 font-bold">AI</div>
                    <div class="glass p-4 rounded-2xl text-slate-200 text-sm leading-relaxed">
                        Привет! Я ваш центральный ИИ-агент на сервере. Я подключён к проектам:
                        <ul class="list-disc list-inside mt-2 space-y-1 text-slate-300 text-xs">
                            <li><strong class="text-white">Карта</strong> (map.dalazareva.ru)</li>
                            <li><strong class="text-white">3D Гонка / Хаб</strong> (game.dalazareva.ru)</li>
                            <li><strong class="text-white">Таплинк</strong> (dalazareva.ru)</li>
                        </ul>
                        <div class="mt-3 text-slate-400 text-xs">Напишите мне задачу текстом или кодом — я изучу файлы проекта на диске, предложу правки и применю их на сервере!</div>
                    </div>
                </div>
            </div>

            <!-- INPUT BOX -->
            <div class="p-3 sm:p-4 border-t border-white/5 glass shrink-0">
                <form onsubmit="sendMessage(event)" class="max-w-4xl mx-auto flex gap-2">
                    <input type="text" id="promptInput" placeholder="Напишите задачу (например: «Ускорь машинку в игре» или «Проверь статус бота»)..."
                        class="flex-1 px-4 py-3 rounded-xl bg-slate-900/90 border border-white/10 text-white placeholder-slate-500 focus:outline-none focus:border-cyan-400 text-sm transition" />
                    <button type="submit" id="sendBtn" class="px-5 py-3 rounded-xl bg-gradient-to-r from-cyan-400 to-blue-500 font-bold text-slate-950 hover:brightness-110 active:scale-[0.98] transition shrink-0 flex items-center gap-1.5">
                        <span>Отправить</span> ➔
                    </button>
                </form>
            </div>
        </main>
    </div>

    <!-- FILES EXPLORER MODAL -->
    <div id="filesModal" class="hidden fixed inset-0 z-40 bg-black/80 backdrop-blur-md flex items-center justify-center p-4">
        <div class="glass max-w-2xl w-full max-h-[80vh] flex flex-col rounded-3xl overflow-hidden">
            <div class="p-4 border-b border-white/10 flex justify-between items-center">
                <h3 class="font-bold text-white flex items-center gap-2">📂 Файлы текущего проекта</h3>
                <button onclick="closeFilesModal()" class="text-slate-400 hover:text-white text-lg">✕</button>
            </div>
            <div id="filesTreeList" class="flex-1 overflow-y-auto p-4 space-y-1 font-mono text-xs custom-scroll">
                <!-- Файлы проекта -->
            </div>
        </div>
    </div>

    <script>
        let currentProject = 'map';
        let currentAgent = 'coder';
        let authToken = localStorage.getItem('hub_token') || '';
        let projects = [];

        window.addEventListener('DOMContentLoaded', () => {
            if (authToken) {
                document.getElementById('loginModal').classList.add('hidden');
                init();
            }
        });

        async function handleLogin(e) {
            e.preventDefault();
            const pin = document.getElementById('pinInput').value.trim();
            try {
                const res = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({pin})
                });
                const data = await res.json();
                if (data.ok) {
                    authToken = data.token;
                    localStorage.setItem('hub_token', authToken);
                    document.getElementById('loginModal').classList.add('hidden');
                    init();
                } else {
                    alert('Неверный PIN!');
                }
            } catch (err) {
                alert('Ошибка соединения с сервером');
            }
        }

        async function init() {
            await loadProjects();
            await checkHealth();
        }

        async function loadProjects() {
            try {
                const res = await fetch('/api/projects', {
                    headers: {'Authorization': 'Bearer ' + authToken}
                });
                const data = await res.json();
                projects = data.projects || [];
                renderProjects();
            } catch (e) {
                console.error(e);
            }
        }

        function renderProjects() {
            const container = document.getElementById('projectsList');
            container.innerHTML = '';
            projects.forEach(p => {
                const active = p.id === currentProject;
                const card = document.createElement('div');
                card.className = `p-3 rounded-2xl cursor-pointer transition flex items-center gap-3 ${active ? 'bg-cyan-500/15 border border-cyan-500/30' : 'bg-slate-900/40 hover:bg-slate-800/50 border border-white/5'}`;
                card.onclick = () => selectProject(p.id);
                card.innerHTML = `
                    <span class="text-xl">${p.icon}</span>
                    <div class="flex-1 min-w-0">
                        <div class="font-bold text-xs text-white truncate">${p.name}</div>
                        <div class="text-[10px] text-slate-400 truncate">${p.domain || p.path}</div>
                    </div>
                `;
                container.appendChild(card);
            });
            updateHeader();
        }

        function selectProject(id) {
            currentProject = id;
            renderProjects();
            appendMessage('system', `🔄 Активный проект переключён на: **${projects.find(p=>p.id===id)?.name}**`);
        }

        function updateHeader() {
            const p = projects.find(x => x.id === currentProject);
            if (p) {
                document.getElementById('headerProjectIcon').innerText = p.icon;
                document.getElementById('headerProjectName').innerText = p.name;
                document.getElementById('projectExternalLink').href = p.url || '#';
            }
        }

        function setAgent(type) {
            currentAgent = type;
            ['coder', 'designer', 'devops'].forEach(t => {
                const el = document.getElementById('tab' + t.charAt(0).toUpperCase() + t.slice(1));
                if (t === type) {
                    el.className = 'px-3 py-1 rounded-lg text-xs font-semibold bg-cyan-500/15 text-cyan-300 border border-cyan-500/30';
                } else {
                    el.className = 'px-3 py-1 rounded-lg text-xs font-semibold text-slate-400 hover:text-white';
                }
            });
        }

        async function checkHealth() {
            try {
                const res = await fetch('/api/system/status', {
                    headers: {'Authorization': 'Bearer ' + authToken}
                });
                const data = await res.json();
                document.getElementById('statDisk').innerText = `${data.disk.used}/${data.disk.total}`;
                document.getElementById('statMem').innerText = `${data.memory.used_mb}MB`;
                document.getElementById('dotNginx').className = `w-2 h-2 rounded-full ${data.services.nginx ? 'bg-emerald-400' : 'bg-rose-500'}`;
                document.getElementById('dotBot').className = `w-2 h-2 rounded-full ${data.services['dalazareva-bot'] ? 'bg-emerald-400' : 'bg-rose-500'}`;
                document.getElementById('dotRush').className = `w-2 h-2 rounded-full ${data.services['dalazareva-rush'] ? 'bg-emerald-400' : 'bg-rose-500'}`;
            } catch (e) {
                console.error(e);
            }
        }

        async function sendMessage(e) {
            e.preventDefault();
            const input = document.getElementById('promptInput');
            const msg = input.value.trim();
            if (!msg) return;
            
            appendMessage('user', msg);
            input.value = '';
            
            const btn = document.getElementById('sendBtn');
            btn.disabled = true;
            btn.innerText = 'Анализ...';

            try {
                const res = await fetch('/api/agent/chat', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': 'Bearer ' + authToken
                    },
                    body: JSON.stringify({
                        project_id: currentProject,
                        message: msg,
                        agent_type: currentAgent
                    })
                });
                const data = await res.json();
                appendMessage('ai', data.reply);
            } catch (err) {
                appendMessage('system', '❌ Ошибка ответа агента. Проверьте соединение.');
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<span>Отправить</span> ➔';
            }
        }

        function appendMessage(role, text) {
            const stream = document.getElementById('chatStream');
            const row = document.createElement('div');
            row.className = 'flex gap-3 max-w-2xl ' + (role === 'user' ? 'ml-auto justify-end' : '');
            
            let icon = role === 'user' ? '👤' : (role === 'system' ? '⚙️' : 'AI');
            let bg = role === 'user' ? 'bg-gradient-to-r from-cyan-600 to-blue-600 text-white' : 'glass text-slate-200';
            
            row.innerHTML = `
                ${role !== 'user' ? `<div class="w-8 h-8 rounded-xl bg-gradient-to-tr from-cyan-400 to-indigo-500 flex items-center justify-center shrink-0 text-slate-950 font-bold text-xs">${icon}</div>` : ''}
                <div class="${bg} p-4 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap">${text}</div>
                ${role === 'user' ? `<div class="w-8 h-8 rounded-xl bg-slate-700 flex items-center justify-center shrink-0 text-white text-xs">${icon}</div>` : ''}
            `;
            stream.appendChild(row);
            stream.scrollTop = stream.scrollHeight;
        }

        async function openFilesModal() {
            const modal = document.getElementById('filesModal');
            const list = document.getElementById('filesTreeList');
            list.innerHTML = 'Загрузка списка файлов...';
            modal.classList.remove('hidden');

            try {
                const res = await fetch(`/api/projects/${currentProject}/tree`, {
                    headers: {'Authorization': 'Bearer ' + authToken}
                });
                const data = await res.json();
                list.innerHTML = '';
                data.files.forEach(f => {
                    const item = document.createElement('div');
                    item.className = 'p-2 rounded hover:bg-white/5 flex justify-between items-center cursor-pointer';
                    item.innerHTML = `<span>📄 ${f.path}</span> <span class="text-slate-500">${(f.size/1024).toFixed(1)} KB</span>`;
                    list.appendChild(item);
                });
            } catch (e) {
                list.innerText = 'Не удалось загрузить файлы';
            }
        }

        function closeFilesModal() {
            document.getElementById('filesModal').classList.add('hidden');
        }
    </script>
</body>
</html>
EOF

echo "=== [4/5] Настройка системной службы systemd для AI Hub ==="
cat << 'EOF' > /etc/systemd/system/dalazareva-hub.service
[Unit]
Description=AI Studio Multi-Project Dev Hub
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/var/www/hub.dalazareva.ru
ExecStart=/var/www/hub.dalazareva.ru/venv/bin/python3 -m uvicorn server:app --host 127.0.0.1 --port 4000
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now dalazareva-hub.service
systemctl restart dalazareva-hub.service

echo "=== [5/5] Настройка Nginx для поддомена hub.dalazareva.ru ==="
cat << 'EOF' > /etc/nginx/sites-available/hub.dalazareva.ru
server {
    listen 80;
    listen [::]:80;
    server_name hub.dalazareva.ru;

    # Проксирование API в бэкенд на порту 4000
    location /api/ {
        proxy_pass http://127.0.0.1:4000/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Фронтенд панели
    location / {
        proxy_pass http://127.0.0.1:4000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
    }
}
EOF

ln -sf /etc/nginx/sites-available/hub.dalazareva.ru /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx

# Выпуск SSL
certbot --nginx -d hub.dalazareva.ru --non-interactive --agree-tos --email variskasosisovna@gmail.com --redirect || {
    echo "Внимание: если DNS для hub.dalazareva.ru ещё не добавлен, сертификат выпустится позже командой:"
    echo "certbot --nginx -d hub.dalazareva.ru --agree-tos --email variskasosisovna@gmail.com --redirect"
}

echo "=============================================================================="
echo "🎉 Центр управления проектами AI Dev Hub развернут!"
echo "Адрес панели: https://hub.dalazareva.ru (или http://IP:4000)"
echo "PIN-код для первого входа: 2026"
echo "=============================================================================="
