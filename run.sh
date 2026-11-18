#!/bin/bash

PORT=8001
PID=$(lsof -t -i:$PORT 2>/dev/null)

if [ -n "$PID" ]; then
    echo "Убиваю старый процесс на порту $PORT (PID: $PID)..."
    kill -9 $PID 2>/dev/null
    sleep 1
fi
# Запуск бота и веб-панели админа
cd "$(dirname "$0")"

echo "🌸 Запуск 'Цветы по русски'..."
echo "Бот: Telegram polling"
echo "Веб-панель: http://0.0.0.0:8001"

source .venv/bin/activate
python -m bot.main
