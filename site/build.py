"""Build the only-vans.uk static site from the Instagram feed.

    python3 site/build.py            # -> site/public/  (what GitHub Pages serves)
    python3 site/build.py --preview  # -> site/preview/ (index without the document wrapper, for an Artifact preview)

Posts come from data/posts.json (written by scripts/sync_instagram.py); titles, places and which
vans went come from data/overrides.json. Layout follows the uv101.uk (seestar) site: a full-bleed
hero on the front page, a single reading column, and one page per adventure.
Needs Pillow (thumbnails are made at build time into <out>/img/thumb/).
"""
import datetime
import html
import json
import os
import re
import shutil
import sys
from zoneinfo import ZoneInfo

from PIL import Image

SITE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SITE)
DOMAIN = "only-vans.uk"
IG = "https://www.instagram.com/tedandlolasonlyvans/"
LONDON = ZoneInfo("Europe/London")
HERO = ("18115457765014274", 0)  # both vans, tops up, outside Winchester
NAV = [("adventures", "index.html#adventures", "Adventures"), ("map", "index.html#map", "Map"), ("ig", IG, "Instagram")]
LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/"
# Lola's GPS routes: data kept locally (data/raw/gps/routes.json, gitignored); off the public map
# since 2026-10-10 at Ian's request. Set True (and copy the file to data/routes.json) to show them again.
SHOW_ROUTES = False
FONTS = ("https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700"
         "&family=Nunito+Sans:opsz,wght@6..12,400;6..12,600&family=DM+Mono:wght@400;500&display=swap")
# Old and current handles of the van account both mean "Ted & Lola" in captions.
OWN = {"tedandlolasonlyvans", "tedandlolasadventures"}

esc = lambda v: html.escape(str(v), quote=True)  # noqa: E731


def local(ts: str) -> datetime.datetime:
    return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").astimezone(LONDON)


def caption_html(text: str) -> str:
    def handle(m):
        h = m.group(1).rstrip(".")
        url = IG if h in OWN else f"https://www.instagram.com/{h}/"
        return f'<a href="{url}">@{esc(h)}</a>'
    paras = [p.strip() for p in text.split("\n") if p.strip()]
    url = lambda m: f'<a href="{m.group(0)}">{m.group(0).split("//", 1)[1].rstrip("/")}</a>'  # noqa: E731
    link = lambda t: re.sub(r"https?://[^\s<]*[^\s<.,;:!?)]", url, t) if "://" in t else re.sub(r"@([A-Za-z0-9_.]+)", handle, t)  # noqa: E731
    return "\n".join("<p>" + link(esc(p)) + "</p>" for p in paras)


HANDLES = {k: v for k, v in json.load(open(os.path.join(ROOT, "data", "handles.json"))).items() if not k.startswith("_")}


def plain(text: str, n: int = 150) -> str:
    """Caption as readable plain text for summaries: our own handle -> "Ted & Lola", known handles ->
    names (data/handles.json), the trailing list of tagged people dropped, emoji removed."""
    t = re.sub(r"[^\w\s.,!?'’&()@-]", " ", text)
    t = re.sub(r"\s+", " ", t).strip()
    while True:  # drop the tag list at the end (but never our own handle)
        m = re.search(r"\s*@([A-Za-z0-9_.]+?)\.?$", t)
        if not m or m.group(1) in OWN:
            break
        t = t[:m.start()].rstrip()
    t = re.sub(r"@(?:%s) custodians" % "|".join(OWN), "Ted & Lola's custodians", t)
    t = re.sub(r"@([A-Za-z0-9_.]*[A-Za-z0-9_])", lambda m: "Ted & Lola" if m.group(1) in OWN else HANDLES.get(m.group(1), m.group(0)), t)
    t = re.sub(r"\s+([.,!?])", r"\1", t).strip(" .,")
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + "…"


def span(start: datetime.date, end: datetime.date | None, long: bool = False) -> str:
    """'14 Aug 2026', '14–16 Aug 2026', '30 Aug – 2 Sep 2026' (long: full day/month names)."""
    d, m = ("%A %-d", "%B") if long else ("%-d", "%b")
    if not end or end == start:
        return start.strftime(f"{d} {m} %Y")
    if (start.year, start.month) == (end.year, end.month):
        return f"{start:%-d}–{end:%-d} " + end.strftime(f"{m} %Y")
    if start.year == end.year:
        return f"{start:%-d} " + start.strftime(m) + " – " + end.strftime(f"%-d {m} %Y")
    return start.strftime(f"%-d {m} %Y") + " – " + end.strftime(f"%-d {m} %Y")


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower().replace("'", "")).strip("-")[:60]


def load_posts() -> list[dict]:
    posts = json.load(open(os.path.join(ROOT, "data", "posts.json")))
    over = json.load(open(os.path.join(ROOT, "data", "overrides.json")))
    # Trips that never went on Instagram (photos from Google Photos etc.), same keys as overrides
    # plus "caption" and "photos"; their date is required since there is no posting date.
    manual = json.load(open(os.path.join(ROOT, "data", "manual.json")))
    for mid, m in manual.items():
        if mid.startswith("_"):
            continue
        posts.append({"id": mid, "timestamp": f'{m["date"]}T12:00:00+0000', "permalink": "",
                      "caption": m.get("caption", ""), "media": []})
        over[mid] = {**m, "extra": m.get("photos", [])}
    out = []
    for p in posts:
        o = over.get(p["id"], {})
        # extra photos (not from Instagram) are appended after the post's own
        p["media"] = p["media"] + [photo(src) for src in o.get("extra", [])]
        if o.get("order"):  # indices into Instagram media + extras, in display order
            p["media"] = [p["media"][i] for i in o["order"]]
        if o.get("hide") or not p["media"]:
            continue
        # Trip dates from overrides win; otherwise fall back to the Instagram posting date.
        dated = bool(o.get("date"))
        when = datetime.date.fromisoformat(o["date"]) if dated else local(p["timestamp"]).date()
        end = datetime.date.fromisoformat(o["end"]) if o.get("end") else None
        title = o.get("title") or plain(p["caption"], 60) or "On the road"
        p.update(title=title, place=o.get("place", ""), at=o.get("at"), notes=o.get("notes", ""), when_text=o.get("when_text", ""), vans=o.get("vans", "Ted & Lola"),
                 when=when, end=end, dated=dated, cover=p["media"][min(o.get("cover", 0), len(p["media"]) - 1)],
                 slug=f"{when:%Y-%m-%d}-{slugify(title)}")
        out.append(p)
    out.sort(key=lambda x: (x["when"], x["timestamp"]), reverse=True)
    return out


def photo(src: str) -> dict:
    w, h = Image.open(os.path.join(SITE, src)).size
    return {"src": src, "w": w, "h": h, "video": False}


def thumbs(posts: list[dict], out: str) -> None:
    """800px copies for the adventure list and photo grids."""
    d = os.path.join(out, "img", "thumb")
    os.makedirs(d, exist_ok=True)
    for p in posts:
        for m in p["media"]:
            dst = os.path.join(d, os.path.basename(m["src"]))
            if not os.path.exists(dst):
                im = Image.open(os.path.join(SITE, m["src"]))
                im.thumbnail((800, 800))
                im.save(dst, "JPEG", quality=78, optimize=True, progressive=True)


def thumb(m: dict) -> str:
    return "img/thumb/" + os.path.basename(m["src"])


def layout(body: str, meta: dict, depth: int, full: bool = True, rel: str = "index.html") -> str:
    up = "../" * depth
    url = f"https://{DOMAIN}/" + ("" if rel == "index.html" else rel)
    title, desc = esc(meta["title"]), esc(meta.get("description", ""))
    img = f'https://{DOMAIN}/{meta["image"]}' if meta.get("image") else ""
    article = bool(meta.get("date"))
    ld = {"@context": "https://schema.org", "@type": "BlogPosting" if article else "WebPage",
          "headline" if article else "name": meta["title"], "description": meta.get("description", ""), "url": url}
    if img:
        ld["image"] = img
    if article:
        ld["datePublished"] = meta["date"]
    head = (f'<title>{title}</title>\n'
            f'<link rel="canonical" href="{url}">\n'
            f'<meta name="description" content="{desc}">\n'
            f'<meta property="og:type" content="{"article" if article else "website"}">\n'
            '<meta property="og:site_name" content="Only Vans">\n'
            f'<meta property="og:url" content="{url}">\n'
            f'<meta property="og:title" content="{title}">\n'
            f'<meta property="og:description" content="{desc}">\n'
            + (f'<meta property="og:image" content="{img}">\n' if img else "")
            + f'<meta name="twitter:card" content="{"summary_large_image" if img else "summary"}">\n'
            + '<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False).replace("</", "<\\/") + '</script>\n'
            + '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            f'<link rel="stylesheet" href="{FONTS}">\n'
            f'<link rel="stylesheet" href="{up}assets/style.css">\n'
            '<script>if("IntersectionObserver"in window&&!matchMedia("(prefers-reduced-motion: reduce)").matches){document.documentElement.classList.add("rv");setTimeout(function(){if(!window.__rv)document.documentElement.classList.remove("rv")},2500)}</script>\n'
            f'<script src="{up}assets/reveal.js" defer></script>\n'
            f'<link rel="icon" href="{up}assets/favicon.png" type="image/png">\n'
            '<meta name="theme-color" content="#f6f4ef">\n')
    over = " bar--over" if meta.get("hero") else ""
    nav = "".join(f'<a href="{href if href.startswith("http") else up + href}">{label}</a>' for _, href, label in NAV)
    page = (f'<header class="bar{over}"><a class="brand" href="{up}index.html"><img src="{up}assets/logo-192.png" alt="" width="67" height="67">Only <span>Vans</span></a>\n'
            f'<nav>{nav}</nav></header>\n'
            + ('' if over else '<div class="stripe" aria-hidden="true"></div>\n')
            + body.replace("{{up}}", up) +
            '\n<footer><span class="stripe" aria-hidden="true"></span>Lola (white) and Ted (grey), two VW campers that like to travel together. '
            f'Stories and photos from <a href="{IG}">@tedandlolasonlyvans</a>. Ian\'s astronomy pictures: <a href="https://uv101.uk">uv101.uk</a>. Site built by Claude.'
            f'<br>© {datetime.date.today().year} only-vans.uk. Photos are ours; please ask before reusing them.</footer>\n')
    if not full:
        return head + page
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + head + '</head>\n<body>\n' + page + '</body>\n</html>\n')


def index_page(posts: list[dict]) -> tuple[dict, str]:
    hero = next((p for p in posts if p["id"] == HERO[0]), posts[0])
    hm = hero["media"][HERO[1]] if hero["id"] == HERO[0] else hero["cover"]
    items = []
    for p in posts:
        where = f'{esc(p["place"])} · ' if p["place"] else ""
        items.append(
            f'<li><a href="adventures/{p["slug"]}.html">'
            f'<img src="{thumb(p["cover"])}" alt="" loading="lazy" width="{p["cover"]["w"]}" height="{p["cover"]["h"]}">'
            f'<span><time datetime="{p["when"]:%Y-%m-%d}">{where}{p["when_text"] or span(p["when"], p["end"])}</time>'
            f'<h3>{esc(p["title"])}</h3><p>{esc(plain(p["caption"]))}</p></span></a></li>')
    places = len({p["place"] for p in posts if p["place"]})
    # trips, not entries: back-to-back campsite stays (Kendal -> Moss Howe) are one trip
    trips, last_end = 0, None
    for c in sorted(json.load(open(os.path.join(ROOT, "data", "campsites.json"))), key=lambda c: c["date"]):
        if last_end is None or c["date"] > last_end:
            trips += 1
        last_end = max(last_end or "", c.get("end") or c["date"])
    # one map pin per spot; several adventures at the same spot share a pin
    # campsites (data/campsites.json) share a pin with any adventure at the same spot
    pins = {}
    for c in json.load(open(os.path.join(ROOT, "data", "campsites.json"))):
        if c.get("at"):
            pins.setdefault(tuple(c["at"]), {"camps": [], "posts": []})["camps"].append(c)
    for p in sorted(posts, key=lambda x: x["when"]):
        if p["at"]:
            pins.setdefault(tuple(p["at"]), {"camps": [], "posts": []})["posts"].append(p)
    rpath = os.path.join(ROOT, "data", "routes.json")
    rj = json.load(open(rpath)) if SHOW_ROUTES and os.path.exists(rpath) else {"connector": [], "routes": []}
    routes = rj["routes"]
    route_data = ([{"label": "", "segments": [rj["connector"]]}] if rj["connector"] else []) + [{"label": f'Lola\'s route · {r["campsite"]} · {span(datetime.date.fromisoformat(r["date"]), datetime.date.fromisoformat(r["end"]) if r.get("end") else None)}',
                   "segments": r["segments"]} for r in routes]
    pin_data = []
    for k, v in pins.items():
        head = "".join(f'<b>{esc(c["name"])}</b><br><span>Campsite · {span(datetime.date.fromisoformat(c["date"]), datetime.date.fromisoformat(c["end"]) if c.get("end") else None)}</span><br>'
                       for c in v["camps"]) or f'<b>{esc(v["posts"][0]["place"])}</b><br>'
        pin_data.append({"at": list(k), "camp": bool(v["camps"]) and not v["posts"], "html": head + "<br>".join(
            f'<a href="adventures/{q["slug"]}.html">{esc(q["title"])}</a> <span>{span(q["when"], q["end"])}</span>' for q in v["posts"])})
    body = f'''<section class="hero">
  <img src="{hm["src"]}" alt="Lola, the white VW camper with a teal pop-top, and Ted, the grey one, roofs up on a sunny campsite" width="{hm["w"]}" height="{hm["h"]}">
  <div class="hero__text">
    <p class="eyebrow">Two vans · four friends · one road</p>
    <h1>Ted &amp; Lola's adventures</h1>
    <p>Ted &amp; Lola love an adventure! Anywhere, any weather, just as long as they are travelling together.</p>
    <p class="hero__cta"><a href="#adventures">Read the adventures</a><a href="{IG}">Follow on Instagram</a></p>
  </div>
  <p class="hero__credit">{esc(hero["place"] or "On the road")} · {hero["when"]:%b %Y}</p>
</section>
<main class="page">
  <p class="lede">Lola, the white van with the teal roof, is Annette's, and Ian is her designated driver. Ted, the grey one, is JC's, and Ceri is his passenger princess. More often than not the two vans set off together. This is where their trips are written up, straight from the Instagram feed.</p>
  <dl class="log">
    <div><dt>Vans</dt><dd>Ted &amp; Lola</dd></div>
    <div><dt>Crew</dt><dd>Annette, Ian, JC, Ceri</dd></div>
    <div><dt>Trips</dt><dd>{trips}</dd></div>
    <div><dt>Places</dt><dd>{places}</dd></div>
  </dl>
  <h2 id="map">Where we've been</h2>
  <link rel="stylesheet" href="{LEAFLET}leaflet.min.css">
  <div class="map" id="ov-map" role="region" aria-label="Map of everywhere Ted and Lola have been"></div>
  {'<p class="map-note">Lines are Lola' + "'" + 's actual routes from her GPS tracker. They start and finish on the main road, not at our front door.</p>' if route_data else ""}
  <script type="application/json" id="ov-routes">{json.dumps(route_data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")}</script>
  <script type="application/json" id="ov-pins">{json.dumps(pin_data, ensure_ascii=False).replace("</", "<\\/")}</script>
  <script src="{LEAFLET}leaflet.min.js"></script>
  <script>
  (function () {{
    if (!window.L) return;
    var pins = JSON.parse(document.getElementById("ov-pins").textContent);
    var map = L.map("ov-map", {{ scrollWheelZoom: false }});
    L.tileLayer("https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
      maxZoom: 18, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }}).addTo(map);
    var teal = getComputedStyle(document.documentElement).getPropertyValue("--teal-bright").trim() || "#36b3aa";
    var routes = JSON.parse(document.getElementById("ov-routes").textContent);
    routes.forEach(function (r) {{
      L.polyline(r.segments, {{ color: teal, weight: 3.5, opacity: 0.85, lineJoin: "round" }})
        .bindTooltip(r.label || "Lola's route", {{ sticky: true }}).addTo(map);
    }});
    pins.forEach(function (p) {{
      L.circleMarker(p.at, p.camp ? {{ radius: 8, color: teal, weight: 3, fillColor: "#ffffff", fillOpacity: 1 }}
                                  : {{ radius: 9, color: "#ffffff", weight: 2, fillColor: teal, fillOpacity: 1 }})
        .bindPopup(p.html).addTo(map);
    }});
    map.fitBounds(pins.map(function (p) {{ return p.at; }}), {{ padding: [30, 30] }});
  }})();
  </script>
  <h2 id="adventures">Adventures</h2>
  <ul class="trips">
    {chr(10).join("    " + i for i in items).lstrip()}
  </ul>
</main>'''
    meta = {"title": "Ted & Lola's Adventures",
            "description": "Two VW camper vans, Ted and Lola, and the trips they take together around the UK.",
            "image": hm["src"], "hero": True}
    return meta, body


def post_page(p: dict, newer: dict | None, older: dict | None) -> tuple[dict, str]:
    figs = "\n".join(
        f'    <a href="{{{{up}}}}{m["src"]}"><img src="{{{{up}}}}{thumb(m)}" alt="Photo {i + 1} from {esc(p["title"])}" loading="lazy" width="{m["w"]}" height="{m["h"]}"></a>'
        for i, m in enumerate(p["media"]))
    c = p["cover"]
    nav = ""
    if newer or older:
        nav = ('<nav class="pager">'
               + (f'<a href="{older["slug"]}.html"><small>Older</small>{esc(older["title"])}</a>' if older else "<span></span>")
               + (f'<a class="next" href="{newer["slug"]}.html"><small>Newer</small>{esc(newer["title"])}</a>' if newer else "")
               + '</nav>')
    body = f'''<main class="page">
  <p class="eyebrow">{esc(p["place"]) + " · " if p["place"] else ""}{p["when_text"] or (span(p["when"], p["end"], True) if p["dated"] else "Posted " + span(p["when"], None, True))}</p>
  <h1>{esc(p["title"])}</h1>
  <figure class="wide"><img src="{{{{up}}}}{c["src"]}" alt="" width="{c["w"]}" height="{c["h"]}"></figure>
  <dl class="log">
    <div><dt>Where</dt><dd>{esc(p["place"] or "On the road")}</dd></div>
    <div><dt>Vans</dt><dd>{esc(p["vans"])}</dd></div>
    <div><dt>{"When" if p["dated"] else "Posted"}</dt><dd>{p["when_text"] or span(p["when"], p["end"])}</dd></div>
    <div><dt>Photos</dt><dd>{len(p["media"])}</dd></div>
  </dl>
  {caption_html(p["caption"])}
  {caption_html(p["notes"])}
  {'<div class="photos">' + chr(10) + figs + chr(10) + '  </div>' if len(p["media"]) > 1 else ""}
  {f'<p><a href="{p["permalink"]}">See this post on Instagram</a></p>' if p["permalink"] else ""}
  <script src="{{{{up}}}}assets/lightbox.js" defer></script>
  {nav}
</main>'''
    meta = {"title": f'{p["title"]} · Only Vans', "description": plain(p["caption"], 155),
            "image": c["src"], "date": "" if p["when_text"] else f'{p["when"]:%Y-%m-%d}'}
    return meta, body


def build(preview: bool = False) -> str:
    out = os.path.join(SITE, "preview" if preview else "public")
    os.makedirs(out, exist_ok=True)
    for sub in ("assets", "img"):
        shutil.copytree(os.path.join(SITE, sub), os.path.join(out, sub), dirs_exist_ok=True)
    posts = load_posts()
    thumbs(posts, out)
    pages = [("index.html", None, *index_page(posts))]
    for i, p in enumerate(posts):
        pages.append((f'adventures/{p["slug"]}.html', None if p["when_text"] else p["when"].isoformat(),
                      *post_page(p, posts[i - 1] if i else None, posts[i + 1] if i + 1 < len(posts) else None)))
    for rel, _, meta, body in pages:
        full = not (preview and rel == "index.html")  # the Artifact wraps its own entry page
        dst = os.path.join(out, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "w").write(layout(body, meta, rel.count("/"), full, rel))
    if not preview:
        open(os.path.join(out, "CNAME"), "w").write(DOMAIN + "\n")
        today = datetime.date.today().isoformat()
        urls = "".join(f"  <url><loc>https://{DOMAIN}/{'' if r == 'index.html' else r}</loc><lastmod>{d or today}</lastmod></url>\n"
                       for r, d, *_ in pages)
        open(os.path.join(out, "sitemap.xml"), "w").write(
            '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + urls + '</urlset>\n')
        open(os.path.join(out, "robots.txt"), "w").write(f"User-agent: *\nAllow: /\n\nSitemap: https://{DOMAIN}/sitemap.xml\n")
        open(os.path.join(out, ".nojekyll"), "w").write("")
        # Google Search Console ownership check (URL-prefix property) — must stay served
        open(os.path.join(out, "google2ee47459a7d5a626.html"), "w").write("google-site-verification: google2ee47459a7d5a626.html")
    return out


if __name__ == "__main__":
    print(build("--preview" in sys.argv))
