#!/bin/bash

# ============================================
# Отключение спящего режима и энергосбережения
# ============================================

# Отключить сон системы (только если есть права root)
if [ "$(id -u)" -eq 0 ]; then
    # systemd-based systems
    if command -v systemctl &>/dev/null; then
        systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null
    fi

    # laptop-mode-tools
    if command -v pm-set-attributes &>/dev/null; then
        pm-set-attributes sleep off 2>/dev/null
    fi

    # TLP
    if command -v tlp &>/dev/null; then
        tlp setcharge 100 2>/dev/null
    fi
fi

# Отключить энергосбережение дисплея (X11)
if command -v xset &>/dev/null && [ -n "$DISPLAY" ]; then
    xset s off 2>/dev/null || true        # отключить экранную заставку
    xset -dpms 2>/dev/null || true        # отключить DPMS (выключение дисплея)
    xset s noblank 2>/dev/null || true    # отключить бланкирование экрана
fi

# Отключить автосон в GNOME (только если есть права root для dbus)
if command -v gsettings &>/dev/null && [ -n "$DBUS_SESSION_BUS_ADDRESS" ]; then
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing' 2>/dev/null
    gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-bc-type 'nothing' 2>/dev/null
    gsettings set org.gnome.desktop.session idle-delay 0 2>/dev/null
fi

# ============================================
# Предотвращение ухода в сон через inotify
# ============================================
prevent_sleep() {
    while true; do
        # Отправляем «нажатие» на пустой файл (предотвращает idle sleep)
        if command -v xdotool &>/dev/null && [ -n "$DISPLAY" ]; then
            xdotool key alt+F4 2>/dev/null &  # имитация активности раз в 5 минут
        fi
        sleep 300  # каждые 5 минут
    done
}

# Запуск prevent_sleep в фоне (только если есть DISPLAY)
if [ -n "$DISPLAY" ] && command -v xdotool &>/dev/null; then
    prevent_sleep &
    PREVENT_SLEEP_PID=$!
    echo "⏰ Предотвращение сна активно (PID: $PREVENT_SLEEP_PID)"
fi

# ============================================
# Функция остановки всех процессов бота и веб-панели
# ============================================
kill_all() {
    echo "Остановка всех процессов бота и веб-панели..."
    
    # Убить все процессы бота через порт
    PORT=8001
    PID=$(lsof -t -i:$PORT 2>/dev/null)
    if [ -n "$PID" ]; then
        echo "Убиваю процесс(ы) на порту $PORT..."
        kill -9 $PID 2>/dev/null
    fi
    
    # Убить все python процессы с bot.main
    pkill -9 -f "python -m bot.main" 2>/dev/null
    
    # Убить процессы веб-сервера админа
    pkill -9 -f "run_web.sh" 2>/dev/null
    
    # Дополнительная очистка - убить всё на портах
    for PORT in 8001 8000; do
        fuser -k 9 $PORT/tcp 2>/dev/null
    done
    
    sleep 2
    
    # Проверка - убедиться что процессы убиты
    REMAINING=$(pgrep -f "python -m bot.main" 2>/dev/null)
    if [ -n "$REMAINING" ]; then
        echo "Принудительно убиваю оставшиеся процессы: $REMAINING"
        kill -9 $REMAINING 2>/dev/null
        sleep 1
    fi
    
    echo "Все процессы остановлены."
}

# ============================================
# Настройка ngrok туннеля
# ============================================
setup_ngrok() {
    local NGROK_BIN="/tmp/ngrok"
    local NGROK_TOKEN='2OVFaiEfL1v5DuGyLYBt78Nbdhb_8732EsawD6ZCMiUr7rKCB'
    
    # Скачать ngrok если не существует
    if [ ! -f "$NGROK_BIN" ]; then
        echo "⬇️ Скачиваю ngrok..."
        curl -sSL https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz | tar xz -C /tmp/
        chmod +x "$NGROK_BIN"
    fi
    
    # Авторизовать ngrok
    "$NGROK_BIN" authtoken "$NGROK_TOKEN"
    
    echo "🚀 Запуск ngrok туннеля на порт 8001..."
    "$NGROK_BIN" http 8001 &
    NGROK_PID=$!
    sleep 3
    
    # Получить ngrok URL
    local NGROK_URL
    NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels | python3 -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null)
    
    if [ -n "$NGROK_URL" ]; then
        echo "✅ ngrok туннель запущен: $NGROK_URL"
        echo "$NGROK_URL" > /tmp/ngrok_url.txt
    else
        echo "⚠️ Не удалось получить ngrok URL"
        NGROK_PID=""
    fi
}

# ============================================
# Отправка сообщения в Telegram через бота
# ============================================
send_telegram_message() {
    local message="$1"
    local chat_id="-1004309485623"
    local bot_token="${BOT_TOKEN:-}"
    
    if [ -z "$bot_token" ]; then
        # Попробовать прочитать из .env
        if [ -f ".env" ]; then
            bot_token=$(grep '^BOT_TOKEN=' .env | cut -d'=' -f2- | tr -d '"' | tr -d "'" | xargs)
        fi
    fi
    
    if [ -n "$bot_token" ]; then
        echo "📤 Отправка сообщения в Telegram..."
        curl -s -X POST "https://api.telegram.org/bot${bot_token}/sendMessage" \
            -d chat_id="$chat_id" \
            -d text="$message" \
            -d parse_mode="Markdown" \
            --max-time 10 2>/dev/null
        if [ $? -eq 0 ]; then
            echo "✅ Сообщение отправлено в Telegram"
        else
            echo "⚠️ Не удалось отправить сообщение в Telegram"
        fi
    else
        echo "⚠️ BOT_TOKEN не найден, сообщение не отправлено"
        echo "💡 URL для доступа: $NGROK_URL"
    fi
}

# ============================================
# Очистка старого процесса бота
# ============================================
echo "Очистка старых процессов бота..."
kill_all

# Запустить ngrok туннель
setup_ngrok

# ============================================
# Запуск бота и веб-панели админа
# ============================================
cd "$(dirname "$0")"

echo "🌸 Запуск 'Цветы по русски'..."
echo "Бот: Telegram polling"
echo "Веб-панель: http://0.0.0.0:8001"
echo "Спящий режим: отключён"

source .venv/bin/activate

# Запуск бота в фоне с перезапуском при падении
run_bot() {
    while true; do
        python -m bot.main
        echo "⚠️ Бот остановился. Перезапуск через 5 секунд..."
        sleep 5
    done
}

run_bot &
BOT_PID=$!

echo "🤖 Бот запущен (PID: $BOT_PID)"

# Отправить URL в Telegram (с задержкой чтобы бот успел запуститься)
sleep 5
if [ -n "$NGROK_PID" ] && [ -f /tmp/ngrok_url.txt ]; then
    NGROK_URL=$(cat /tmp/ngrok_url.txt)
    send_telegram_message "${NGROK_URL}" 2>/dev/null
fi

# Очистка при выходе
cleanup() {
    echo "Остановка..."
    kill $BOT_PID 2>/dev/null
    [ -n "$PREVENT_SLEEP_PID" ] && kill $PREVENT_SLEEP_PID 2>/dev/null
    [ -n "$NGROK_PID" ] && kill $NGROK_PID 2>/dev/null
    kill_all
    exit 0
}
trap cleanup SIGINT SIGTERM

# Ожидание завершения
wait $BOT_PID
