#!/usr/bin/env python3
"""
MinerU Batch PDF Converter — Precision Parse API.

Converts PDF files or directories of PDFs to clean Markdown via the MinerU
Precision Parse API. Handles splitting (>200 pages), OSS upload, polling,
download, extraction, and stitching of split parts.

Usage:
    python3 .claude/skills/mineru-batch/mineru-batch.py raw/annual-reports/
    python3 .claude/skills/mineru-batch/mineru-batch.py report.pdf -o ./out/
    python3 .claude/skills/mineru-batch/mineru-batch.py ./pdfs/ --model vlm

Token: set MINERU_TOKEN in .env or export it.
Get a token at https://mineru.net/apiManage/token
"""

import argparse, json, os, subprocess, sys, time, zipfile
from pathlib import Path

BASE_URL = "https://mineru.net"
API_FILE_URLS = "/api/v4/file-urls/batch"
API_EXTRACT_RESULTS = "/api/v4/extract-results/batch"


# ── Helpers ─────────────────────────────────────────────────────────────────

def load_dotenv():
    """Load .env from project root (skill is at .claude/skills/mineru-batch/)."""
    for candidate in [
        Path(__file__).resolve().parent.parent.parent.parent / ".env",
        Path.cwd() / ".env",
    ]:
        if candidate.exists():
            with open(candidate) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, val = line.partition("=")
                        if key.strip() not in os.environ:
                            os.environ[key.strip()] = val.strip()
            return
    print("Warning: .env not found, MINERU_TOKEN may not be set.", file=sys.stderr)


def api_call(method, path, data=None, token=None):
    """Call MinerU API via curl (avoids macOS Python 3.14 SSL issues)."""
    t = token or os.environ.get("MINERU_TOKEN", "")
    cmd = ["curl", "-s", "-X", method, f"{BASE_URL}{path}",
           "-H", f"Authorization: Bearer {t}"]
    if data is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", data]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"API error (non-JSON): {result.stdout[:500]}", file=sys.stderr)
        sys.exit(1)


def upload_to_oss(filepath, signed_url):
    """Upload a file to an OSS signed URL. Uses -T, no Content-Type."""
    return subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
         "-X", "PUT", "-T", str(filepath), signed_url],
        capture_output=True, text=True, timeout=180,
    )


def split_pdf(filepath):
    """Split a PDF into ≤200-page parts. Returns list of part Paths."""
    import pypdf
    reader = pypdf.PdfReader(str(filepath))
    total = len(reader.pages)
    if total <= 200:
        return [filepath]

    parts = []
    for pn, (start, end) in enumerate([(0, 200), (200, total)], 1):
        writer = pypdf.PdfWriter()
        for i in range(start, min(end, total)):
            writer.add_page(reader.pages[i])
        part_path = filepath.with_name(
            f"{filepath.stem}_part{pn}{filepath.suffix}")
        with open(part_path, "wb") as f:
            writer.write(f)
        parts.append(part_path)
        print(f"  Split: {filepath.name} → part{pn} "
              f"(pages {start+1}–{min(end, total)})")
    return parts


# ── Pipeline ────────────────────────────────────────────────────────────────

def run(inputs, output_dir, model="pipeline", language="ch",
        keep_zips=False, keep_parts=False, token=None):
    """Full pipeline: split → upload → poll → download → stitch."""

    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    # ── Collect & split ──────────────────────────────────────────────────
    pdfs = []
    for inp in inputs:
        p = Path(inp).resolve()
        if p.is_dir():
            pdfs.extend(sorted(p.glob("*.pdf")))
        elif p.is_file() and p.suffix == ".pdf":
            pdfs.append(p)

    if not pdfs:
        print("No PDF files found.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(pdfs)} PDF(s)")

    all_parts = []
    for pdf in pdfs:
        all_parts.extend(split_pdf(pdf))

    if len(all_parts) > len(pdfs):
        print(f"  → {len(all_parts)} parts after splitting")

    # ── Build file list ──────────────────────────────────────────────────
    file_list = []
    for part in all_parts:
        data_id = part.stem
        for sfx in ["_2025-annual-report", "_annual-report",
                     "_part1", "_part2"]:
            data_id = data_id.replace(sfx, "")
        data_id = "".join(c for c in data_id
                          if c.isalnum() or c in "_-")[:64]
        file_list.append(
            {"name": part.name, "data_id": data_id, "path": part})

    # ── Step 1: Get upload URLs ──────────────────────────────────────────
    print(f"\nRequesting {len(file_list)} upload URL(s)...")
    payload = json.dumps({
        "files": [{"name": f["name"], "data_id": f["data_id"]}
                  for f in file_list],
        "model_version": model, "language": language,
        "enable_table": True, "enable_formula": True,
    })

    resp = api_call("POST", API_FILE_URLS, data=payload, token=token)
    if resp.get("code") != 0:
        print(f"Error: {resp.get('msg')} (code {resp.get('code')})",
              file=sys.stderr)
        sys.exit(1)

    batch_id = resp["data"]["batch_id"]
    urls = resp["data"]["file_urls"]  # ← "file_urls", not "files"

    if len(urls) != len(file_list):
        print(f"Mismatch: {len(urls)} URLs for {len(file_list)} files",
              file=sys.stderr)
        sys.exit(1)

    print(f"  Batch ID: {batch_id}")

    # ── Step 2: Upload ───────────────────────────────────────────────────
    print(f"\nUploading...")
    for i, (fi, url) in enumerate(zip(file_list, urls)):
        kb = fi["path"].stat().st_size / 1024
        print(f"  [{i+1}/{len(file_list)}] {fi['name']} ({kb:.0f} KB)...",
              end=" ", flush=True)
        r = upload_to_oss(str(fi["path"]), url)
        code = r.stdout.strip()
        print(f"HTTP {code}")
        if code != "200":
            print(f"    WARNING: upload may have failed", file=sys.stderr)

    # ── Step 3: Poll ─────────────────────────────────────────────────────
    print(f"\nPolling...")
    elapsed, interval, max_wait = 0, 15, 1800
    while elapsed < max_wait:
        time.sleep(interval)
        elapsed += interval
        resp = api_call("GET", f"{API_EXTRACT_RESULTS}/{batch_id}",
                        token=token)
        results = resp.get("data", {}).get(
            "extract_result", [])  # ← "extract_result"

        if not results:
            print(f"  [{elapsed}s] Waiting for scan...")
            continue

        done = sum(1 for r in results if r["state"] == "done")
        failed = sum(1 for r in results if r["state"] == "failed")
        pending = len(results) - done - failed

        mins, secs = divmod(elapsed, 60)
        print(f"  [{mins}m{secs:02d}s] Done: {done}, Failed: {failed}, "
              f"Processing: {pending}")
        if pending == 0:
            break
    else:
        print("Timed out.", file=sys.stderr)
        sys.exit(1)

    # ── Step 4: Download & Extract ───────────────────────────────────────
    print(f"\nDownloading...")
    stitch_map = {}

    for r in results:
        fname = r.get("file_name", "?")
        state, zip_url = r.get("state"), r.get("full_zip_url")

        if state == "failed":
            print(f"  FAILED: {fname} — {r.get('err_msg', '?')}")
            continue
        if state != "done" or not zip_url:
            continue

        zip_out = out / fname.replace(".pdf", ".zip")
        md_out = out / fname.replace(".pdf", ".md")

        subprocess.run(["curl", "-s", "-o", str(zip_out), zip_url],
                       check=True)
        with zipfile.ZipFile(zip_out) as zf:
            for n in zf.namelist():
                if n.endswith(".md"):
                    md_out.write_bytes(zf.read(n))

        kb = md_out.stat().st_size / 1024
        print(f"  {md_out.name} ({kb:.0f} KB)")

        # Track for stitching
        if "_part" in fname:
            base = fname.rsplit("_part", 1)[0].replace(".pdf", "")
        else:
            base = fname.replace(".pdf", "")
        stitch_map.setdefault(base, []).append(md_out)

        if not keep_zips:
            zip_out.unlink()

    # ── Step 5: Stitch split parts ───────────────────────────────────────
    stitched = 0
    for base, parts in stitch_map.items():
        if len(parts) < 2:
            continue
        parts.sort(key=lambda p: str(p))
        merged = out / f"{base}.md"
        with open(merged, "wb") as dst:
            for i, p in enumerate(parts):
                dst.write(p.read_bytes())
                if i < len(parts) - 1:
                    dst.write(b"\n\n<!-- PAGE BREAK: part 2 -->\n\n")
                if not keep_parts:
                    p.unlink()
        stitched += 1

    if stitched:
        print(f"  Stitched {stitched} split file(s)")

    # ── Summary ──────────────────────────────────────────────────────────
    final = sorted(out.glob("*_annual-report*.md")) or sorted(out.glob("*.md"))
    print(f"\nDone — {len(final)} markdown file(s) in {out}/")
    for md in final:
        lines = md.read_text().count("\n")
        print(f"  {md.name} ({lines} lines)")


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="MinerU Batch PDF Converter — Precision Parse API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 .claude/skills/mineru-batch/mineru-batch.py raw/annual-reports/
  python3 .claude/skills/mineru-batch/mineru-batch.py report.pdf -o ./out/
  python3 .claude/skills/mineru-batch/mineru-batch.py ./pdfs/ --model vlm

Set MINERU_TOKEN in .env or export it.
Get a token: https://mineru.net/apiManage/token
        """,
    )
    parser.add_argument("inputs", nargs="+",
                        help="PDF files or directories containing PDFs")
    parser.add_argument("-o", "--output", default="./output",
                        help="Output directory (default: ./output)")
    parser.add_argument("--model", choices=["pipeline", "vlm"],
                        default="pipeline",
                        help="Parse model (default: pipeline)")
    parser.add_argument("--language", default="ch",
                        help="Document language (default: ch)")
    parser.add_argument("--keep-zips", action="store_true",
                        help="Keep downloaded ZIPs after extraction")
    parser.add_argument("--keep-parts", action="store_true",
                        help="Keep intermediate part markdown after stitch")
    parser.add_argument("--token", default=None,
                        help="API token (reads MINERU_TOKEN from .env)")

    args = parser.parse_args()
    load_dotenv()

    token = args.token or os.environ.get("MINERU_TOKEN")
    if not token:
        print("Error: MINERU_TOKEN not set.", file=sys.stderr)
        print("  Add MINERU_TOKEN=... to .env, or export it, or use --token",
              file=sys.stderr)
        print("  Get a token: https://mineru.net/apiManage/token",
              file=sys.stderr)
        sys.exit(1)

    print(f"Model: {args.model}  |  Language: {args.language}  "
          f"|  Output: {args.output}")
    run(inputs=args.inputs, output_dir=args.output, model=args.model,
        language=args.language, keep_zips=args.keep_zips,
        keep_parts=args.keep_parts, token=token)


if __name__ == "__main__":
    main()
