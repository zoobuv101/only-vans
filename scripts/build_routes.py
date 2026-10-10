#!/usr/bin/env python3
"""Build data/routes.json (Lola's driving routes per trip) from GPSLive history.

    set -a; . ./.env; set +a; python3 scripts/build_routes.py

Fetches POST /v1/devices/history per trip day (cached in data/raw/gps/, gitignored), keeps the
points where Lola was moving, cuts everything within PRIVACY_KM of home (home = HA zone.home,
cached in data/raw/gps/.home.json, never committed), splits on gaps, simplifies to ~SIMPLIFY_M and
rounds to 4 dp. dtTracker is UTC (checked against photo times 2026-10-10). Trip dates come from
data/campsites.json, so a new trip only needs a campsite entry. Needs GPSLIVE_API_KEY.
"""
import datetime as D, json, math, os, sys, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw", "gps")
PRIVACY_KM, SIMPLIFY_M, GAP_S = 3.0, 30, 600


def km(a, b):
    p = math.radians
    x, y = p(b[0] - a[0]), p(b[1] - a[1])
    h = math.sin(x / 2) ** 2 + math.cos(p(a[0])) * math.cos(p(b[0])) * math.sin(y / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def simplify(pts, tol_m):
    """Douglas-Peucker on an equirectangular projection (fine at route scale)."""
    if len(pts) < 3:
        return pts
    lat0 = math.radians(pts[0][0])
    xy = [(p[1] * 111320 * math.cos(lat0), p[0] * 110540) for p in pts]
    keep, stack = {0, len(pts) - 1}, [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        (x1, y1), (x2, y2) = xy[i], xy[j]
        L = math.hypot(x2 - x1, y2 - y1) or 1e-9
        best, idx = 0, None
        for k in range(i + 1, j):
            d = abs((y2 - y1) * xy[k][0] - (x2 - x1) * xy[k][1] + x2 * y1 - y2 * x1) / L
            if d > best:
                best, idx = d, k
        if idx is not None and best > tol_m:
            keep.add(idx)
            stack += [(i, idx), (idx, j)]
    return [pts[k] for k in sorted(keep)]


def day(imei, key, d):
    f = os.path.join(RAW, f"{d}.json")
    if not os.path.exists(f):
        req = urllib.request.Request("https://api.gpslive.app/v1/devices/history", method="POST",
            data=json.dumps({"imei": imei, "dateFrom": f"{d} 00:00:00", "dateTo": f"{d} 23:59:59"}).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as r:
            json.dump(json.load(r), open(f, "w"))
        time.sleep(0.5)
    h = json.load(open(f))
    return h if isinstance(h, list) else []


def main():
    key = os.environ.get("GPSLIVE_API_KEY") or sys.exit("GPSLIVE_API_KEY not set")
    imei = open(os.path.join(RAW, ".imei")).read().strip()
    home = json.load(open(os.path.join(RAW, ".home.json")))
    routes, used = [], set()
    # newest first, so a moving day shared by two campsites (e.g. Kendal -> Moss Howe on 23 Sep)
    # is drawn once, with the campsite they moved TO
    for c in sorted(json.load(open(os.path.join(ROOT, "data", "campsites.json"))), key=lambda c: c["date"], reverse=True):
        d, end = D.date.fromisoformat(c["date"]), D.date.fromisoformat(c.get("end") or c["date"])
        pts = []
        while d <= end:
            if d not in used:
                pts += day(imei, key, d)
                used.add(d)
            d += D.timedelta(days=1)
        segs, cur, last_t = [], [], None
        for p in sorted(pts, key=lambda p: p["dtTracker"]):
            t = D.datetime.strptime(p["dtTracker"], "%Y-%m-%d %H:%M:%S")
            ll = (p["lat"], p["lng"])
            if p.get("speed", 0) <= 3 or km(ll, home) < PRIVACY_KM:
                if km(ll, home) < PRIVACY_KM and cur:
                    segs.append(cur); cur = []
                continue
            if last_t and (t - last_t).total_seconds() > GAP_S and cur:
                segs.append(cur); cur = []
            cur.append(ll); last_t = t
        if cur:
            segs.append(cur)
        segs = [[[round(a, 4), round(b, 4)] for a, b in simplify(s, SIMPLIFY_M)] for s in segs if len(s) > 2]
        n = sum(len(s) for s in segs)
        print(f'{c["name"]:45} {len(pts):5} pts -> {len(segs)} segments, {n} points')
        if segs:
            routes.append({"campsite": c["name"], "date": c["date"], "end": c.get("end"), "segments": segs})
    routes.sort(key=lambda r: r["date"])
    with open(os.path.join(ROOT, "data", "routes.json"), "w") as f:
        json.dump(routes, f, separators=(",", ":"))
        f.write("\n")


if __name__ == "__main__":
    main()
