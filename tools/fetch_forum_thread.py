#!/usr/bin/env python3
"""Archive a RomRaider forum thread locally, every post, as plain text.

Most of what is known about this TCU lives in two forum threads. Working from a
partial copy has already cost time - the shift-table naming discussion turned out
to be in a thread this project had only one page of - and forum posts are not
permanent. Keep the whole thing on disk.

The board rejects the default urllib user agent, so a browser one is sent. Pages
are cached under the output directory, so a re-run only fetches what is missing
and the board is not hammered.

    python tools/fetch_forum_thread.py 13725
    python tools/fetch_forum_thread.py 20850 --out docs/

Output is one text file per thread: docs/forum_thread_<id>.txt, with each post
labelled by author, date and post number.

The posts are other people's writing. They are archived here for reference and
credited in the project README; nothing in them is claimed as this project's work.
"""

import argparse
import html
import os
import re
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

BASE = "https://www.romraider.com/forum/viewtopic.php?f=40&t={tid}&start={start}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def fetch(url, tries=3):
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        })
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as e:
            if attempt == tries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    return ""


DIV_TAG = re.compile(r"<(/?)div\b", re.I)


def extract_div(segment, opener):
    """The full contents of the div `opener` matched, nesting included.

    A non-greedy match to the first </div> looks right and is not: a post that
    quotes another contains a nested div, so the match ends at the quote's own
    closing tag and everything the author actually wrote is discarded. That
    silently emptied 122 of the 391 posts in the topic 13725 archive - every
    post replying to someone, which is most of the technical argument.
    """
    start = opener.end()
    depth = 1
    for m in DIV_TAG.finditer(segment, start):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return segment[start:m.start()]
    return segment[start:]


def strip_tags(fragment):
    # Keep quote blocks legible: they carry a lot of the technical back-and-forth.
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"</(p|div|li|blockquote)>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    text = html.unescape(fragment)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def parse_posts(page):
    """Return [(author, date, body, id)] for one page.

    This board runs phpBB2, not phpBB3: posts are table rows anchored by
    <a name="p12345">, the author is a viewprofile link, and the text sits in a
    <div class="postbody">. A phpBB3 parser looking for id="p12345" finds nothing
    and reports an empty thread, which is exactly what happened first time.
    """
    posts = []
    chunks = re.split(r'<a\s+name="p(\d+)"', page)
    for i in range(1, len(chunks), 2):
        pid = chunks[i]
        seg = chunks[i + 1]

        # The author sits in <b class="postauthor"> immediately after the post
        # anchor. Matching the first viewprofile link instead - as this parser
        # originally did - finds the profile BUTTON in the previous post's footer,
        # whose visible text is &nbsp;, which is how an earlier archive of topic
        # 13725 ended up attributing most of the thread to nobody.
        author = re.search(r'<b class="postauthor">([^<]*)</b>', seg)
        if not author:
            author = re.search(
                r'memberlist\.php\?mode=viewprofile[^"]*"[^>]*>(?:<[^>]+>)*([^<]+)', seg)
        date = re.search(r'<b>Posted:</b>\s*([^<&]+)', seg)
        body = re.search(r'<div class="postbody">', seg, re.S)

        # Drop the quoted-reply chrome but keep the quoted text, since a lot of the
        # technical detail in this thread is inside quote blocks.
        text = strip_tags(extract_div(seg, body)) if body else ""
        posts.append((
            author.group(1).strip() if author else "unknown",
            date.group(1).strip() if date else "",
            text,
            pid,
        ))
    return posts


def total_posts(page):
    m = re.search(r"(\d+)\s+posts?\b", page)
    return int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tid", help="topic id, e.g. 13725")
    ap.add_argument("--out", default=os.path.join(REPO, "docs"))
    ap.add_argument("--per-page", type=int, default=15)
    ap.add_argument("--max-pages", type=int, default=60)
    args = ap.parse_args()

    seen = set()
    collected = []
    total = None

    for page in range(args.max_pages):
        start = page * args.per_page
        url = BASE.format(tid=args.tid, start=start)
        try:
            body = fetch(url)
        except Exception as e:
            print("  page %d failed: %s" % (page + 1, e))
            break

        if total is None:
            total = total_posts(body)
            if total:
                print("thread reports %d posts" % total)

        posts = parse_posts(body)
        fresh = [p for p in posts if p[3] not in seen]
        for p in fresh:
            seen.add(p[3])
        collected.extend(fresh)
        print("  page %2d  start=%-5d posts=%2d new=%2d  (total %d)"
              % (page + 1, start, len(posts), len(fresh), len(collected)))

        # Stop when a page adds nothing: either the end, or the board is ignoring
        # `start` and serving page one over and over.
        if not fresh:
            break
        if total and len(collected) >= total:
            break
        time.sleep(1.0)

    if not collected:
        print("\nNo posts parsed. The board may require a login for this topic, "
              "or the markup changed - check the saved HTML by hand.")
        return 1

    dest = os.path.join(args.out, "forum_thread_%s.txt" % args.tid)

    # Never silently shrink an existing archive. The copy of topic 20850 in this
    # repo is hand-curated - the CAN message tables were transcribed from an
    # attachment, not from the post body, which is only a few hundred characters -
    # so a scrape of that topic is much SMALLER than what is already on disk.
    # Overwriting it destroyed the useful content, once.
    if os.path.exists(dest):
        old = os.path.getsize(dest)
        if old > 4096 and old > 4 * sum(len(p[2]) for p in collected):
            alt = dest.replace(".txt", "_scraped.txt")
            print("\nREFUSING to overwrite %s: the existing file is %d bytes and the\n"
                  "scrape is much smaller, so it is probably hand-curated. Writing\n"
                  "%s instead - merge by hand if the scrape adds anything."
                  % (dest, old, alt))
            dest = alt

    with open(dest, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("RomRaider forum topic %s\n" % args.tid)
        fh.write("https://www.romraider.com/forum/viewtopic.php?f=40&t=%s\n\n" % args.tid)
        fh.write("Archived for reference. These are other people's posts; they are\n"
                 "credited in the project README and nothing here is my work.\n")
        fh.write("=" * 78 + "\n\n")
        for n, (author, date, text, pid) in enumerate(collected, 1):
            fh.write("=== post %d | %s | %s | #p%s ===\n" % (n, author, date, pid))
            fh.write(text + "\n\n")
    print("\nwrote %s (%d posts)" % (dest, len(collected)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
