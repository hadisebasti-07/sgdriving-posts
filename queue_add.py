#!/usr/bin/env python3
"""
Queue finished posts from ../posts/ for automatic publishing.

Usage:
  python3 queue_add.py ../posts/day01_electrical_study_notes [more dirs…]
  python3 queue_add.py --update ../posts/day0[1-7]_*   # re-copy slides/caption after edits

For each post dir it reads caption.md (the "Post on:" date, an optional
"**Time:** HH:MM" (SGT, else 19:30), the caption in the first ``` block, the
numbered alt-text list), converts slides/slide-NN.png to JPEG (the API refuses
PNG) and writes queue/<YYYY-MM-DD>-<dir name>/ with caption.txt and post.json
(approved: true). A dir with reel.mp4 instead of slides queues a Reel; an
optional "**Cover:** N s" picks its cover frame. Folders sort by date, so items for
the same day post in name order. Posted items are never touched.
"""

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

QUEUE = Path(__file__).parent / "queue"
MAX_CAPTION, MAX_TAGS, MAX_ALT = 2200, 30, 1000


def parse(md: str, name: str) -> tuple[str, str, list[str], dict]:
    m = re.search(r"\*\*Post on:\*\*\s*\w+\s+(\d{1,2} \w{3} \d{4})", md)
    if not m:
        sys.exit(f"{name}: no 'Post on:' date in caption.md")
    post_on = datetime.strptime(m.group(1), "%d %b %Y").date().isoformat()
    c = re.search(r"```\n(.*?)\n```", md, re.S)
    if not c:
        sys.exit(f"{name}: no ``` caption block in caption.md")
    caption = c.group(1).strip()
    alt_sec = md.split("## Alt text", 1)[1] if "## Alt text" in md else ""
    alts = re.findall(r"^\d+\.\s+(.+)$", alt_sec, re.M)
    extra = {}
    if t := re.search(r"\*\*Time:\*\*\s*(\d{1,2}:\d{2})", md):
        extra["post_time"] = f"{int(t.group(1).split(':')[0]):02d}:{t.group(1).split(':')[1]}"
    if c := re.search(r"\*\*Cover:\*\*\s*([\d.]+)\s*s", md):
        extra["thumb_offset_ms"] = round(float(c.group(1)) * 1000)
    return post_on, caption, alts, extra


def add(src: Path, update: bool) -> None:
    name = src.name
    post_on, caption, alts, extra = parse((src / "caption.md").read_text(), name)
    reel = src / "reel.mp4"
    slides = [reel] if reel.exists() else sorted((src / "slides").glob("slide-*.png"))
    problems = []
    if not slides:
        problems.append("no slides/slide-*.png or reel.mp4")
    if len(slides) > 10:
        problems.append(f"{len(slides)} slides, max is 10")
    if len(caption) > MAX_CAPTION:
        problems.append(f"caption is {len(caption)} chars, max {MAX_CAPTION}")
    if caption.count("#") > MAX_TAGS:
        problems.append(f"{caption.count('#')} hashtags, max {MAX_TAGS}")
    if not reel.exists() and len(alts) != len(slides):
        problems.append(f"{len(alts)} alt texts for {len(slides)} slides")
    if any(len(a) > MAX_ALT for a in alts):
        problems.append(f"an alt text is over {MAX_ALT} chars")
    if problems:
        sys.exit(f"{name}: " + "; ".join(problems))

    dest = QUEUE / f"{post_on}-{name}"
    others = [d for d in QUEUE.glob(f"*-{name}") if d != dest]
    if others:
        sys.exit(f"{name}: already queued as {others[0].name} (date changed? remove it first)")
    if dest.exists():
        old = json.loads((dest / "post.json").read_text())
        if old.get("posted_at"):
            print(f"skip   {dest.name}: already posted")
            return
        if not update:
            sys.exit(f"{name}: already queued; use --update to refresh it")
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    if reel.exists():
        shutil.copy(reel, dest / "01.mp4")
        slides = []
    for i, png in enumerate(slides, 1):
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "92",
                        str(png), "--out", str(dest / f"{i:02d}.jpg")],
                       check=True, capture_output=True)
    (dest / "caption.txt").write_text(caption + "\n")
    meta = {"source": f"posts/{name}", "post_on": post_on, **extra, "approved": True}
    if alts and not reel.exists():
        meta["alt_text"] = alts
    (dest / "post.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    print(f"queued {dest.name}: " + ("reel" if reel.exists() else f"{len(slides)} slides")
          + f" · {post_on} {extra.get('post_time', '19:30')}")


if __name__ == "__main__":
    a = sys.argv[1:]
    update = "--update" in a
    dirs = [Path(x) for x in a if x != "--update"]
    if not dirs:
        sys.exit(__doc__)
    for d in dirs:
        add(d.resolve(), update)
