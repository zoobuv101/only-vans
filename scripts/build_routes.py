#!/usr/bin/env python3
"""Build data/routes.json (Lola's driving routes per trip) from GPSLive history.

    set -a; . ./.env; set +a; python3 scripts/build_routes.py

Fetches POST /v1/devices/history per trip day (cached in data/raw/gps/, gitignored), keeps the
points where Lola was moving, cuts everything within PRIVACY_KM of home (home = HA zone.home,
cached in data/raw/gps/.home.json, never committed), splits on gaps, simplifies to ~SIMPLIFY_M and
rounds to 4 dp. Output: data/raw/gps/routes.json (local, gitignored) — routes are OFF the public map. dtTracker is UTC (checked against photo times 2026-10-10). Trip dates come from
data/campsites.json, so a new trip only needs a campsite entry. Needs GPSLIVE_API_KEY.
"""
import datetime as D, json, math, os, sys, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw", "gps")
PRIVACY_KM, LOCAL_KM, SIMPLIFY_M, GAP_S = 10.0, 30.0, 30, 600
MILTON = (51.618, -1.304)  # A34 Milton Interchange: the connector must pass here


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


def connector(ends):
    """One A34 through-line from the north boundary end (Abingdon) past Milton and Chilton to the
    south boundary end (East Ilsley), so routes join a through-road instead of dead-ending at a circle
    centred on home (Ian, 2026-10-10). Lola never drives the Milton-Chilton stretch (southbound trips
    leave via West Hagbourne), so the road shape comes from the public OSRM router (OSM data), cached.
    Only the two A34 end points are sent, both PRIVACY_KM from home."""
    cache = os.path.join(RAW, ".a34.json")
    if not os.path.exists(cache):
        north, south = max(ends), min(ends)  # by latitude
        url = (f"https://router.project-osrm.org/route/v1/driving/{north[1]},{north[0]};{south[1]},{south[0]}"
               "?overview=full&geometries=geojson")
        req = urllib.request.Request(url, headers={"User-Agent": "only-vans.uk route builder"})
        with urllib.request.urlopen(req, timeout=60) as r:
            coords = json.load(r)["routes"][0]["geometry"]["coordinates"]
        json.dump([[lat, lon] for lon, lat in coords], open(cache, "w"))
    line = [tuple(p) for p in json.load(open(cache))]
    if min(km(p, MILTON) for p in line) > 1.0:
        sys.exit("connector does not follow the A34 past Milton — check .a34.json")
    return line


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
            if km(ll, home) < PRIVACY_KM:
                if cur:
                    segs.append(cur); cur = []
                continue
            if p.get("speed", 0) <= 3:
                continue
            if last_t and (t - last_t).total_seconds() > GAP_S and cur:
                segs.append(cur); cur = []
            cur.append(ll); last_t = t
        if cur:
            segs.append(cur)
        segs = [s for s in segs if max(km(p, home) for p in s) >= LOCAL_KM]  # drop local runs near home
        segs = [[[round(a, 4), round(b, 4)] for a, b in simplify(s, SIMPLIFY_M)] for s in segs if len(s) > 2]
        n = sum(len(s) for s in segs)
        print(f'{c["name"]:45} {len(pts):5} pts -> {len(segs)} segments, {n} points')
        if segs:
            routes.append({"campsite": c["name"], "date": c["date"], "end": c.get("end"), "segments": segs})
    routes.sort(key=lambda r: r["date"])
    # join every boundary end to the A34 through-line
    ends = [tuple(e) for r in routes for s in r["segments"] for e in (s[0], s[-1]) if km(e, home) < PRIVACY_KM + 1.5]
    a34 = connector(ends) or sys.exit("no A34 pass found in history to use as connector")
    a34 = [[round(a, 4), round(b, 4)] for a, b in simplify(a34, SIMPLIFY_M)]
    for r in routes:
        for s in r["segments"]:
            if km(s[0], home) < PRIVACY_KM + 1.5:
                s.insert(0, min((a34[0], a34[-1]), key=lambda e: km(e, s[0])))
            if km(s[-1], home) < PRIVACY_KM + 1.5:
                s.append(min((a34[0], a34[-1]), key=lambda e: km(e, s[-1])))
    print(f"A34 connector: {len(a34)} points, {len(ends)} route ends joined")
    with open(os.path.join(RAW, "routes.json"), "w") as f:  # local only; see SHOW_ROUTES in site/build.py
        json.dump({"connector": a34, "routes": routes}, f, separators=(",", ":"))
        f.write("\n")


if __name__ == "__main__":
    main()
