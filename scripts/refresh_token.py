#!/usr/bin/env python3
"""Renew the long-lived Instagram token (Instagram API with Instagram Login).

Each refresh returns a token valid for another 60 days. Needs IG_TOKEN in the environment.
The token must be >24h old and not yet expired; once expired it cannot be refreshed —
regenerate it in the Meta dashboard (Instagram > API setup > Generate token).

Where the new token goes:
  --env-file PATH   upsert IG_TOKEN='...' into that .env (local runs)
  --gh-secret       `gh secret set IG_TOKEN` via stdin (GitHub Actions; needs GH_TOKEN with
                    secrets:write on this repo — the default GITHUB_TOKEN cannot write secrets)

Always writes data/token-status.json (dates only, never the token) and exits non-zero on any
failure or if the renewed token has < MIN_DAYS left — a failed scheduled run is the alert.
"""
import argparse, json, os, subprocess, sys, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

MIN_DAYS = 45
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATUS = os.path.join(ROOT, "data", "token-status.json")


def fail(msg):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def upsert_env(path, key, value):
    lines = []
    if os.path.exists(path):
        with open(path) as f:
            lines = [l for l in f if not l.startswith(key + "=")]
    v = value.replace("'", "'\\''")
    lines.append(f"{key}='{v}'\n")
    tmp = path + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.writelines(lines)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--gh-secret", action="store_true")
    args = ap.parse_args()
    if not (args.env_file or args.gh_secret):
        fail("choose --env-file and/or --gh-secret, or the new token is lost")

    old = os.environ.get("IG_TOKEN") or fail("IG_TOKEN not set")
    url = "https://graph.instagram.com/refresh_access_token?" + urllib.parse.urlencode(
        {"grant_type": "ig_refresh_token", "access_token": old})
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        fail(f"refresh HTTP {e.code}: {e.read().decode()[:300].replace(old, '<token>')}")
    except urllib.error.URLError as e:
        fail(f"refresh network error: {e.reason}")

    new, expires_in = resp.get("access_token"), resp.get("expires_in")
    if not new or not expires_in:
        fail(f"unexpected refresh response keys: {sorted(resp)}")
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::add-mask::{new}")  # new value isn't a registered secret yet

    if args.env_file:
        upsert_env(args.env_file, "IG_TOKEN", new)
    if args.gh_secret:
        r = subprocess.run(["gh", "secret", "set", "IG_TOKEN"], input=new, text=True,
                           capture_output=True)
        if r.returncode:
            fail(f"gh secret set failed: {r.stderr.strip()[:300]}")

    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=int(expires_in))
    days = int(expires_in) // 86400
    os.makedirs(os.path.dirname(STATUS), exist_ok=True)
    with open(STATUS, "w") as f:
        json.dump({"last_refreshed_utc": now.isoformat(timespec="seconds"),
                   "expires_utc": expires.isoformat(timespec="seconds"),
                   "days_left": days, "token_changed": new != old}, f, indent=2)
        f.write("\n")
    print(f"refreshed: {days} days left, expires {expires:%Y-%m-%d} (UTC), "
          f"token {'changed' if new != old else 'unchanged'}")
    if days < MIN_DAYS:
        fail(f"renewed token has only {days} days left (< {MIN_DAYS}) — regenerate it")


if __name__ == "__main__":
    main()
