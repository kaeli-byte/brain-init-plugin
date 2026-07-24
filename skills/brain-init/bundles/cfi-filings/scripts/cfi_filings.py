#!/usr/bin/env python3
"""
cfi_filings.py — agent CLI for the CFI Periodic Filings API.

Stdlib-only (works with any python3, no venv needed for querying).
Starting the server requires the project venv (uvicorn).

Subcommands:
  ensure-server            health-check; start uvicorn if down (pidfile in .cache/)
  stop-server              stop the server started by ensure-server
  company CODE             resolve stock code -> name / internal id / source
  filings CODE [--fiscal-year Y | --publish-year Y] [--type T]
  annual CODE YEAR         annual-report bundle (main_report + related)
  download CODE YEAR [--type T] [--out DIR] [--variants]
                           download filing PDFs, print a JSON manifest

Environment:
  CFI_API_URL   default http://127.0.0.1:8000
  CFI_API_DIR   project root containing api.py + .venv (auto-detected otherwise)

All output is JSON on stdout. Exit code 0 = ok, 1 = API/runtime error,
2 = usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8000"
VALID_TYPES = ("annual", "semi_annual", "q1", "q3", "other")


# --------------------------------------------------------------------------
# project root detection
# --------------------------------------------------------------------------

def find_project_root() -> Path:
    env = os.environ.get("CFI_API_DIR")
    candidates = [Path(env)] if env else []
    # walk up from this script (covers .agents/skills/<name>/scripts/)
    candidates += list(Path(__file__).resolve().parents)
    candidates += list(Path.cwd().parents) + [Path.cwd()]
    for c in candidates:
        if (c / "api.py").is_file() and (c / ".venv/bin/python").is_file():
            return c
    die(
        "cannot locate the API project root (needs api.py and .venv/). "
        "Set CFI_API_DIR=/path/to/project.",
        code=2,
    )


def base_url() -> str:
    return os.environ.get("CFI_API_URL", DEFAULT_URL).rstrip("/")


# --------------------------------------------------------------------------
# http helpers
# --------------------------------------------------------------------------

def api_get(path: str, params: dict | None = None) -> dict:
    url = base_url() + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={"User-Agent": "cfi-filings-cli/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("detail", str(exc))
        except Exception:
            detail = str(exc)
        die(f"API {exc.code}: {detail}")
    except urllib.error.URLError:
        die(f"API server unreachable at {base_url()} — run: cfi_filings.py ensure-server")


def die(msg: str, code: int = 1):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(code)


def out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=1))


# --------------------------------------------------------------------------
# server lifecycle
# --------------------------------------------------------------------------

def _paths(root: Path) -> tuple[Path, Path]:
    cache = root / ".cache"
    cache.mkdir(exist_ok=True)
    return cache / "server.pid", cache / "server.log"


def _healthy() -> bool:
    try:
        with urllib.request.urlopen(base_url() + "/api/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def cmd_ensure_server(_args):
    if _healthy():
        out({"ok": True, "status": "already_running", "url": base_url()})
        return
    root = find_project_root()
    pidfile, logfile = _paths(root)
    log = open(logfile, "ab")
    port = str(urllib.parse.urlparse(base_url()).port or 8000)
    proc = subprocess.Popen(
        [str(root / ".venv/bin/python"), "-m", "uvicorn", "api:app",
         "--host", "127.0.0.1", "--port", port],
        cwd=root, stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    pidfile.write_text(str(proc.pid))
    for _ in range(30):
        if _healthy():
            out({"ok": True, "status": "started", "pid": proc.pid, "url": base_url(),
                 "log": str(logfile)})
            return
        if proc.poll() is not None:
            die(f"server exited during startup; see {logfile}")
        time.sleep(0.5)
    die(f"server did not become healthy in 15s; see {logfile}")


def cmd_stop_server(_args):
    root = find_project_root()
    pidfile, _ = _paths(root)
    if not pidfile.exists():
        out({"ok": True, "status": "no_pidfile_nothing_to_do"})
        return
    pid = int(pidfile.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        time.sleep(1)
    except ProcessLookupError:
        pass
    pidfile.unlink(missing_ok=True)
    out({"ok": True, "status": "stopped", "pid": pid})


# --------------------------------------------------------------------------
# query subcommands
# --------------------------------------------------------------------------

def cmd_company(args):
    out(api_get(f"/api/company/{args.code}"))


def cmd_filings(args):
    if args.type and args.type not in VALID_TYPES:
        die(f"--type must be one of {VALID_TYPES}", code=2)
    out(api_get(f"/api/company/{args.code}/filings", {
        "fiscal_year": args.fiscal_year,
        "publish_year": args.publish_year,
        "report_type": args.type,
    }))


def cmd_annual(args):
    out(api_get(f"/api/company/{args.code}/annual-report/{args.year}"))


def cmd_search(args):
    out(api_get("/api/search", {"q": args.query, "max_results": args.max}))


def _safe_name(s: str) -> str:
    return re.sub(r"[^\w一-鿿.-]+", "_", s)[:80]


def cmd_download(args):
    data = api_get(f"/api/company/{args.code}/filings", {
        "fiscal_year": args.year,
        "report_type": args.type or "annual",
    })
    filings = data.get("filings", [])
    if not args.variants:
        # keep the main full report only (prefer non-revised)
        main = [f for f in filings if f["variant"] == "full" and not f["is_revised"]] \
            or [f for f in filings if f["variant"] == "full"]
        filings = main[:1]
    outdir = Path(args.out or f"./filings_{args.code}_{args.year}")
    outdir.mkdir(parents=True, exist_ok=True)

    manifest = {"ok": True, "company": data["company"], "source": data["source"],
                "fiscal_year": args.year, "downloaded": [], "skipped": []}
    for f in filings:
        pdf = f.get("pdf_url")
        if not pdf:
            manifest["skipped"].append({"title": f["title"], "reason": "no pdf_url"})
            continue
        fname = _safe_name(f["title"]) + ".pdf"
        dest = outdir / fname
        req = urllib.request.Request(pdf, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as w:
                w.write(r.read())
            manifest["downloaded"].append({
                "title": f["title"], "variant": f["variant"],
                "publish_date": f["publish_date"],
                "file": str(dest), "size_bytes": dest.stat().st_size,
            })
        except Exception as exc:
            manifest["skipped"].append({"title": f["title"], "reason": str(exc)})
    out(manifest)


# --------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Agent CLI for the CFI Periodic Filings API")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ensure-server").set_defaults(fn=cmd_ensure_server)
    sub.add_parser("stop-server").set_defaults(fn=cmd_stop_server)

    c = sub.add_parser("company"); c.add_argument("code"); c.set_defaults(fn=cmd_company)

    f = sub.add_parser("filings")
    f.add_argument("code")
    g = f.add_mutually_exclusive_group()
    g.add_argument("--fiscal-year", type=int)
    g.add_argument("--publish-year", type=int)
    f.add_argument("--type", choices=VALID_TYPES)
    f.set_defaults(fn=cmd_filings)

    a = sub.add_parser("annual"); a.add_argument("code"); a.add_argument("year", type=int)
    a.set_defaults(fn=cmd_annual)

    s = sub.add_parser("search",
                       help="find codes by Chinese company name (or code); pinyin/English usually returns nothing")
    s.add_argument("query")
    s.add_argument("--max", type=int, default=10)
    s.set_defaults(fn=cmd_search)

    d = sub.add_parser("download")
    d.add_argument("code"); d.add_argument("year", type=int)
    d.add_argument("--type", choices=VALID_TYPES)
    d.add_argument("--out")
    d.add_argument("--variants", action="store_true",
                   help="also download 摘要/简版/英文版 variants")
    d.set_defaults(fn=cmd_download)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
