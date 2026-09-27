#!/usr/bin/env python3
"""Sync study-guide artifacts into this repo.

Usage:
  PRIVACY_PATTERNS='regex' python3 tools/sync.py MANIFEST.json FETCHED_DIR [DOCS_EXPORT.json ...]

MANIFEST.json: [{"id": "<artifact id>", "path": "med-surg/x.html"},
                {"id": "<artifact id>", "path": "nclex/y.html", "docs": true, "title": "..."}]
FETCHED_DIR:   folder holding <id>/index.html for each html artifact (the Artifact tool's read output).
DOCS_EXPORT:   saved Claude Docs export results (JSON with data.bytes_b64), matched to manifest
               entries by the artifact id found in the file's frame.slug.

Writes cleaned pages into the repo, scans every page for the patterns in PRIVACY_PATTERNS,
and prints CHANGED/UNCHANGED per page. Exits 2 (and restores nothing written) if the scan hits.
"""
import json, os, re, shutil, subprocess, sys, base64, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACK = '<a class="back" href="../index.html">← All study guides</a>'


def clean_html(h):
    # "Not affiliated with <school> or Elsevier." -> "Not affiliated with Elsevier."
    return re.sub(r"Not affiliated with [^<.]{1,80}? or Elsevier\.", "Not affiliated with Elsevier.", h)


def pandoc_wrap(body_html, title):
    with tempfile.TemporaryDirectory() as t:
        src, back, out = (os.path.join(t, n) for n in ("in.html", "back.html", "out.html"))
        open(src, "w").write(body_html)
        open(back, "w").write(BACK)
        args = ["-f", "html", "-t", "html5", "-s", "--metadata", f"title={title}",
                "--css", "../assets/guide.css", "-V", "lang=en", "-B", back, "-o", out]
        if shutil.which("pandoc"):
            subprocess.run(["pandoc", src, *args], check=True)
        else:
            import pypandoc
            pypandoc.convert_file(src, "html5", format="html", outputfile=out, extra_args=args[4:-2])
        return open(out).read()


def docs_page(export_path, title):
    d = json.load(open(export_path))
    body = base64.b64decode(d["data"]["bytes_b64"]).decode("utf-8")
    # drop the date / @-mention line Claude Docs puts under the title
    body = re.sub(r'<p><time data-atom="date".*?</p>\n?', "", body, count=1, flags=re.S)
    body = re.sub(r'<span data-atom="mention"[^>]*>.*?</span>', "", body, flags=re.S)
    return pandoc_wrap(body, title)


def main():
    pats = os.environ.get("PRIVACY_PATTERNS")
    if not pats:
        sys.exit("PRIVACY_PATTERNS is not set; refusing to sync without a privacy scan.")
    scan = re.compile(pats, re.I)
    manifest = json.load(open(sys.argv[1]))
    fetched = sys.argv[2]
    exports = {}
    for p in sys.argv[3:]:
        exports[json.load(open(p))["frame"]["slug"]] = p

    staged, problems = {}, []
    for e in manifest:
        if e.get("docs"):
            if e["id"] not in exports:
                problems.append(f"MISSING docs export for {e['path']}")
                continue
            html = docs_page(exports[e["id"]], e["title"])
        else:
            src = os.path.join(fetched, e["id"], "index.html")
            if not os.path.exists(src):
                problems.append(f"MISSING fetched file for {e['path']}")
                continue
            html = clean_html(open(src, encoding="utf-8").read())
        hits = {m.group(0) for m in scan.finditer(html)}
        if hits:
            problems.append(f"PRIVACY HIT in {e['path']}: {len(hits)} match(es)")
            continue
        staged[e["path"]] = html

    if any(p.startswith("PRIVACY") for p in problems):
        print("\n".join(problems))
        sys.exit(2)

    for path, html in staged.items():
        dest = os.path.join(REPO, path)
        old = open(dest, encoding="utf-8").read() if os.path.exists(dest) else None
        if old == html:
            print(f"UNCHANGED {path}")
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "w", encoding="utf-8").write(html)
        print(f"{'CHANGED' if old is not None else 'ADDED'} {path}")
    for p in problems:
        print(p)


if __name__ == "__main__":
    main()
