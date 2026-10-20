#!/bin/bash
# Let another Telegram user talk to @ov_ted_lola_bot:  bash scripts/add_telegram_user.sh <telegram user id>
# Adds the id to the bot's allowlist (.telegram/access.json) and to TELEGRAM_ALLOWED_IDS in .env (the
# Cloudflare Worker's list, used on its next deploy), then restarts the bot — static mode reads the list at boot.
# Ian runs this from a normal session only; the bot itself is denied it (.claude/telegram-bot.settings.json).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
ID="${1:-}"
[[ "$ID" =~ ^[0-9]{5,15}$ ]] || { echo "usage: $0 <numeric telegram user id>" >&2; exit 1; }
[ -z "${ONLY_VANS_BOT:-}" ] || { echo "refused: the Telegram bot can't change who may use it" >&2; exit 1; }

A=.telegram/access.json
jq --arg id "$ID" '.allowFrom |= (. + [$id] | unique)' "$A" > "$A.new"
chmod 600 "$A.new" && mv "$A.new" "$A"
echo "bot allowlist: $(jq -c .allowFrom "$A")"

CUR="$(set -a; . ./.env; printf %s "${TELEGRAM_ALLOWED_IDS:-}")"
if [[ ",$CUR," != *",$ID,"* ]]; then
  NEW="${CUR:+$CUR,}$ID"
  if grep -q '^TELEGRAM_ALLOWED_IDS=' .env; then
    sed -i "s/^TELEGRAM_ALLOWED_IDS=.*/TELEGRAM_ALLOWED_IDS='$NEW'/" .env
  else
    printf "TELEGRAM_ALLOWED_IDS='%s'\n" "$NEW" >> .env
  fi
fi
echo "worker list (.env): $(set -a; . ./.env; printf %s "$TELEGRAM_ALLOWED_IDS")"

bash scripts/telegram_session.sh stop
bash scripts/telegram_session.sh start
