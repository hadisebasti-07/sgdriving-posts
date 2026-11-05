#!/usr/bin/env python3
"""
Publish dated posts to Instagram (Instagram API with Instagram Login).

Usage:
  python3 publish.py next              # publish every approved item dated today whose time (SGT) has come, in folder order
  python3 publish.py next --dry-run    # show what would be posted, call nothing
  python3 publish.py next --window     # same as next, but only items due in the last 3 hours (backup schedule)
  python3 publish.py next --catch-up   # also publish approved items from earlier days that were missed
  python3 publish.py check <item>      # create upload containers, never publish
  python3 publish.py refresh-token     # print a refreshed 60-day token
  python3 publish.py status            # list the queue

Env: IG_ACCESS_TOKEN, MEDIA_BASE (public URL of this repo's Pages site).
Each queue/<item>/ holds 01..NN media (.jpg/.mp4), caption.txt, post.json
({"post_on": "YYYY-MM-DD", "post_time": "HH:MM" (SGT, default 19:30), "approved": true,
  "alt_text": [...]}; a single .mp4 posts as a Reel, with optional "thumb_offset_ms" for its cover).
An item is posted once: the workflow commits posted_at back, so reruns skip it.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

GRAPH = "https://graph.instagram.com/v21.0"
QUEUE = Path(__file__).parent / "queue"
MEDIA_EXT = {".jpg", ".jpeg", ".mp4", ".mov"}
SGT = timezone(timedelta(hours=8))
DEFAULT_TIME = "19:30"  # SGT, when an item has no post_time
WINDOW = timedelta(hours=3)  # a backup run posts an item only this long after its time


def token() -> str:
    t = os.getenv("IG_ACCESS_TOKEN")
    if not t:
        sys.exit("IG_ACCESS_TOKEN is not set")
    return t


def api(method: str, path: str, **params) -> dict:
    params["access_token"] = token()
    data = urllib.parse.urlencode(params).encode()
    url = f"{GRAPH}/{path}"
    if method == "GET":
        req = urllib.request.Request(f"{url}?{data.decode()}")
    else:
        req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path}: {e.read().decode()}") from None


# ── Queue ─────────────────────────────────────────────────────────────────────

def items() -> list[Path]:
    return sorted(p for p in QUEUE.iterdir() if (p / "post.json").exists())


def meta(item: Path) -> dict:
    return json.loads((item / "post.json").read_text())


def post_on(item: Path) -> date:
    return date.fromisoformat(meta(item)["post_on"])


def due_at(item: Path) -> datetime:
    t = datetime.strptime(meta(item).get("post_time", DEFAULT_TIME), "%H:%M").time()
    return datetime.combine(post_on(item), t, tzinfo=SGT)


def media_files(item: Path) -> list[Path]:
    return sorted(f for f in item.iterdir() if f.suffix.lower() in MEDIA_EXT)


def media_url(item: Path, f: Path) -> str:
    base = os.getenv("MEDIA_BASE")
    if not base:
        sys.exit("MEDIA_BASE is not set")
    return f"{base.rstrip('/')}/queue/{item.name}/{f.name}"


# ── Containers ────────────────────────────────────────────────────────────────

def wait_ready(cid: str, label: str, timeout: int = 600) -> None:
    start = time.time()
    while True:
        s = api("GET", cid, fields="status_code,status")
        code = s.get("status_code")
        if code in ("FINISHED", "PUBLISHED"):
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"{label}: {code} {s.get('status')}")
        if time.time() - start > timeout:
            raise RuntimeError(f"{label}: still {code} after {timeout}s")
        time.sleep(5)


def container(item: Path, f: Path, alt: str, carousel: bool, caption: str = "") -> str:
    url = media_url(item, f)
    video = f.suffix.lower() in (".mp4", ".mov")
    p = {"is_carousel_item": "true"} if carousel else {"caption": caption}
    if video:
        p.update(media_type="VIDEO" if carousel else "REELS", video_url=url)
        if not carousel:
            p.update(share_to_feed="true")
            if "thumb_offset_ms" in meta(item):
                p.update(thumb_offset=str(meta(item)["thumb_offset_ms"]))
    else:
        p.update(image_url=url)
        if alt:
            p.update(alt_text=alt)  # images only; set per child, not on the carousel
    return api("POST", "me/media", **p)["id"]


def build(item: Path) -> str:
    """Create all containers for an item and return the top-level container id."""
    files = media_files(item)
    caption = (item / "caption.txt").read_text().strip()
    alts = meta(item).get("alt_text", [])
    alts += [""] * (len(files) - len(alts))
    if not files:
        raise RuntimeError(f"{item.name}: no media")
    if len(files) > 10:
        raise RuntimeError(f"{item.name}: {len(files)} files, carousel max is 10")
    if len(files) == 1:
        top = container(item, files[0], alts[0], carousel=False, caption=caption)
        print(f"  {files[0].name} → container {top}")
        wait_ready(top, files[0].name)
        return top
    kids = []
    for f, alt in zip(files, alts):
        cid = container(item, f, alt, carousel=True)
        print(f"  {f.name} → container {cid}")
        kids.append((f.name, cid))
    for name, cid in kids:
        wait_ready(cid, name)
        print(f"  {name} ready")
    top = api("POST", "me/media", media_type="CAROUSEL",
              children=",".join(c for _, c in kids), caption=caption)["id"]
    wait_ready(top, "carousel")
    return top


def publish(item: Path) -> None:
    top = build(item)
    post_id = api("POST", "me/media_publish", creation_id=top)["id"]
    link = api("GET", post_id, fields="permalink").get("permalink", "")
    m = meta(item)
    m.update(posted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
             media_id=post_id, permalink=link)
    (item / "post.json").write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n")
    print(f"Posted: {link}")


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_status() -> None:
    today = datetime.now(SGT).date()
    for item in items():
        m = meta(item)
        if m.get("posted_at"):
            state = "posted " + m["posted_at"][:10]
        elif not m.get("approved"):
            state = "held (approved: false)"
        elif post_on(item) < today:
            state = "MISSED"
        else:
            state = "due"
        print(f"{m['post_on']} {m.get('post_time', DEFAULT_TIME)}  {item.name:50} "
              f"{len(media_files(item)):2} files  {state}")


def cmd_next(dry: bool, window: bool, catch_up: bool) -> None:
    now = datetime.now(SGT)
    pending = [i for i in items() if meta(i).get("approved") and not meta(i).get("posted_at")]
    # GitHub's backup cron runs late, so it only posts items whose time passed in the last 3 h
    today = [i for i in pending if post_on(i) == now.date() and due_at(i) <= now
             and not (window and now - due_at(i) > WINDOW)]
    missed = [i for i in pending if post_on(i) < now.date()]
    if missed and not catch_up:
        # posting today's item would put it ahead of the missed ones; hold everything.
        # non-zero exit makes GitHub email the repo owner
        sys.exit("Missed and still unposted: " + ", ".join(i.name for i in missed) +
                 ". Nothing was posted. Run the workflow with catch_up ticked to post "
                 "them, then today's, in date order.")
    todo = missed + today
    if not todo:
        print(f"Nothing due at {now:%Y-%m-%d %H:%M} SGT, nothing to post.")
    for item in todo:
        print(f"Next: {item.name}")
        for f in media_files(item):
            print(f"  {f.name}  {media_url(item, f) if os.getenv('MEDIA_BASE') else ''}")
        if not dry:
            publish(item)
    if dry:
        print("(dry run, nothing posted)")
    if not today and not missed and not any(due_at(i) > now for i in pending):
        sys.exit("The queue is empty: nothing approved for today or later.")


def cmd_check(name: str) -> None:
    item = QUEUE / name
    top = build(item)
    print(f"All containers accepted ({top}). Nothing was published; "
          "unpublished containers expire after 24 h.")


def cmd_refresh() -> None:
    q = urllib.parse.urlencode({"grant_type": "ig_refresh_token",
                                "access_token": token()})
    with urllib.request.urlopen(f"https://graph.instagram.com/refresh_access_token?{q}") as r:
        d = json.load(r)
    print(d["access_token"])
    print(f"expires in {d['expires_in'] // 86400} days", file=sys.stderr)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "next":
        cmd_next("--dry-run" in a, "--window" in a, "--catch-up" in a)
    elif a[0] == "check" and len(a) > 1:
        cmd_check(a[1])
    elif a[0] == "refresh-token":
        cmd_refresh()
    elif a[0] == "status":
        cmd_status()
    else:
        sys.exit(__doc__)
