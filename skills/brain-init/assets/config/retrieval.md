# Retrieval

## Protocol

1. **Resolve** — exact names, aliases, IDs, titles, tickers, patent numbers, and wikilinks before querying
2. **Formulate** — 2-4 lexical and semantic query formulations with relevant collection filters
3. **Rerank** — qmd candidates by relevance, discard obvious misfires
4. **Read** — 5-8 authoritative Markdown pages in full (not snippets)
5. **Trace** — follow claim-to-source references and retrieve exact evidence before publishing
6. **Expand** — backlinks only for impact analysis, contradiction search, or missing dimensions

## Collections

Status: ✅ All three collections active (qmd v1.0.9, 94 docs indexed, 11,480 vectors).

| Collection | Path | Files | Purpose |
|---|---|---|---|
| `brain-knowledge` | `wiki/` (symlink: `brain-knowledge/`) | 78 | Canonical claims, companies, technologies, markets, etc. Wiki-type enabled (`qmd wiki init`). |
| `brain-sources` | `wiki/sources/` (symlink: `brain-sources/`) | 16 | Primary-source records, evidence maps, interpretation warnings |
| `brain-investigations` | `wiki/investigations/` (symlink: `brain-investigations/`) | 0 | Strategic questions, theses, counterevidence, decisions (populated by `/second-brain-investigate`) |

Collection contexts are set — qmd knows what each collection contains for better query routing.

## Query Formulation

For each search, provide at least:
- One **lexical query** — exact terms, product names, company names, patent numbers
- One **semantic query** — intent description, conceptual framing, "find me evidence about..."

Example:
```
qmd query "intent: Find claims about electrified platform impact on thermal management connector content
lex: electrified platform coolant connector BEV thermal management connection points
vec: vehicle electrification increases cooling system complexity and connector count" \
  --format json -n 10 -c brain-knowledge -c brain-investigations -c brain-sources
```

## Stopping Condition

Stop retrieval when:
- Required dimensions are covered (all relevant entities, technologies, time periods)
- New results repeat known evidence without adding precision
- Contradictions are represented (both sides have evidence on record)
- Remaining uncertainty is explicit and characterized
- More retrieval is unlikely to change the decision materially

## Anti-Patterns

- **Snippet-as-evidence**: Never treat a qmd result snippet as authoritative. Read the full page.
- **Single-source confirmation**: Don't stop after one corroborating result. Seek independent confirmation.
- **Collection blindness**: Query all three collections; investigations and sources often hold critical context.
- **Query anchoring**: First query shapes interpretation. Reformulate at least once with different framing.
