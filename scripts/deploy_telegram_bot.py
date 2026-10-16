#!/usr/bin/env python3
"""Deploy telegram/worker.js to Cloudflare and point the Telegram bot's webhook at it.

    set -a; . ./.env; set +a; python3 scripts/deploy_telegram_bot.py

Needs in .env: CLOUDFLARE_API_TOKEN (Account → Workers Scripts: Edit), CLOUDFLARE_ACCOUNT_ID,
TELEGRAM_BOT_TOKEN (from @BotFather), GH_DISPATCH_PAT (fine-grained, only-vans, Actions: read & write),
TELEGRAM_ALLOWED_IDS (comma-separated Telegram user ids allowed to use the bot).
Safe to re-run: re-uploads the Worker, sets a fresh webhook secret and re-registers the webhook.
Never prints a secret.
"""
import json, os, secrets, sys, urllib.error, urllib.request, uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "only-vans-bot"
CF = "https://api.cloudflare.com/client/v4"
NEED = ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "TELEGRAM_BOT_TOKEN", "GH_DISPATCH_PAT", "TELEGRAM_ALLOWED_IDS"]


def call(url, method="GET", body=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": "application/json", **(headers or {})}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=h), timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # The URL may contain the bot token, so report only the host + status.
        sys.exit(f"{method} {url.split('/')[2]} → HTTP {e.code}: {e.read()[:300].decode(errors='replace')}")


def main():
    missing = [k for k in NEED if not os.environ.get(k)]
    if missing:
        sys.exit("Missing in .env: " + ", ".join(missing))
    acct, cf = os.environ["CLOUDFLARE_ACCOUNT_ID"], {"Authorization": "Bearer " + os.environ["CLOUDFLARE_API_TOKEN"]}
    tg = "https://api.telegram.org/bot" + os.environ["TELEGRAM_BOT_TOKEN"]
    base = f"{CF}/accounts/{acct}/workers/scripts/{NAME}"

    # 1. Upload the Worker (ES module, multipart).
    b = uuid.uuid4().hex
    meta = json.dumps({"main_module": "worker.js", "compatibility_date": "2024-09-23", "keep_bindings": ["secret_text"]})
    code = open(os.path.join(ROOT, "telegram", "worker.js"), "rb").read()
    raw = (f'--{b}\r\nContent-Disposition: form-data; name="metadata"\r\nContent-Type: application/json\r\n\r\n{meta}\r\n'
           f'--{b}\r\nContent-Disposition: form-data; name="worker.js"; filename="worker.js"\r\n'
           f'Content-Type: application/javascript+module\r\n\r\n').encode() + code + f"\r\n--{b}--\r\n".encode()
    call(base, "PUT", raw=raw, headers={**cf, "Content-Type": f"multipart/form-data; boundary={b}"})
    print("Worker uploaded:", NAME)

    # 2. Secrets (a fresh webhook secret each deploy; Telegram is re-registered with it below).
    hook_secret = secrets.token_urlsafe(32)
    for k, v in {"BOT_TOKEN": os.environ["TELEGRAM_BOT_TOKEN"], "GH_PAT": os.environ["GH_DISPATCH_PAT"],
                 "ALLOWED_IDS": os.environ["TELEGRAM_ALLOWED_IDS"], "WEBHOOK_SECRET": hook_secret}.items():
        call(base + "/secrets", "PUT", {"name": k, "text": v, "type": "secret_text"}, cf)
    print("Secrets set: BOT_TOKEN, GH_PAT, ALLOWED_IDS, WEBHOOK_SECRET")

    # 3. Public URL on workers.dev.
    call(base + "/subdomain", "POST", {"enabled": True}, cf)
    sub = call(f"{CF}/accounts/{acct}/workers/subdomain", headers=cf)["result"]["subdomain"]
    url = f"https://{NAME}.{sub}.workers.dev/"
    print("Worker URL:", url)

    # 4. Telegram: webhook + command menu.
    r = call(tg + "/setWebhook", "POST", {"url": url, "secret_token": hook_secret,
                                          "allowed_updates": ["message"], "drop_pending_updates": True})
    print("Telegram webhook:", r.get("description"))
    call(tg + "/setMyCommands", "POST", {"commands": [
        {"command": "update", "description": "Check Instagram and rebuild the site now"},
        {"command": "status", "description": "How the last site update went"}]})
    me = call(tg + "/getMe")["result"]
    print(f"Done. Message @{me['username']} with /update")


if __name__ == "__main__":
    main()
