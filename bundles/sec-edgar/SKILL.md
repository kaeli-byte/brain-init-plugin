---
name: sec-edgar
version: 1.0.1
description: Query US public company SEC EDGAR filings and financial data — company info, filings (10-K, 10-Q, 8-K), XBRL facts, financial statements, insider trades, institutional holdings, and material events — through the Kimi agent-gw data source API. Use when the user needs SEC filing data, financial statements for US-listed companies, insider trading reports, institutional ownership, or wants to pull structured EDGAR data into wiki ingestion. Complements cfi-filings (Chinese A-shares) to cover US equities.
---

# SEC EDGAR — US Public Company Filings & Financial Data

Structured access to SEC EDGAR through the Kimi `agent-gw` data source layer.
Returns parsed filings, XBRL facts, financial statements, insider trades,
institutional holdings, and material events. Covers 8,000+ US-listed companies
with data back to 2009 (XBRL era). All data comes from internal DB
(alpha-longdata). Output is always CSV files — no raw HTML/PDF scraping.

## Setup (always first)

The `agent-gw` Python SDK must be installed. Auth + base URL must be configured:

```bash
# Install SDK if needed
python3 -c "import agent_gw" || python3 -m pip install "$(curl -s https://cdn.kimi.com/agentgw/pysdk/manifest.json | python3 -c "import json,sys; print(json.load(sys.stdin)['latest']['url'])")"

# Required env vars (set in .env and .claude/settings.local.json):
#   KIMI_API_KEY=sk-kimi-...       (API key)
#   KIMI_BASE_URL=https://agent-gw.kimi.com/coding   (production endpoint)
# Without KIMI_BASE_URL, the SDK defaults to an unreachable dev endpoint.
```

The skill script lives at `.claude/skills/sec-edgar/scripts/sec_edgar_tool.py`.
Set `S` for convenience:

```bash
S=.claude/skills/sec-edgar/scripts/sec_edgar_tool.py
```

## The two rules you must follow

1. **Always `describe` first, then `call`.** The data source API catalog is
   dynamic — endpoints, parameters, defaults, and allowed values can change.
   Never guess an API name or parameter shape.

2. **Every API requires `file_path`** — an absolute path where the CSV output
   will be saved. Always use paths under `raw/sec-edgar/` in the workspace
   (e.g. `<vault>/raw/sec-edgar/AAPL-info.csv`). The
   script writes the returned file to exactly this path.

## Workflow

```bash
# Step 1 — Fetch the API catalog (CRITICAL: always first)
python3 $S describe

# Step 2 — Call the selected API with exact params from the docs
# ALL APIs require "file_path" (absolute path to save CSV)
python3 $S call --api-name "<api name>" --params-json '{"ticker":"AAPL","file_path":"/absolute/path/to/output.csv"}'

# For large/complex params, write JSON to a file instead
python3 $S call --api-name "<api name>" --params-file /tmp/params.json
```

## API Catalog (verified 2026-07-23)

### `sec_edgar_get_company_info`
Company name, CIK, SIC code, state of incorporation, fiscal year end, stock
exchange, shares outstanding, public float, category, contact info.

```bash
python3 $S call --api-name "sec_edgar_get_company_info" \
  --params-json '{"ticker":"AAPL","file_path":"<vault>/raw/sec-edgar/AAPL-company-info.csv"}'
```

### `sec_edgar_get_filings`
List SEC filings with fiscal period labels. Primary use: look up fiscal period
labels (e.g. `fiscal_year=2024, fiscal_period=Q2`) before calling
`sec_edgar_get_financial_statements`. Supports all form types.

```bash
# All recent filings
python3 $S call --api-name "sec_edgar_get_filings" \
  --params-json '{"ticker":"AAPL","file_path":"<vault>/raw/sec-edgar/AAPL-filings.csv"}'

# Filter by form type
python3 $S call --api-name "sec_edgar_get_filings" \
  --params-json '{"ticker":"TSLA","form_type":"10-K","limit":10,"file_path":"<vault>/raw/sec-edgar/TSLA-10K-filings.csv"}'
```

### `sec_edgar_get_financial_statements`
Full structured financial statements (income statement, balance sheet, cash flow)
parsed from SEC XBRL. Multi-year coverage in one call — the latest 10-K includes
3 years (IS/CF) and 2 years (BS) side-by-side. Use `financial_parameter` for
specific periods.

View levels: `summary` (~15 rows), `standard` (default, ~25 rows), `detailed`
(~50+ rows with segment breakdowns).

```bash
# Latest annual (all 3 statements)
python3 $S call --api-name "sec_edgar_get_financial_statements" \
  --params-json '{"ticker":"AAPL","statement":"all","file_path":"<vault>/raw/sec-edgar/AAPL-financials.csv"}'

# Specific fiscal year, income statement only, detailed view
python3 $S call --api-name "sec_edgar_get_financial_statements" \
  --params-json '{"ticker":"AAPL","statement":"income_statement","financial_parameter":"FY2025","view":"detailed","file_path":"<vault>/raw/sec-edgar/AAPL-FY2025-income.csv"}'

# Quarterly (Q2 FY2026)
python3 $S call --api-name "sec_edgar_get_financial_statements" \
  --params-json '{"ticker":"AAPL","statement":"balance_sheet","financial_parameter":"Q2FY2026","file_path":"<vault>/raw/sec-edgar/AAPL-Q2FY2026-bs.csv"}'
```

### `sec_edgar_get_xbrl_facts`
Single metric time-series — faster than full statements when you just need
revenue/net income/etc. across years. Three mutually exclusive query modes:
- **keyword** (recommended): plain-language term mapped to XBRL concepts. Near-synonyms accepted.
- **concept**: exact XBRL tag for precise lookup
- **metric**: shortcut for latest annual + quarterly value

```bash
# Revenue trend 2019-2025 via keyword
python3 $S call --api-name "sec_edgar_get_xbrl_facts" \
  --params-json '{"ticker":"AAPL","keyword":"revenue","year":"2019-2025","period":"FY","file_path":"<vault>/raw/sec-edgar/AAPL-revenue-trend.csv"}'

# Quick latest metric
python3 $S call --api-name "sec_edgar_get_xbrl_facts" \
  --params-json '{"ticker":"AAPL","metric":"free_cash_flow","file_path":"<vault>/raw/sec-edgar/AAPL-fcf.csv"}'

# Exact XBRL concept
python3 $S call --api-name "sec_edgar_get_xbrl_facts" \
  --params-json '{"ticker":"MSFT","concept":"NetIncomeLoss","period":"FY","file_path":"<vault>/raw/sec-edgar/MSFT-net-income.csv"}'
```

### `sec_edgar_get_insider_trades`
Insider transactions from SEC Forms 3/4/5. `summary=true` (default) = one row
per filing; `summary=false` = full transaction detail.

```bash
python3 $S call --api-name "sec_edgar_get_insider_trades" \
  --params-json '{"ticker":"META","limit":20,"file_path":"<vault>/raw/sec-edgar/META-insider-trades.csv"}'
```

### `sec_edgar_get_institutional_holdings`
13F filings from institutional investors. `ticker` is the INSTITUTION's ticker
(e.g. `BRK-B` for Berkshire), not the stock being held. Use `compare=true` for
quarter-over-quarter position changes.

```bash
python3 $S call --api-name "sec_edgar_get_institutional_holdings" \
  --params-json '{"ticker":"BRK-B","compare":true,"file_path":"<vault>/raw/sec-edgar/BRKB-13F.csv"}'
```

### `sec_edgar_get_company_events`
Material corporate events from 8-K filings: earnings releases, acquisitions,
executive changes. Use `start_date`/`end_date` to filter.

```bash
python3 $S call --api-name "sec_edgar_get_company_events" \
  --params-json '{"ticker":"AMZN","start_date":"2025-01-01","limit":20,"file_path":"<vault>/raw/sec-edgar/AMZN-events.csv"}'
```

## Integration with wiki ingestion

SEC EDGAR CSV data feeds the wiki's `/second-brain:capture` pipeline:

```bash
# 1. Pull company info + financials
python3 $S call --api-name "sec_edgar_get_company_info" \
  --params-json '{"ticker":"AAPL","file_path":"<vault>/raw/sec-edgar/AAPL-info.csv"}'

python3 $S call --api-name "sec_edgar_get_financial_statements" \
  --params-json '{"ticker":"AAPL","statement":"all","file_path":"<vault>/raw/sec-edgar/AAPL-financials.csv"}'

# 2. Read the CSV and extract claims via /second-brain:capture
# The CSV contains structured numbers — use these to create/update
# claim pages with revenue, profit, margin, cash flow, etc.

# 3. Cross-reference with existing claims via /second-brain:reconcile
```

The CSV output is far more efficient than PDF → mineru for financial data.
For narrative sections (MD&A, risk factors, business description), you still
need the original SEC filing HTML/PDF.

## Response shape

The `call` subcommand saves the returned CSV to the `file_path` specified in
params, and prints `result.assistant` text (summary/context) to stdout.
Errors go to stderr.

Expected `call_data_source_tool` response shape:
```python
{
    "is_success": bool,
    "result": {"user": list[str], "assistant": list[str]} | None,
    "error": {"user": list[str], "assistant": list[str]} | None,
    "files": [{"name": str, "content": str}],
}
```

The script writes each file in `files[]` to `name` (which is the `file_path`
from params). On failure, it prints `error.assistant` or `error.user` to stderr.

## Limits and caveats

- **`KIMI_BASE_URL` must be set.** The SDK defaults to
  `https://agent-gw-dev.dev.kimi.team/coding` which is unreachable. Set to
  `https://agent-gw.kimi.com/coding` (already configured in project `.env`).
- **`file_path` must be absolute.** Always use full paths under
  `raw/sec-edgar/` in the workspace.
- **All output is CSV.** No JSON/structured responses — data comes as CSV
  files written to `file_path`. Read them back with `head` or a dataframe
  tool after the call completes.
- **Catalog is dynamic.** API names and params can change between sessions.
  Always `describe` first, never cache the catalog.
- **Rate limits.** The `agent_gw` layer may throttle. If a call fails with
  a rate-limit error, wait and retry once.
- **Coverage.** 8,000+ US-listed companies, data back to 2009 (XBRL era).
  Foreign private issuers (20-F, 6-K) are included. Accepts both ticker
  symbols and CIK numbers.
- **Not a PDF downloader.** This skill returns structured CSV data. For
  original filing PDFs/HTMLs, use the SEC.gov website directly.
- **Data is as-reported.** XBRL facts and financial statements reflect what
  the company filed — not adjusted or normalized. Always note the filing
  date, period end date, and form type when citing numbers.
