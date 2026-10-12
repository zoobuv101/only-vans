#!/usr/bin/env python3
"""Suggest where Lola camped for an Instagram post (or a date range), from her GPSLive history.

    set -a; . ./.env; set +a
    python3 scripts/suggest_campsite.py                    # new posts (no trip date in overrides.json yet)
    python3 scripts/suggest_campsite.py 17988168282082501  # one post: the 14 nights before it was posted
    python3 scripts/suggest_campsite.py --from 2025-10-08 --to 2025-10-14

For each night in the window, takes where Lola was parked at 03:00 UTC. Nights more than AWAY_KM
from home are grouped into trips (consecutive nights) and stays (same spot within MOVE_KM); each stay
is matched to the nearest OpenStreetMap campsite (Overpass), else the nearest village/town
(Nominatim). Prints suggestions only — Ian confirms before anything goes on the site (his solo trips
are in the same history and must NOT be published).

Run LOCALLY only: the repo and its Actions logs are public, and this prints Lola's overnight positions.
Never prints home. Day files are cached in data/raw/gps/ (gitignored), except the last two days, which
may still be filling. Times are shown in Europe/London. Needs GPSLIVE_API_KEY.
"""
import argparse, datetime as D, json, os, sys, time, urllib.parse, urllib.request
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_routes import RAW, ROOT, km  # noqa: E402

AWAY_KM, MOVE_KM, AT_KM, CAMP_M, LOOKBACK = 16.0, 1.5, 0.3, 500, 14   # 16 km = Ian's "10 miles from home"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]
SPOTS = os.path.join(RAW, ".campsite_lookups.json")  # cache: rounded spot -> OSM campsites (local only)
LONDON, UA = ZoneInfo("Europe/London"), {"User-Agent": "only-vans.uk campsite finder"}


def day(imei, key, d):
    """One UTC day of history; cached unless it may still be growing."""
    f = os.path.join(RAW, f"{d}.json")
    fresh = d >= D.datetime.now(D.timezone.utc).date() - D.timedelta(days=1)
    if fresh or not os.path.exists(f):
        req = urllib.request.Request("https://api.gpslive.app/v1/devices/history", method="POST",
            data=json.dumps({"imei": imei, "dateFrom": f"{d} 00:00:00", "dateTo": f"{d} 23:59:59"}).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as r:
            h = json.load(r)
        if not fresh:
            json.dump(h, open(f, "w"))
        time.sleep(0.5)
    else:
        h = json.load(open(f))
    pts = h if isinstance(h, list) else []
    for p in pts:
        p["t"] = D.datetime.strptime(p["dtTracker"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=D.timezone.utc)
    return pts


def get(url, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.load(r)


def name_spot(at):
    """Nearest OSM campsite within CAMP_M (None if every server failed), else village/town."""
    seen = json.load(open(SPOTS)) if os.path.exists(SPOTS) else {}
    k = f"{at[0]:.4f},{at[1]:.4f}"
    q = (f'[out:json][timeout:25];nwr["tourism"~"^(camp_site|caravan_site)$"](around:{CAMP_M},{at[0]},{at[1]});'
         'out center tags;')
    els = seen.get(k)
    for host in ([] if els is not None else OVERPASS + OVERPASS[:1]):  # the public servers 504 when busy: retry, then try the mirror
        try:
            els = get(host + "?data=" + urllib.parse.quote(q), timeout=30)["elements"]
            break
        except Exception as e:
            err = e
            time.sleep(3)
    if els is None:  # the town fallback below still helps
        print(f"    (campsite lookup failed: {err})")
    else:
        seen[k] = els
        json.dump(seen, open(SPOTS, "w"))
    camps = None if els is None else []
    for e in els or []:
        c = e.get("center") or e
        if "lat" in c and e.get("tags", {}).get("name"):
            camps.append((km(at, (c["lat"], c["lon"])) * 1000, e["tags"]["name"]))
    if camps is not None:
        camps.sort()
    time.sleep(1)
    r = get(f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=14&lat={at[0]}&lon={at[1]}")
    a = r.get("address", {})
    town = next((a[k] for k in ("village", "town", "city", "hamlet", "suburb") if k in a), "")
    area = a.get("county") or a.get("state_district") or a.get("state") or ""
    return camps, ", ".join(x for x in (town, area) if x)


def london(t):
    return t.astimezone(LONDON).strftime("%a %-d %b %H:%M %Z")


def scan(imei, key, home, first, last):
    """Nights first..last (a night belongs to the date it starts on). Returns trips → stays."""
    cache, nights = {}, []
    def pts(d):
        if d not in cache:
            cache[d] = day(imei, key, d) if d <= D.datetime.now(D.timezone.utc).date() else []
        return cache[d]
    n, today = first, D.datetime.now(D.timezone.utc).date()
    while n <= last or (nights and nights[-1][0] == n - D.timedelta(days=1) and n < today):  # run on to the end of a trip still going at `last`
        nxt = n + D.timedelta(days=1)
        cutoff = D.datetime.combine(nxt, D.time(3), D.timezone.utc)
        before = [p for p in pts(n) + pts(nxt) if p["t"] <= cutoff]
        if before:
            p = max(before, key=lambda p: p["t"])
            at = (p["lat"], p["lng"])
            if km(at, home) > AWAY_KM:
                nights.append((n, at))
        n = nxt
    trips = []
    for n, at in nights:
        if trips and trips[-1][-1]["nights"][-1] == n - D.timedelta(days=1):
            stays = trips[-1]
            if km(at, stays[-1]["at"]) <= MOVE_KM:
                stays[-1]["nights"].append(n)
                continue
            stays.append({"at": at, "nights": [n]})
        else:
            trips.append([{"at": at, "nights": [n]}])
    for stays in trips:
        for s in stays:
            a, b = s["nights"][0], s["nights"][-1] + D.timedelta(days=1)
            near = lambda p: km((p["lat"], p["lng"]), s["at"]) <= AT_KM
            arr = [p for p in pts(a) + pts(b) if near(p) and p["t"] <= D.datetime.combine(a + D.timedelta(days=1), D.time(3), D.timezone.utc)]
            day_b = sorted(pts(b), key=lambda p: p["t"])
            gone = [i for i, p in enumerate(day_b) if not near(p) and any(near(q) for q in day_b[:i])]
            s["arrive"] = min((p["t"] for p in arr), default=None)
            s["leave"] = day_b[gone[0] - 1]["t"] if gone else None  # last fix at the spot before driving off
            s["date"], s["end"] = a, b
    return trips


def report(trips, home, label):
    print(f"\n=== {label}")
    if not trips:
        print("  No nights away (> 10 miles from home) — a day trip, or posted long after the trip:"
              " rerun with --from/--to around the trip dates.")
        return
    sites = json.load(open(os.path.join(ROOT, "data", "campsites.json")))
    for i, stays in enumerate(trips):
        nn = sum(len(s["nights"]) for s in stays)
        tag = "  ← most recent" if i == len(trips) - 1 else ""
        print(f"  Trip: {stays[0]['date']:%a %-d %b %Y} → {stays[-1]['end']:%a %-d %b %Y}, {nn} night{'s' * (nn > 1)}{tag}")
        for s in stays:
            camps, place = name_spot(s["at"])
            on = [c["name"] for c in sites if c["date"] <= s["date"].isoformat() <= (c.get("end") or c["date"])
                  and km(s["at"], c["at"]) < 2]
            n = len(s["nights"])
            print(f"    {s['date']:%a %-d} → {s['end']:%a %-d %b}: {n} night{'s' * (n > 1)} near {place or '?'}"
                  f" ({km(s['at'], home):.0f} km from home)")
            if s["arrive"] or s["leave"]:
                print(f"      arrived {london(s['arrive']) if s['arrive'] else '?'}, left {london(s['leave']) if s['leave'] else 'not seen leaving that day'}")
            if camps is None:
                print("      campsite lookup failed (OpenStreetMap servers busy) — run again in a minute")
            elif camps:
                print(f"      campsite: {camps[0][1]} ({camps[0][0]:.0f} m)"
                      + (f"; also {', '.join(f'{c} ({d:.0f} m)' for d, c in camps[1:3])}" if len(camps) > 1 else ""))
            else:
                print(f"      no campsite mapped within {CAMP_M} m (a pub, CL or friend's drive?)")
            if on:
                print(f"      already on the site: {on[0]}")
            else:
                at = [round(s["at"][0], 3), round(s["at"][1], 3)]
                print(f'      suggested campsites.json: {{"name": "{camps[0][1] if camps else place}", "at": {at}, '
                      f'"date": "{s["date"]}", "end": "{s["end"]}"}}')
    print("  ⚠ Confirm with Ian before adding — solo trips are in this history too.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("posts", nargs="*", help="Instagram post ids (default: posts with no trip date yet)")
    ap.add_argument("--from", dest="start", type=D.date.fromisoformat)
    ap.add_argument("--to", dest="end", type=D.date.fromisoformat)
    ap.add_argument("--days", type=int, default=LOOKBACK, help="nights to look back from a post (default 14)")
    a = ap.parse_args()
    key = os.environ.get("GPSLIVE_API_KEY") or sys.exit("GPSLIVE_API_KEY not set (set -a; . ./.env; set +a)")
    imei = open(os.path.join(RAW, ".imei")).read().strip()
    home = tuple(json.load(open(os.path.join(RAW, ".home.json"))))
    if a.start or a.end:
        s, e = a.start or a.end, a.end or a.start
        return report(scan(imei, key, home, s, e), home, f"Nights {s:%-d %b %Y} → {e:%-d %b %Y}")
    posts = {p["id"]: p for p in json.load(open(os.path.join(ROOT, "data", "posts.json")))}
    over = json.load(open(os.path.join(ROOT, "data", "overrides.json")))
    ids = a.posts or [i for i in posts if not over.get(i, {}).get("date") and not over.get(i, {}).get("hide")]
    if not ids:
        print("Every Instagram post already has trip dates in overrides.json — nothing new to look up.")
    for i in ids:
        p = posts.get(i) or sys.exit(f"no post {i} in data/posts.json")
        t = D.datetime.strptime(p["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        d = t.astimezone(LONDON).date()
        cap = " ".join((p.get("caption") or "").split())[:70]
        report(scan(imei, key, home, d - D.timedelta(days=a.days), d), home,
               f"Post {i}, posted {london(t)}: \"{cap}…\"")


if __name__ == "__main__":
    main()
