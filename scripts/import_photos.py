#!/usr/bin/env python3
"""Convert chosen photos (e.g. from a Google Takeout export in data/raw/) into site/img/gp/.

    python3 scripts/import_photos.py data/raw/Takeout/Google\\ Photos/Album/IMG_1234.HEIC ...

Each file is rotated upright, resized (longest edge 1800px) and saved as JPEG with ALL metadata
stripped — Takeout originals carry GPS. Originals stay in data/raw/ (gitignored).
Reference the output from data/overrides.json ("extra") or data/manual.json ("photos").
"""
import os, sys
from PIL import Image, ImageOps
import pillow_heif

pillow_heif.register_heif_opener()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "site", "img", "gp")

os.makedirs(OUT, exist_ok=True)
for src in sys.argv[1:]:
    name = os.path.splitext(os.path.basename(src))[0] + ".jpg"
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    im.thumbnail((1800, 1800))
    im.save(os.path.join(OUT, name), "JPEG", quality=80, optimize=True, progressive=True)
    print(f"img/gp/{name}  {im.size[0]}x{im.size[1]}")
