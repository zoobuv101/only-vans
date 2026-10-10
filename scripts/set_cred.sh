#!/bin/bash
# Upsert a secret KEY=value into only-vans/.env WITHOUT the value touching shell history,
# argv (ps), or the chat transcript. Adapted from FW_agent/scripts/_shared/set_cred.sh.
#
#   usage:  bash scripts/set_cred.sh KEY        (prompts silently for the value)
#
# Value is read with `read -rs`, passed to the writer via the environment (never argv),
# and stored SINGLE-QUOTED so .env stays `source`-able for any password.
set -euo pipefail
KEY="${1:?usage: set_cred.sh KEY}"
[[ "$KEY" =~ ^[A-Z0-9_]+$ ]] || { echo "KEY must be [A-Z0-9_]" >&2; exit 1; }
# Assert the resolved root really is this project — a wrong depth would silently write the
# secret somewhere nothing reads (bit FW_agent's copy twice).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ "$(basename "$ROOT")" == "only-vans" && -f "$ROOT/CLAUDE.md" ]] || {
  echo "set_cred.sh: resolved root '$ROOT' is not only-vans — refusing to write a secret there." >&2
  exit 1
}
F="$ROOT/.env"

[ -t 0 ] || { echo "set_cred.sh: no interactive terminal — run this in a real terminal, not via '!'." >&2; exit 1; }
read -rsp "Value for $KEY: " CRED_VALUE; echo
touch "$F"; chmod 600 "$F"
grep -v "^${KEY}=" "$F" > "$F.tmp" 2>/dev/null || true

CRED_VALUE="$CRED_VALUE" KEY="$KEY" FTMP="$F.tmp" python3 <<'PY'
import os
v = os.environ["CRED_VALUE"].replace("'", "'\\''")
with open(os.environ["FTMP"], "a") as f:
    f.write(os.environ["KEY"] + "='" + v + "'\n")
PY

mv "$F.tmp" "$F"; chmod 600 "$F"
unset CRED_VALUE
echo "stored $KEY in $(basename "$F")"
