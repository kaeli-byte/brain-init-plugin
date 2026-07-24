---
name: mineru-batch
description: "Batch-convert PDFs to Markdown using MinerU Precision Parse API. Use when ingesting multiple annual reports, 10-Ks, or other large PDFs (>20 pages) into the wiki. Handles authentication, splitting oversized PDFs (>200 pages), parallel OSS upload, polling, download, and stitching. Includes battle-tested workarounds for SSL issues, upload header requirements, and model selection."
homepage: https://mineru.net/apiManage/docs
metadata:
  author: deep-tech-wiki
  version: "1.0.1"
  argument-hint: "<pdf-file-or-dir>"
  requires:
    bins: ["curl", "python3"]
    env: ["MINERU_TOKEN"]
---

# MinerU Batch PDF Conversion

Batch-convert large PDFs (>20 pages) to clean Markdown via the MinerU **Precision
Parse API**. This skill covers the API workflow battle-tested on 11 Chinese annual
reports during the July 2026 batch ingestion.

## Quick Reference

| API Tier | Max Pages | Max Size | Token | When to Use |
|----------|-----------|----------|-------|-------------|
| Agent | 20 | 10 MB | No | Small/single docs |
| **Precision** | **200** | **200 MB** | **Yes** | **Annual reports, 10-Ks** |

## Token Setup

Get a token at https://mineru.net/apiManage/token, add it to `.env`:

```bash
# .env (gitignored — never commit)
MINERU_TOKEN=your_token_here
```

Load before use:

```bash
export $(grep -v '^#' .env | xargs)
# or: set -a && source .env && set +a
```

1000 high-priority pages/day per account; excess pages process at lower priority
(slower but still complete). Copy `.env.example` for the template.

## Model Selection — CRITICAL

| Model | Best For | Notes |
|-------|----------|-------|
| `pipeline` | **Chinese annual reports**, complex tables, dense financials | Use this for all wiki ingestions. |
| `vlm` | Simple layouts, English docs, image-heavy PDFs | Produced 72 lines from a 197-page Chinese report. Do NOT use for Chinese docs. |

**Always default to `pipeline` for this wiki.** The vlm model produced incomplete
output on 3 of 11 Chinese reports in testing.

## Full Workflow (Precision API — Batch File Upload)

### Step 1: Split Oversized PDFs (>200 pages)

```python
import pypdf

def split_pdf(filepath):
    reader = pypdf.PdfReader(filepath)
    pages = len(reader.pages)
    if pages <= 200:
        return [filepath]

    parts = []
    for part_num, (start, end) in enumerate([(0, 200), (200, pages)], 1):
        writer = pypdf.PdfWriter()
        for i in range(start, min(end, pages)):
            writer.add_page(reader.pages[i])
        part_path = filepath.replace(".pdf", f"_part{part_num}.pdf")
        with open(part_path, "wb") as f:
            writer.write(f)
        parts.append(part_path)
    return parts
```

### Step 2: Request OSS Upload URLs

```bash
curl -s -X POST 'https://mineru.net/api/v4/file-urls/batch' \
  -H "Authorization: Bearer ${MINERU_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "files": [
      {"name": "report_part1.pdf", "data_id": "report_p1"},
      {"name": "report_part2.pdf", "data_id": "report_p2"}
    ],
    "model_version": "pipeline",
    "language": "ch",
    "enable_table": true,
    "enable_formula": true
  }'
```

**Response has `file_urls` array** (not `files`). Each URL is an OSS pre-signed
PUT endpoint.

### Step 3: Upload to OSS

```bash
# CRITICAL: Use -T (--upload-file), NOT --data-binary
# CRITICAL: Omit Content-Type header entirely
curl -s -o /dev/null -w "%{http_code}" -X PUT -T file.pdf "$UPLOAD_URL"
```

| Wrong | Right | Why |
|-------|-------|-----|
| `--data-binary @file` | `-T file` | OSS expects upload-file semantics |
| `Content-Type: application/pdf` | No Content-Type header | OSS signed URLs reject Content-Type |
| Python `urllib.request` | Python `subprocess` + `curl` | macOS Python 3.14 SSL cert issue |

### Step 4: Poll Until Complete

```bash
curl -s "https://mineru.net/api/v4/extract-results/batch/${BATCH_ID}" \
  -H "Authorization: Bearer ${MINERU_TOKEN}"
```

**CRITICAL: Response key is `extract_result`** (not `files`).

States: `pending` → `running` → `done` / `failed`. Poll every 15–20s.
~4 minutes per 200-page file.

### Step 5: Download ZIPs and Extract Markdown

```bash
# Each done file has a full_zip_url
curl -s -o output.zip "$full_zip_url"
python3 -c "
import zipfile
with zipfile.ZipFile('output.zip') as z:
    for n in z.namelist():
        if n.endswith('.md'):
            with z.open(n) as src, open('output.md', 'wb') as dst:
                dst.write(src.read())
"
```

ZIP contains: `full.md`, `*_content_list.json`, `*_model.json`, `layout.json`,
`images/`, `*_origin.pdf`.

### Step 6: Stitch Split Parts

```bash
cat report_part1.md > report.md
printf '\n\n<!-- PAGE BREAK: continued from part 2 -->\n\n' >> report.md
cat report_part2.md >> report.md
```

## Quality Verification

After conversion, check each file before ingestion:

```bash
# Must start with company header (not mid-document subsidiary tables)
head -5 output.md | grep -qE '公司|有限|股份' && echo "OK" || echo "MAY START MID-DOC — re-extract with pipeline"

# Expected density: >10 lines per page for Chinese reports
LINES=$(wc -l < output.md)
echo "$LINES lines (~$((LINES/PAGES)) per page)"

# Must contain key financial sections
grep -c '营业收入\|利润表\|资产负债表' output.md
```

## Troubleshooting

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| HTTP 403 on upload | `--data-binary` or Content-Type set | Use `-T` flag, no Content-Type |
| HTTP 429 | Agent API IP rate limit | Switch to Precision API with token |
| `-500 service error` | Malformed JSON or transient | Validate JSON with `python3 -m json.tool`, retry |
| `-10002 type mismatch` | Wrong `files` JSON structure | Must be `[{name, data_id}, ...]` |
| `KeyError: 'files'` (upload) | Wrong response key | Use `file_urls` |
| `KeyError: 'files'` (poll) | Wrong response key | Use `extract_result` |
| Starts mid-document | vlm model truncated output | Re-extract with `"model_version": "pipeline"` |
| SSL cert error (Python) | macOS Python 3.14 urllib bug | Use `curl` via `subprocess` |
| 0 results on first poll | Upload scan delay | Wait 30–60s, poll again |
| Local CLI GPU error | hybrid-engine needs MLX GPU | Use cloud API, not local CLI |

## CLI Tool

The skill includes a fully-tested CLI script at `mineru-batch.py`. It handles
the entire pipeline — splitting, upload, polling, download, extraction, and
stitching — with proper error handling and progress output.

```bash
# Convert a directory of PDFs
python3 .claude/skills/mineru-batch/mineru-batch.py raw/annual-reports/

# Convert specific files, custom output
python3 .claude/skills/mineru-batch/mineru-batch.py report.pdf -o ./out/

# With options
python3 .claude/skills/mineru-batch/mineru-batch.py ./pdfs/ --model vlm --keep-zips
```

**Options:** `-o/--output DIR`, `--model pipeline|vlm` (default: pipeline),
`--language ch|en|...` (default: ch), `--keep-zips`, `--keep-parts`,
`--token TOKEN` (reads from `.env` by default).

Token is loaded automatically from `.env` at the project root — no `export`
needed when using the CLI.

## Integration with Wiki Ingestion

This skill is the **first step** in the `/second-brain:capture` pipeline. After conversion:

1. Verify markdown quality (check headers, financial sections present)
2. Run `/second-brain:capture` or use specialist agents for claim extraction
3. Clean up intermediate files after successful ingestion

```bash
# Convert + verify
python3 .claude/skills/mineru-batch/mineru-batch.py raw/annual-reports/ -o raw/annual-reports/

# Ingest each converted markdown
# (use parallel agents or sequential /second-brain:capture commands)
```
