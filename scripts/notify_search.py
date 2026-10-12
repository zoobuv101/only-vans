#!/usr/bin/env python3
"""Tell search engines which pages changed, after a deploy.

    python3 scripts/notify_search.py diff   # BEFORE deploy: built site/public vs the live site -> data/raw/changed.txt
    python3 scripts/notify_search.py send   # AFTER deploy: IndexNow ping + Google sitemap resubmit, if anything changed
    python3 scripts/notify_search.py send --all   # every URL in the sitemap (first run / after a big change)

IndexNow (Bing, Yandex, Seznam, Naver; DuckDuckGo uses Bing) — Google doesn't take part. The key isn't
a secret: it is served at /<key>.txt so the engines can check the ping came from this site.
Google: resubmits sitemap.xml through the Search Console API as service account
only-vans-sitemap@only-vans-511419.iam.gserviceaccount.com ("Full" user on the property). Its JSON key
comes from env GSC_SA_KEY (GitHub secret) or the file named in GSC_SA_FILE; needs google-auth + requests.
Failures print a warning but never fail the deploy.
"""
import json, os, re, sys, urllib.error, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "site", "public")
CHANGED = os.path.join(ROOT, "data", "raw", "changed.txt")
DOMAIN = "only-vans.uk"
INDEXNOW_KEY = "74d12d053bbb34955d8daa58745a2128"   # also written to /<key>.txt by site/build.py
UA = {"User-Agent": "only-vans.uk deploy"}


def sitemap_urls() -> list[str]:
    return re.findall(r"<loc>([^<]+)</loc>", open(os.path.join(PUBLIC, "sitemap.xml")).read())


def local_file(url: str) -> str:
    rel = url.split(DOMAIN + "/", 1)[1] or "index.html"
    return os.path.join(PUBLIC, rel)


def live(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        return None if e.code == 404 else b"?"
    except Exception:
        return b"?"


def diff() -> None:
    old = set(re.findall(r"<loc>([^<]+)</loc>", (live(f"https://{DOMAIN}/sitemap.xml") or b"").decode()))
    urls = sitemap_urls()
    changed = [u for u in urls if live(u) != open(local_file(u), "rb").read()]
    changed += sorted(old - set(urls))  # dropped pages: the engines recrawl and see the 404/noindex
    os.makedirs(os.path.dirname(CHANGED), exist_ok=True)
    open(CHANGED, "w").write("".join(u + "\n" for u in changed))
    print(f"{len(changed)} of {len(urls)} pages changed" + "".join(f"\n  {u}" for u in changed))


def send(all_urls: bool) -> None:
    urls = sitemap_urls() if all_urls else (open(CHANGED).read().split() if os.path.exists(CHANGED) else [])
    if not urls:
        print("Nothing changed: no IndexNow ping, no Google resubmit.")
        return
    google()
    body = json.dumps({"host": DOMAIN, "key": INDEXNOW_KEY, "keyLocation": f"https://{DOMAIN}/{INDEXNOW_KEY}.txt",
                       "urlList": urls}).encode()
    req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, method="POST",
                                 headers={**UA, "Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"IndexNow: HTTP {r.status} for {len(urls)} URL(s)")  # 200/202 = accepted
    except urllib.error.HTTPError as e:
        print(f"::warning::IndexNow refused: HTTP {e.code} {e.read()[:200]!r}")
    except Exception as e:
        print(f"::warning::IndexNow failed: {e}")


def google() -> None:
    raw = os.environ.get("GSC_SA_KEY") or (open(os.environ["GSC_SA_FILE"]).read() if os.environ.get("GSC_SA_FILE") else "")
    if not raw:
        print("Google: no GSC_SA_KEY, skipped.")
        return
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
        creds = service_account.Credentials.from_service_account_info(
            json.loads(raw), scopes=["https://www.googleapis.com/auth/webmasters"])
        site = urllib.parse.quote(f"https://{DOMAIN}/", safe="")
        feed = urllib.parse.quote(f"https://{DOMAIN}/sitemap.xml", safe="")
        r = AuthorizedSession(creds).put(f"https://www.googleapis.com/webmasters/v3/sites/{site}/sitemaps/{feed}", timeout=30)
        print(f"Google: sitemap resubmitted, HTTP {r.status_code}" if r.ok
              else f"::warning::Google sitemap resubmit refused: HTTP {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"::warning::Google sitemap resubmit failed: {e}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["diff"]:
        diff()
    elif sys.argv[1:2] == ["send"]:
        send("--all" in sys.argv)
    else:
        sys.exit(__doc__)
