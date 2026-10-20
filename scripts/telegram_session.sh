#!/bin/bash
# Run Claude Code in this folder with the Telegram channel, so Ian can talk to it via @ov_ted_lola_bot.
#
#   bash scripts/telegram_session.sh start    # start in a detached tmux session "only-vans-bot"
#   bash scripts/telegram_session.sh status   # session running or not
#   bash scripts/telegram_session.sh check    # is the Telegram plugin actually connected
#   bash scripts/telegram_session.sh attach   # look at / type into it (detach: Ctrl-b then d)
#   bash scripts/telegram_session.sh stop
#
# Only TELEGRAM_BOT_TOKEN is taken from .env (via the environment, never argv). Plugin state —
# the allowlist access.json, downloaded attachments — lives in .telegram/ (gitignored), not ~/.claude.
# The Telegram plugin long-polls, so the bot must have NO webhook: start deletes the Cloudflare
# Worker's webhook. To hand the bot back to the Worker: stop, then scripts/deploy_telegram_bot.py.
# Tool approvals beyond .claude/settings.local.json's allowlist arrive in Telegram as Allow/Deny buttons.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME=only-vans-bot
cd "$ROOT"

# PIDs of Telegram plugin servers using OUR state dir (i.e. polling @ov_ted_lola_bot for this project).
pollers() {
  for p in $(pgrep -f 'bun server.ts'); do
    tr '\0' '\n' < "/proc/$p/environ" 2>/dev/null | grep -qx "TELEGRAM_STATE_DIR=$ROOT/.telegram" && echo "$p"
  done
}

case "${1:-}" in
  start)
    tmux has-session -t "$NAME" 2>/dev/null && { echo "already running (attach: $0 attach)"; exit 0; }
    TOKEN="$(set -a; . ./.env; printf %s "${TELEGRAM_BOT_TOKEN:-}")"
    [ -n "$TOKEN" ] || { echo "TELEGRAM_BOT_TOKEN missing from .env" >&2; exit 1; }
    TELEGRAM_BOT_TOKEN="$TOKEN" python3 - <<'PY'
import json, os, urllib.request
r = json.load(urllib.request.urlopen(
    f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/deleteWebhook", timeout=20))
print("webhook removed" if r.get("ok") else f"deleteWebhook failed: {r}")
PY
    # Telegram allows ONE poller per bot. A leftover plugin process from an earlier session would make the
    # new one fail at startup (409) — and the session then sits there deaf. Clear ours (by state dir) first.
    for p in $(pollers); do kill "$p" 2>/dev/null && echo "stopped leftover Telegram poller $p"; done
    # Claude Code caches an MCP start failure machine-wide for ~15 min and silently skips the server in
    # every session meanwhile (anthropics/claude-code#97314) — drop just our plugin's entry first.
    python3 - "$HOME/.claude/mcp-needs-auth-cache.json" <<'PY'
import json, os, sys
f = sys.argv[1]
if os.path.exists(f):
    d = json.load(open(f))
    if d.pop("plugin:telegram:telegram", None) is not None:
        json.dump(d, open(f, "w")); print("cleared cached Telegram start failure")
PY
    # Some starts come up without the plugin connected (seen 2026-10-16, cause not pinned down) — so
    # check for it and retry rather than trusting the start.
    for try in 1 2 3; do
      tmux new-session -d -s "$NAME" -c "$ROOT" "bash '$ROOT/scripts/telegram_session.sh' run"
      for _ in $(seq 1 12); do sleep 5; [ -n "$(pollers)" ] && break; done
      if [ -n "$(pollers)" ]; then echo "started in tmux session $NAME — Telegram connected"; exit 0; fi
      echo "attempt $try: session up but Telegram plugin not connected — restarting"
      tmux kill-session -t "$NAME" 2>/dev/null; sleep 3
    done
    echo "FAILED: Telegram plugin would not connect after 3 attempts (attach and run /mcp → plugin:telegram → Reconnect)" >&2
    exit 1
    ;;
  check) [ -n "$(pollers)" ] && echo "Telegram connected (pid $(pollers | tr '\n' ' '))" || { echo "Telegram NOT connected"; exit 1; } ;;
  run)  # inside tmux: token goes into the environment here, so it never appears in tmux's argv
    TELEGRAM_BOT_TOKEN="$(set -a; . ./.env; printf %s "${TELEGRAM_BOT_TOKEN:-}")"
    export TELEGRAM_BOT_TOKEN TELEGRAM_STATE_DIR="$ROOT/.telegram" TELEGRAM_ACCESS_MODE=static
    export PATH="$HOME/.bun/bin:$PATH" ONLY_VANS_BOT=1   # suggest_campsite.py hides trips in progress
    # When started from inside another Claude Code session, tmux hands over that session's CLAUDE*
    # variables (CLAUDE_CODE_CHILD_SESSION, …SESSION_ID, …MESSAGING_SOCKET) and the bot then runs as
    # its child — without the Telegram plugin. Start clean.
    for v in $(compgen -e | grep -E '^(CLAUDECODE|CLAUDE_CODE_|CLAUDE_PID|CLAUDE_EFFORT)'); do unset "$v"; done
    # Bot-only settings: enables the Telegram plugin (it's disabled for every other session, so they can't
    # poison Claude Code's machine-wide MCP failure cache) + the bot-only deny rules.
    exec claude ${BOT_DEBUG:+--debug-file "$BOT_DEBUG"} --settings "$ROOT/.claude/telegram-bot.settings.json" --permission-mode default --channels plugin:telegram@claude-plugins-official
    ;;
  status) tmux has-session -t "$NAME" 2>/dev/null && echo running || echo "not running" ;;
  attach) exec tmux attach -t "$NAME" ;;
  stop)   tmux kill-session -t "$NAME" 2>/dev/null && echo stopped || echo "not running" ;;
  *) sed -n 2,13p "$0"; exit 1 ;;
esac
