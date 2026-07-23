---
name: cfi-filings
description: Query and download Chinese A-share periodic filings (年报/半年报/季报 annual, semi-annual, Q1/Q3 reports) by stock code and year, and find stock codes from Chinese company names, through the local CFI Periodic Filings API (中财网 + 巨潮资讯/cninfo dual-source, full history back to IPO, covers 沪/深/创业板/科创板/北交所). Use when the user asks for a listed Chinese company's annual report, quarterly/semi-annual report, filing PDFs, disclosure dates, code lookup, or batch filing collection — e.g. "茅台2020年年报", "download the FY2023 annual report PDF for 688005", "what is 宁德时代's stock code", "when did X publish its Q3 report", "collect annual reports for these companies".
---

# CFI Periodic Filings API

Local REST API over 中财网 (CFI) + 巨潮资讯 (cninfo) giving structured JSON
access to A-share periodic filings and their official PDFs.

## Setup (always first)

The API project lives at `/Users/hafid/cfi-api/cfi`. All operations go through
the CLI — it manages the server for you:

```bash
S=/Users/hafid/cfi-api/cfi/.agents/skills/cfi-filings/scripts/cfi_filings.py
python3 $S ensure-server     # idempotent; starts uvicorn if not running
# ... do work ...
python3 $S stop-server       # when the task is done, stop the server
```

All CLI output is JSON on stdout; exit 1 = API/runtime error (message in
`.error`), exit 2 = bad usage. Server defaults to `http://127.0.0.1:8000`
(override with `CFI_API_URL`; override project detection with `CFI_API_DIR`).

## The one concept you must get right

**`fiscal_year` ≠ `publish_year`.** The FY2020 annual report is *published*
around Feb–Apr **2021**. Agents almost always want `fiscal_year` (报告期年份,
the year IN the report title). The API scans publication years {Y, Y+1}
automatically. Use `publish_year` (公告年份) only when the user explicitly
means "announcements published during year Y".

## Recipes

```bash
# find the code for a company name FIRST when the user gives a name
# (works with Chinese names and codes; pinyin/English returns nothing)
python3 $S search 贵州茅台        # -> 600519; check `category == "A股"`
python3 $S search 贝特瑞          # -> 835185 (delisted) + 920185 (active) — pick the active one

# resolve a code (name, internal id, which source covers it)
python3 $S company 600519

# all periodic filings for fiscal year 2020 (annual+semi+Q1+Q3+摘要+修订)
python3 $S filings 688005 --fiscal-year 2020

# only the annual report + its variants
python3 $S filings 600519 --fiscal-year 2020 --type annual

# annual-report bundle: main_report (full, non-revised preferred) + related
python3 $S annual 000001 2020

# latest filings (no year args)
python3 $S filings 300750

# download the FY2020 annual report PDF (main report only)
python3 $S download 600519 2020 --out ./output/600519

# download including 摘要/简版/英文版 variants
python3 $S download 600519 2020 --variants --out ./output/600519
```

**Name → code workflow:** when the user gives a company name, always run
`search` first and use the returned `code` for all other commands. The
search backend (cninfo topSearch) matches **Chinese names and stock codes
only — pinyin and English names usually return zero results**; if the user
provides an English name, translate to the official Chinese name first. A
name can yield several codes (delisted old 北交所 83xxxx vs active 920xxx,
A/B shares): prefer `delisted == false` and `category == "A股"`, and ask the
user when genuinely ambiguous.

Batch pattern: loop codes in bash/python around `filings`/`download`; the
server enforces a 0.4 s politeness delay upstream — do not parallelize calls.

## Response shape (filings)

`source` (`cfi`|`cninfo`), `count`, `company`, and `filings[]`, each with:
`publish_date`, `title`, `fiscal_year`, `report_type`
(`annual|semi_annual|q1|q3|other`), `variant`
(`full|abstract 摘要|summary 简版|english|announcement`), `is_revised`
(更正/修订), `article_url` (CFI only), `pdf_url` (cninfo static PDF).

To pick "the" annual report: `variant == "full"` and prefer
`is_revised == false` — or just use the `annual` subcommand's `main_report`.

## Sources and limits (know these before promising data)

- `source: cfi` covers recent years only (~FY2021+); older years transparently
  fall back to `source: cninfo` (official disclosure site, history to IPO).
- 北交所 (BSE) codes are cninfo-only (`internal_id: null`); their pre-BSE
  新三板-era filings are unavailable from both sources.
- Empty `filings` for pre-IPO fiscal years is correct, not an error.
- Unknown code → 404. Upstream failure → 502 (retry once after a pause).
- cninfo may list both 全文 and 正文 of one quarterly report (both kept).
- Save downloaded PDFs and any generated output inside the current workspace.

## Full reference

For the complete endpoint spec, direct-HTTP (curl) usage, field taxonomy,
upstream URL reverse-engineering notes, and edge cases, read
[references/api_reference.md](references/api_reference.md).
