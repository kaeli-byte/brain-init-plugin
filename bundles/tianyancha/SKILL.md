---
name: tianyancha
description: Query Tianyancha (天眼查) Chinese enterprise database — 226 APIs covering company registration, shareholders, legal risks, intellectual property, financials, investments, group structures, and more. Use when researching Chinese companies (due diligence, competitor analysis, supply chain mapping, finding company registration details). Complements cfi-filings (A-share filings) and sec-edgar (US SEC) for full-spectrum company intelligence.
---

# Tianyancha (天眼查) — Chinese Enterprise Database

Structured access to Tianyancha's enterprise database through the Kimi
`agent-gw` data source layer. Covers 226 APIs across company registration,
shareholders, judicial risk, IP, operations, investments, and more.
All output is CSV — saved to the path specified by `file_path`.

## Setup

The `agent_gw` SDK is already installed and auth is configured in the project
`.env` and `.claude/settings.local.json` (same `KIMI_API_KEY` +
`KIMI_BASE_URL` as sec-edgar). No additional setup needed.

The skill script lives at `.claude/skills/tianyancha/scripts/tianyancha_tool.py`.
Set `S` for convenience:

```bash
S=.claude/skills/tianyancha/scripts/tianyancha_tool.py
```

## Architecture (critical — different from sec-edgar)

Tianyancha uses a **dynamic API discovery** pattern with 3 tools:

| Tool | Purpose |
|---|---|
| `tianyancha_api_search` | Search for APIs by category keywords. Returns API names + params. |
| `tianyancha_company_search` | Find company by partial name / registration number. Only when full name is unknown. |
| `tianyancha_api_call` | Call a specific API discovered via `api_search`. |

**The tool name is always `tianyancha_api_call`**, regardless of which
specific API you're calling. The actual API name goes in `api_call_name`.

## Workflow

```bash
# Step 1 — Discover APIs for your topic
python3 $S call --api-name "tianyancha_api_search" \
  --params-json '{"query":"企业基本信息,股东信息","limit":10}'

# Step 2 — Call the discovered API with full company name
python3 $S call --api-name "tianyancha_api_call" \
  --params-json '{"api_call_name":"工商信息-企业基本信息","api_call_params":{"keyword":"比亚迪股份有限公司"},"file_path":"/Users/hafid/deep-tech-wiki/raw/tianyancha/BYD-basic-info.csv"}'
```

## Key rules

1. **Always use full company names.** Never abbreviations — "比亚迪股份有限公司"
   not "比亚迪", "阿里巴巴集团控股有限公司" not "阿里巴巴". If you don't know
   the full name, use `tianyancha_company_search` first.

2. **`keyword` supports up to 5 companies** comma-separated:
   `"北京百度网讯科技有限公司,阿里巴巴集团控股有限公司"`

3. **`api_call_name` is always `tianyancha_api_call`.** The actual API name
   (discovered via `api_search`) goes in the `api_call_name` param, not the
   `--api-name` flag.

4. **Discover APIs by category, not by company.** `api_search` query uses
   category keywords like `"司法风险,年报"` or `"专利,招投标"` — never
   company names.

## Common API categories

Search with these keywords to discover relevant APIs:

| Category (CN) | English | Typical APIs discovered |
|---|---|---|
| 企业基本信息 | Basic company info | Registration, legal rep, capital, status |
| 股东信息 | Shareholders | Shareholder structure, equity stakes |
| 主要人员 | Key personnel | Directors, supervisors, executives |
| 司法风险 | Judicial risk | Lawsuits, enforcement, bankruptcy |
| 知识产权 | Intellectual property | Patents, trademarks, copyrights |
| 年报 | Annual reports | Company annual filings |
| 经营异常 | Abnormal operations | Business exceptions, penalties |
| 行政处罚 | Administrative penalties | Government sanctions |
| 对外投资 | External investments | Subsidiaries, invested companies |
| 分支机构 | Branches | Branch offices |
| 融资信息 | Financing info | Funding rounds, investors |
| 上市信息 | Listing info | IPO, stock listing details |
| 招投标 | Bidding | Government bids, procurement |
| 变更记录 | Change records | Registration changes over time |
| 税务评级 | Tax rating | Tax credit ratings |
| 进出口 | Import/export | Trade registration, customs data |
| 私募基金 | Private equity funds | PE fund registration |
| 建筑资质 | Construction qualification | Building permits, certifications |

## Recipes

```bash
S=.claude/skills/tianyancha/scripts/tianyancha_tool.py
OUT=/Users/hafid/deep-tech-wiki/raw/tianyancha

# --- Search for a company (when you don't know the full name) ---
python3 $S call --api-name "tianyancha_company_search" \
  --params-json '{"search_keyword":"比亚迪","file_path":"'$OUT'/BYD-search.csv"}'

# --- Basic company registration info ---
python3 $S call --api-name "tianyancha_api_call" \
  --params-json '{"api_call_name":"工商信息-企业基本信息","api_call_params":{"keyword":"比亚迪股份有限公司"},"file_path":"'$OUT'/BYD-basic-info.csv"}'

# --- Shareholder information ---
python3 $S call --api-name "tianyancha_api_call" \
  --params-json '{"api_call_name":"工商信息-股东信息","api_call_params":{"keyword":"宁德时代新能源科技股份有限公司"},"file_path":"'$OUT'/CATL-shareholders.csv"}'

# --- Judicial risk (lawsuits, enforcement) ---
python3 $S call --api-name "tianyancha_api_call" \
  --params-json '{"api_call_name":"司法风险-法律诉讼","api_call_params":{"keyword":"恒大地产集团有限公司","pageSize":10},"file_path":"'$OUT'/Evergrande-lawsuits.csv"}'

# --- Discover what APIs exist first ---
python3 $S call --api-name "tianyancha_api_search" \
  --params-json '{"query":"融资信息,上市信息,私募基金","limit":10}'
```

## Integration with wiki ingestion

Tianyancha data enriches Chinese company pages in the wiki. It provides
registration details, shareholder structure, and risk data that complements
A-share filings from `cfi-filings`:

```bash
# 1. Get basic company info
python3 $S call --api-name "tianyancha_api_call" \
  --params-json '{"api_call_name":"工商信息-企业基本信息","api_call_params":{"keyword":"<full company name>"},"file_path":"/Users/hafid/deep-tech-wiki/raw/tianyancha/company-basic-info.csv"}'

# 2. Read the CSV and extract claims via /capture
# Registration date, legal representative, registered capital, status

# 3. Cross-reference with existing wiki company page via /reconcile
```

## Combined US + China intelligence stack

| Market | Company data | Filings |
|---|---|---|
| US | `sec-edgar` (SEC EDGAR) | `sec-edgar` (10-K, 10-Q, 8-K) |
| China | `tianyancha` (天眼查) | `cfi-filings` (年报, 半年报, 季报) |

## Response shape

Same as sec-edgar. The `call` subcommand saves returned CSV to `file_path`
and prints `result.assistant` text to stdout. Errors go to stderr.

## Limits and caveats

- **226 APIs — always `api_search` first.** Don't guess API names. The
  catalog is dynamic; discover what's available for your query.
- **Full company names required.** Abbreviations return empty or wrong
  results. Use `company_search` when unsure.
- **CSV output only.** Data is written to `file_path`. Read it back after
  the call completes.
- **`file_path` must be absolute.** Always use paths under
  `raw/tianyancha/` in the workspace.
- **Rate limits.** The `agent_gw` layer may throttle. Retry once with a
  pause on rate-limit errors.
- **Data currency.** Tianyancha data reflects its last crawl/index time.
  Note the retrieval date when citing. For the most current filing data,
  supplement with `cfi-filings`.
- **Authentication.** Uses the same `KIMI_API_KEY` and `KIMI_BASE_URL` as
  sec-edgar — already configured in project `.env`.
