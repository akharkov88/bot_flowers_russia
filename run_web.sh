#!/bin/bash
# Запуск веб-панели админа с автоубийством старого процесса

PORT=8001
PID=$(lsof -t -i:$PORT 2>/dev/null)

if [ -n "$PID" ]; then
    echo "Убиваю старый процесс на порту $PORT (PID: $PID)..."
    kill -9 $PID 2>/dev/null
    sleep 1
fi

cd "$(dirname "$0")"
source .venv/bin/activate
uvicorn admin_web.main:app --host 0.0.0.0 --port $PORT --reload
python -m bot.main