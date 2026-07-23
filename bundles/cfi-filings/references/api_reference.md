# CFI Periodic Filings API — Full Reference

Base URL: `http://127.0.0.1:8000` (default). Project root:
`/Users/hafid/cfi-api/cfi`. Interactive docs: `/docs` when the server runs.

## Contents

1. Endpoints
2. Query semantics (fiscal vs publish year)
3. Field taxonomy
4. Direct HTTP usage
5. Data sources & the source switch
6. Upstream endpoints (reverse-engineered, for debugging/extension)
7. Edge cases & error handling
8. Validated coverage (2026-07-23 sweep)

## 1. Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | `{"status":"ok"}` |
| GET | `/api/search?q=&max_results=` | name/code → candidate codes (cninfo topSearch) |
| GET | `/api/company/{code}` | resolve code → name, internal_id, urls, source |
| GET | `/api/company/{code}/filings` | query filings (params below) |
| GET | `/api/company/{code}/annual-report/{year}` | FY annual bundle: `main_report` + `related` |

`/api/search` notes: **matches Chinese names and stock codes only — pinyin
and English queries normally return zero hits** (translate to the official
Chinese name first). Result fields: `code`, `name`, `category` (`"A股"` for
stocks), `pinyin`, `org_id`, `delisted`. One company may appear under
several codes (e.g. 贝特瑞: old 835185 `delisted: true` + migrated 920185
active) — prefer the active code. Entries with `category == "A股"` work with
all other endpoints.

`/filings` query params (all optional, combinable except the two years are
alternatives in spirit — `fiscal_year` wins the scan window if both given):

- `fiscal_year` (int) — report period year; scans publication years Y and Y+1
- `publish_year` (int) — raw publication-year filter (CFI `jzrq`)
- `report_type` — `annual|semi_annual|q1|q3|other`

With no params, `/filings` returns CFI's "latest" page (recent ~3 years).

## 2. Query semantics

- A-share annual reports for FY Y are published Feb–Apr of Y+1; Q1 of Y in
  April Y; semi-annual Y in Jul–Aug Y; Q3 Y in Oct Y. `fiscal_year` handles
  this by scanning two publication years and filtering by the year parsed
  from each filing's title.
- `publish_year` = CFI's `jzrq` = 公告年份. E.g. `publish_year=2020` for
  600519 returns the FY2019 annual report (published 2020-04) — correct
  behavior, surprising only if you expected fiscal semantics.

## 3. Field taxonomy

Company: `code`, `name`, `internal_id` (null for cninfo-only/BSE),
`quote_url`, `cbgg_url` (both null for BSE), `source`.

Filing:

| field | values / meaning |
|---|---|
| `publish_date` | YYYY-MM-DD 公告时间 |
| `title` | announcement title, whitespace-normalized |
| `fiscal_year` | int parsed from title; null for non-periodic |
| `report_type` | `annual` 年度报告, `semi_annual` 半年度报告, `q1` 第一季度报告, `q3` 第三季度报告, `other` |
| `variant` | `full` | `abstract` (摘要) | `summary` (简版) | `english` (英文版) | `announcement` (non-periodic) |
| `is_revised` | title mentions 更正/修订/更新后 |
| `article_url` | cfi.cn article page; null when source=cninfo |
| `pdf_url` | cninfo static PDF (`static.cninfo.com.cn/finalpage/...`) |

Choosing the canonical report: `variant=="full"`, prefer `is_revised==false`
unless the user wants the corrected version (then prefer the revised one —
it supersedes).

## 4. Direct HTTP usage

```bash
curl -s "http://127.0.0.1:8000/api/company/600519/filings?fiscal_year=2020&report_type=annual"
curl -s "http://127.0.0.1:8000/api/company/688005/annual-report/2023"
```

Errors: `404 {"detail": ...}` unknown code; `422` invalid param;
`502 {"detail": ...}` upstream failure (retry once after a few seconds).

## 5. Data sources & the source switch

Every response carries `source`:

- `cfi` — 中财网 `quote.cfi.cn`. Only serves the **most recent ~3-4 years**
  (verified 2026-07: publish years 2022+). Older years return HTTP 200 with
  an empty body (not an error page) — the API detects this and falls back.
- `cninfo` — 巨潮资讯, the official disclosure site. Full history to IPO.
  Also the only source for 北交所 codes (CFI doesn't list them).

The fallback triggers only when CFI yields zero filings for a year-bounded
query, or when CFI can't resolve the code at all.

## 6. Upstream endpoints (reverse-engineered)

For debugging or extending the scrapers (`cfi_client.py`, `cninfo_client.py`):

```
# CFI — all plain GET
GET https://quote.cfi.cn/{CODE}.html
    -> <title> gives name; regex cbgg/(\d+)/{CODE} gives INTERNAL_ID
GET https://quote.cfi.cn/quote.aspx?stockid={INTERNAL_ID}&contenttype=cbgg&jzrq={YEAR|latest}
    -> HTML table rows: date | title(link cfi.cn article) | 查看(link cninfo PDF)
GET https://quote.cfi.cn/cbgg/{INTERNAL_ID}/{CODE}.html   # == jzrq=latest
# NB: data.cfi.cn/cbgg/cbgg/{ID}/{CODE}.html returns 200 + empty body. Dead end.

# cninfo — POST form-encoded, headers X-Requested-With: XMLHttpRequest
POST www.cninfo.com.cn/new/information/topSearch/query   keyWord={CODE}
    -> [{code, orgId, zwjc, ...}]
POST www.cninfo.com.cn/new/hisAnnouncement/query
    stock={CODE},{orgId}&category={cat}&column={col}&seDate=YYYY-MM-DD~YYYY-MM-DD
    &pageNum=1&pageSize=30&tabName=fulltext
    cat: annual=category_ndbg_szsh semi=category_bndbg_szsh
         q1=category_yjdbg_szsh q3=category_sjdbg_szsh
    col: sse (60/68/9xx) | szse (00/30) | bj (43/83/87/92)
    -> announcements[]: announcementTitle, announcementTime (ms epoch),
       adjunctUrl (PDF path under static.cninfo.com.cn)
```

## 7. Edge cases

- Pre-IPO fiscal years → `count: 0` (correct; cross-check IPO date if unsure).
- cninfo quarterly reports often appear twice (全文 + 正文) — both `full`;
  either PDF is the report body.
- Very late variants (English 简版 published 2+ years after FY) fall outside
  the {Y, Y+1} scan window.
- BSE codes: `internal_id`/`quote_url`/`cbgg_url` are null; filings work for
  the BSE era (2021+). 新三板-era (pre-BSE) filings are not exposed by
  cninfo's endpoint under any known column/plate combination.
- Code→internal_id and code→orgId mappings persist in
  `.cache/company_map.json` / `.cache/cninfo_org_map.json`; delete to refresh.

## 8. Validated coverage (sweep of FY2015–FY2025, annual, live on 2026-07-23)

600519 沪主板 11/11 · 000001 深主板 11/11 · 300750 创业板 (zeros only
pre-IPO FY15–17) · 688005 科创板 (zeros only pre-IPO FY15–18) ·
835185 北交所 (BSE era 2021+ fully covered). Raw CSVs: `tests/results/`.
