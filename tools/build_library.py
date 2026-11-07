#!/usr/bin/env python3
"""
Astra library builder
=====================
Splits a book / lecture PDF into small PDFs and registers them in
library/map.json, the "map" Astra reads to decide which file to open.

Basic use
    python tools/build_library.py "Gray's Anatomy.pdf" --title "Gray's Anatomy" --id grays

Useful options
    --ranges "1-2:Overview;3-6:Hip bone"   split exactly where you say (title optional)
    --max-pages 8                          largest chunk when splitting automatically
    --page-offset 14                       printed page = PDF page - 14 (pages <= 0 are skipped)
    --summaries summaries.json             hand-written / pre-generated summaries (see below)
    --summarize gemini --key YOUR_KEY      let Gemini write the summaries
    --dry-run                              show the plan, write nothing

Splitting order: --ranges, else the PDF's own bookmarks (chapters), else fixed
--max-pages blocks. Re-running with the same --id replaces that book.

summaries.json format (keys are "start-end" book pages, or the chunk id):
    { "_book": "One-line description of the whole book",
      "3-6": {"title": "Hip bone", "summary": "...", "keywords": ["ilium", "pubis"]} }
"""
import argparse, json, os, re, shutil, sys, time, urllib.request, urllib.error
from collections import Counter
from datetime import datetime, timezone

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    sys.exit("pypdf is required:  pip install pypdf")

STOP = set("""a about above after again all also an and any are as at be because been before being below between both but by can
could did do does doing down during each few for from further had has have having he her here hers him his how i if in into is it
its itself just me more most my no nor not now of off on once only or other our out over own same she should so some such than that
the their them then there these they this those through to too under until up very was we were what when where which while who whom
why will with would you your yours may must shall one two three four five six used use using called form formed see
""".split())


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "book"


def page_text(reader, i):
    try:
        return (reader.pages[i].extract_text() or "").strip()
    except Exception:
        return ""


def clean(t):
    return re.sub(r"\s+", " ", t).strip()


def parse_ranges(spec, total):
    out = []
    for part in [p for p in spec.split(";") if p.strip()]:
        rng, _, title = part.partition(":")
        m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", rng)
        if not m:
            sys.exit(f"Bad range: {part!r}")
        a = int(m.group(1)); b = int(m.group(2) or a)
        if not (1 <= a <= b <= total):
            sys.exit(f"Range {a}-{b} is outside the PDF (1-{total})")
        out.append((a, b, title.strip()))
    return out


def outline_ranges(reader, total):
    """Top-level bookmarks -> (start, end, title) in PDF pages (1-based)."""
    try:
        items = [o for o in reader.outline if not isinstance(o, list)]
    except Exception:
        return []
    starts = []
    for o in items:
        try:
            p = reader.get_destination_page_number(o) + 1
            starts.append((p, str(o.title).strip()))
        except Exception:
            pass
    starts = sorted(set(starts))
    if len(starts) < 3:
        return []
    out = []
    for k, (p, t) in enumerate(starts):
        end = (starts[k + 1][0] - 1) if k + 1 < len(starts) else total
        if end >= p:
            out.append((p, end, t))
    if out and out[0][0] > 1:
        out.insert(0, (1, out[0][0] - 1, "Front matter"))
    return out


def fixed_ranges(total, size):
    return [(a, min(a + size - 1, total), "") for a in range(1, total + 1, size)]


def enforce_max(ranges, max_pages):
    out = []
    for a, b, t in ranges:
        n = b - a + 1
        if n <= max_pages:
            out.append((a, b, t)); continue
        parts = -(-n // max_pages)
        size = -(-n // parts)
        for k in range(parts):
            s = a + k * size; e = min(s + size - 1, b)
            out.append((s, e, f"{t} (part {k + 1})" if t else ""))
    return out


def auto_title(text):
    for line in text.splitlines():
        line = clean(line)
        if 3 <= len(line) <= 90 and not re.fullmatch(r"[\d\W]+", line):
            return line
    return ""


def auto_keywords(text, n=12):
    words = re.findall(r"[^\W\d_]{4,}", text.lower())
    c = Counter(w for w in words if w not in STOP)
    return [w for w, _ in c.most_common(n)]


def gemini_summary(text, key, model, book_title):
    prompt = (
        f"You are indexing a study source ('{book_title}') so a retrieval system knows what this file contains.\n"
        "Return JSON only: {\"title\": short topic title, \"summary\": 40-70 words listing the specific topics, "
        "structures, terms, definitions, classifications and conclusions covered, \"keywords\": 8-14 distinctive "
        "search terms (include synonyms and abbreviations a student might use)}.\n\nTEXT:\n" + text[:24000]
    )
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, body, {"Content-Type": "application/json", "x-goog-api-key": key})
            with urllib.request.urlopen(req, timeout=90) as r:
                data = json.load(r)
            raw = data["candidates"][0]["content"]["parts"][0]["text"]
            raw = re.sub(r"^```(?:json)?|```$", "", raw.strip()).strip()
            return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503):
                time.sleep(4 * (attempt + 1)); continue
            print(f"   Gemini error {e.code}: {e.read()[:200]!r}")
            return None
        except Exception as e:
            print(f"   Gemini failed: {e}")
            time.sleep(2)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("--title"); ap.add_argument("--id"); ap.add_argument("--author", default="")
    ap.add_argument("--subject", default="")
    ap.add_argument("--ranges"); ap.add_argument("--max-pages", type=int, default=8)
    ap.add_argument("--page-offset", type=int, default=0)
    ap.add_argument("--summaries"); ap.add_argument("--summarize", choices=["gemini"]); ap.add_argument("--key")
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "library"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    reader = PdfReader(a.pdf)
    total = len(reader.pages)
    title = a.title or (reader.metadata.title if reader.metadata and reader.metadata.title else None) \
        or os.path.splitext(os.path.basename(a.pdf))[0].replace("_", " ")
    book_id = a.id or slugify(title)
    off = a.page_offset

    if a.ranges:
        ranges = parse_ranges(a.ranges, total); how = "your --ranges"
    else:
        ranges = outline_ranges(reader, total)
        how = "the PDF bookmarks"
        if not ranges:
            ranges = fixed_ranges(total, a.max_pages); how = f"fixed blocks of {a.max_pages} pages"
        ranges = enforce_max(ranges, a.max_pages)

    # drop front matter that has no printed page number
    ranges = [(max(s, off + 1), e, t) for s, e, t in ranges if e > off]

    print(f"{title}: {total} PDF pages -> {len(ranges)} files (split by {how})")
    summaries = {}
    if a.summaries:
        with open(a.summaries, encoding="utf-8") as f:
            summaries = json.load(f)
    if a.summarize == "gemini" and not a.key:
        sys.exit("--summarize gemini needs --key")

    chunks = []
    for n, (s, e, t) in enumerate(ranges, 1):
        bs, be = s - off, e - off
        cid = f"{book_id}__c{n:03d}"
        text = "\n".join(f"[page {p - off}]\n{page_text(reader, p - 1)}" for p in range(s, e + 1))
        body = re.sub(r"\[page \d+\]\n", "", text)
        meta = summaries.get(cid) or summaries.get(f"{bs}-{be}") or {}
        src = "provided" if meta else "auto-extract"
        if not meta and a.summarize == "gemini" and len(body.strip()) > 40 and not a.dry_run:
            print(f"   summarising pages {bs}-{be} ...")
            meta = gemini_summary(text, a.key, a.model, title) or {}
            src = "gemini" if meta else "auto-extract"
            time.sleep(1.2)
        ctitle = meta.get("title") or t or auto_title(body) or f"Pages {bs}-{be}"
        summary = meta.get("summary") or clean(body)[:420]
        kws = meta.get("keywords") or auto_keywords(body)
        fname = f"{n:03d}_p{bs:03d}-{be:03d}.pdf"
        chunks.append({
            "id": cid, "book": book_id, "file": f"chunks/{book_id}/{fname}",
            "startPage": bs, "endPage": be, "pdfStart": s, "pdfEnd": e,
            "title": ctitle, "summary": summary, "keywords": kws,
            "hasText": len(clean(body)) > 40, "summarySource": src,
        })
        print(f"  {fname}  pages {bs}-{be}  {ctitle[:60]}")

    if a.dry_run:
        print("dry run: nothing written"); return

    book_dir = os.path.join(a.out, "chunks", book_id)
    if os.path.isdir(book_dir):
        shutil.rmtree(book_dir)
    os.makedirs(book_dir, exist_ok=True)
    for c in chunks:
        w = PdfWriter()
        for p in range(c["pdfStart"], c["pdfEnd"] + 1):
            w.add_page(reader.pages[p - 1])
        with open(os.path.join(a.out, c["file"]), "wb") as f:
            w.write(f)
        del c["pdfStart"], c["pdfEnd"]

    map_path = os.path.join(a.out, "map.json")
    lib = {"version": 1, "books": [], "chunks": []}
    if os.path.exists(map_path):
        with open(map_path, encoding="utf-8") as f:
            lib = json.load(f)
    lib["books"] = [b for b in lib["books"] if b["id"] != book_id]
    lib["chunks"] = [c for c in lib["chunks"] if c["book"] != book_id]
    book_summary = summaries.get("_book", "")
    lib["books"].append({
        "id": book_id, "title": title, "author": a.author, "subject": a.subject,
        "totalPages": total - off, "summary": book_summary if isinstance(book_summary, str) else "",
    })
    lib["chunks"].extend(chunks)
    lib["generated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(lib, f, ensure_ascii=False, indent=1)
    weak = [c for c in chunks if c["summarySource"] == "auto-extract"]
    print(f"\nWrote {len(chunks)} files and updated {map_path}")
    if weak:
        print(f"Note: {len(weak)} summaries are auto-extracted (plain text excerpt). Retrieval works better with real "
              f"summaries: re-run with --summarize gemini --key ..., or pass --summaries.")


if __name__ == "__main__":
    main()
