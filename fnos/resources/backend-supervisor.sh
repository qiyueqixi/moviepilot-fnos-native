#!/bin/bash
set -u

python_bin="${MOVIEPILOT_PYTHON:?MOVIEPILOT_PYTHON is required}"
log_file="${MOVIEPILOT_LOG_FILE:?MOVIEPILOT_LOG_FILE is required}"
backend_pid=""
resource_restart_done=0

stop_backend() {
    if [ -n "$backend_pid" ] && kill -0 "$backend_pid" 2>/dev/null; then
        kill "$backend_pid" 2>/dev/null || true
        wait "$backend_pid" 2>/dev/null || true
    fi
    exit 0
}
trap stop_backend TERM INT

while true; do
    "$python_bin" -u -m app.main &
    backend_pid=$!
    wait "$backend_pid"
    exit_code=$?
    backend_pid=""

    if [ "$exit_code" -eq 0 ] && [ "$resource_restart_done" -eq 0 ] \
        && tail -n 160 "$log_file" 2>/dev/null | grep -Fq "资源包更新完成，开始重启服务"; then
        resource_restart_done=1
        echo "[fnOS] 资源包更新完成，正在自动重启 MoviePilot 后台服务..."
        sleep 2
        continue
    fi
    exit "$exit_code"
done
