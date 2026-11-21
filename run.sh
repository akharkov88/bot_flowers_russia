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
    xset s off        # отключить экранную заставку
    xset -dpms        # отключить DPMS (выключение дисплея)
    xset s noblank    # отключить бланкирование экрана
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
# Очистка старого процесса
# ============================================
PORT=8001
PID=$(lsof -t -i:$PORT 2>/dev/null)

if [ -n "$PID" ]; then
    echo "Убиваю старый процесс на порту $PORT (PID: $PID)..."
    kill -9 $PID 2>/dev/null
    sleep 1
fi

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

# Очистка при выходе
cleanup() {
    echo "Остановка..."
    kill $BOT_PID 2>/dev/null
    [ -n "$PREVENT_SLEEP_PID" ] && kill $PREVENT_SLEEP_PID 2>/dev/null
    exit 0
}
trap cleanup SIGINT SIGTERM

# Ожидание завершения
wait $BOT_PID
