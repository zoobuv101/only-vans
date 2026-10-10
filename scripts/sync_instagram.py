#!/usr/bin/env python3
"""Pull every @tedandlolasonlyvans post via the Instagram API into data/posts.json + site/img/ig/.

Instagram's media_url links expire, so each photo (or a video's cover frame) is downloaded once,
resized for the web (longest edge MAX_PX, metadata stripped) and kept in the repo; files already
present are not fetched again. Needs IG_TOKEN in the env and Pillow.
Hand-written titles/dates/places live in data/overrides.json and are never touched by this script.
"""
import io, json, os, sys, urllib.error, urllib.parse, urllib.request
from PIL import Image, ImageOps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "site", "img", "ig")
OUT = os.path.join(ROOT, "data", "posts.json")
MAX_PX = 1800
FIELDS = ("id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,"
          "children{id,media_type,media_url,thumbnail_url}")


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300].replace(os.environ["IG_TOKEN"], "<token>")
        sys.exit(f"ERROR: Instagram API HTTP {e.code}: {body}")


def fetch(url, dst):
    if os.path.exists(dst):
        return
    with urllib.request.urlopen(url, timeout=120) as r:
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(r.read()))).convert("RGB")
    im.thumbnail((MAX_PX, MAX_PX))
    tmp = dst + ".part"
    im.save(tmp, "JPEG", quality=80, optimize=True, progressive=True)  # no exif kept
    os.replace(tmp, dst)


def main():
    token = os.environ.get("IG_TOKEN") or sys.exit("ERROR: IG_TOKEN not set")
    url = "https://graph.instagram.com/me/media?" + urllib.parse.urlencode(
        {"fields": FIELDS, "limit": 50, "access_token": token})
    raw = []
    while url:
        page = get(url)
        raw += page.get("data", [])
        url = page.get("paging", {}).get("next")

    os.makedirs(IMG, exist_ok=True)
    posts = []
    for p in raw:
        items = p.get("children", {}).get("data") or [p]
        media = []
        for i, m in enumerate(items):
            video = m["media_type"] == "VIDEO"
            src = m.get("thumbnail_url") if video else m.get("media_url")
            if not src:
                continue
            name = f"{p['id']}-{i:02d}.jpg"
            fetch(src, os.path.join(IMG, name))
            w, h = Image.open(os.path.join(IMG, name)).size
            media.append({"src": f"img/ig/{name}", "w": w, "h": h, "video": video})
        posts.append({"id": p["id"], "timestamp": p["timestamp"], "permalink": p["permalink"],
                      "type": p["media_type"], "caption": p.get("caption", ""), "media": media})
    posts.sort(key=lambda x: x["timestamp"], reverse=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(posts, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"{len(posts)} posts, {sum(len(p['media']) for p in posts)} images -> {os.path.relpath(OUT, ROOT)}")


if __name__ == "__main__":
    main()
