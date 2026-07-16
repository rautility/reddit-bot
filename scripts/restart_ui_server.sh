#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

HOST="${REDDIT_UI_HOST:-127.0.0.1}"
PORT="${REDDIT_UI_PORT:-8765}"
PY="${PY:-$REPO_ROOT/.venv/bin/python}"
DB_PATH="${REDDIT_UI_DB_PATH:-$REPO_ROOT/reddit_bot.db}"
STATIC_DIR="${REDDIT_UI_STATIC_DIR:-$REPO_ROOT/web}"
ACTIONS_DIR="${REDDIT_UI_ACTIONS_DIR:-$REPO_ROOT/.agent-actions}"
LOG_DIR="${REDDIT_UI_LOG_DIR:-$REPO_ROOT/.agent-ui}"
PID_FILE="${REDDIT_UI_PID_FILE:-$LOG_DIR/reddit-ui.pid}"
LOG_FILE="${REDDIT_UI_LOG_FILE:-$LOG_DIR/reddit-ui.log}"
FOREGROUND=0
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --foreground)
      FOREGROUND=1
      shift
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi

mkdir -p "$LOG_DIR"

collect_old_pids() {
  {
    if [[ -f "$PID_FILE" ]]; then
      sed -n '1p' "$PID_FILE"
    fi
    lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true
    pgrep -f "scripts/reddit_ui.py" 2>/dev/null || true
    pgrep -f "bot.web.server" 2>/dev/null || true
  } | awk 'NF && $1 ~ /^[0-9]+$/ && $1 != "'"$$"'" { print $1 }' | sort -u
}

stop_old_servers() {
  local pids=()
  while IFS= read -r pid; do
    pids+=("$pid")
  done < <(collect_old_pids)

  if [[ ${#pids[@]} -eq 0 ]]; then
    echo "No existing reddit-bot UI server found."
    return
  fi

  echo "Stopping old reddit-bot UI server process(es): ${pids[*]}"
  kill "${pids[@]}" 2>/dev/null || true
  sleep 1

  local still_running=()
  local pid
  for pid in "${pids[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      still_running+=("$pid")
    fi
  done

  if [[ ${#still_running[@]} -gt 0 ]]; then
    echo "Force-stopping old reddit-bot UI server process(es): ${still_running[*]}"
    kill -9 "${still_running[@]}" 2>/dev/null || true
  fi
}

stop_old_servers

cd "$REPO_ROOT"
echo "Starting reddit-bot UI on http://$HOST:$PORT"
echo "Using DB: $DB_PATH"
if [[ "$FOREGROUND" == "1" ]]; then
  echo "$$" > "$PID_FILE"
  exec "$PY" "$REPO_ROOT/scripts/reddit_ui.py" \
    --host "$HOST" \
    --port "$PORT" \
    --db-path "$DB_PATH" \
    --static-dir "$STATIC_DIR" \
    --actions-dir "$ACTIONS_DIR" \
    "${EXTRA_ARGS[@]}"
fi

nohup "$PY" "$REPO_ROOT/scripts/reddit_ui.py" \
  --host "$HOST" \
  --port "$PORT" \
  --db-path "$DB_PATH" \
  --static-dir "$STATIC_DIR" \
  --actions-dir "$ACTIONS_DIR" \
  "${EXTRA_ARGS[@]}" >>"$LOG_FILE" 2>&1 &

server_pid=$!
echo "$server_pid" > "$PID_FILE"
sleep 1

if ! kill -0 "$server_pid" 2>/dev/null; then
  echo "Failed to start reddit-bot UI. Last log lines:"
  tail -n 40 "$LOG_FILE" || true
  exit 1
fi

echo "reddit-bot UI restarted with PID $server_pid"
echo "Log: $LOG_FILE"
