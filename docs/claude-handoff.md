# Claude / Cursor morning handoff

Do **not** upload `latest.zip`. Use the stable uncompressed pack.

## Start here (after the collect job has pushed)

1. **Research pack (markdown)**  
   https://raw.githubusercontent.com/buhahemal/parkhu-ai/main/output/latest/research_pack.md

2. **Index (date + all file URLs)**  
   https://raw.githubusercontent.com/buhahemal/parkhu-ai/main/output/index.json

3. **Dashboard (human + shareable)**  
   GitHub Pages site for this repo (enable **Settings → Pages → GitHub Actions** once).  
   Typical URL: `https://buhahemal.github.io/parkhu-ai/`

## What the pack contains

- Market regime and funnel (+ `analytics.funnel_conversions` for the Pages desk)
- New ideas with entry / stop / targets (capital / deployment sizing is for Claude)
- Open suggestion ledger + **needs action** from the brief review
- Top swing candidates (not the full 364-row universe)
- Deep-dive raw URLs for `stock_analysis.csv`, `manifest.json`, `report.json`
- Optional **`enrichment`** (Groq desk note) when `GROQ_API_KEY` is set — narrative only; levels stay from Parkhu gates

The **GitHub Pages desk** is process + market visibility (funnel charts, regime, ledger, Groq note).
It intentionally does **not** show capital deployed — keep that conversation in Claude.

### Groq enrichment (optional)

- Additive JSON under `research_pack.enrichment` — does **not** change scores, gates, or idea levels.
- Prefer `enrichment.claude_feed` as a short paste after the deterministic pack.
- Primary model `llama-3.3-70b-versatile` with fallbacks on rate-limit / failure.
- Repo secret: **Settings → Secrets → Actions → `GROQ_API_KEY`**. Rotate any key that was pasted in chat.
- Local: copy [`.env.example`](../.env.example) → `.env` (gitignored).

## Drill-down

Only fetch CSVs when you need a symbol-level check:

- https://raw.githubusercontent.com/buhahemal/parkhu-ai/main/output/latest/stock_analysis.csv
- https://raw.githubusercontent.com/buhahemal/parkhu-ai/main/output/latest/swing_brief.json

Or browse: https://github.com/buhahemal/parkhu-ai/tree/main/output/latest

## Suggested Claude prompt

```
Fetch the Parkhu research pack at
https://raw.githubusercontent.com/buhahemal/parkhu-ai/main/output/latest/research_pack.md
and summarize regime, ideas, and open positions that need action.
If enrichment.claude_feed is present, treat it as a Groq narrative overlay —
levels and scores in the pack remain authoritative.
Use index.json / stock_analysis.csv URLs only if drilling into a symbol.
Do not ask me for a zip.
```

## Local preview of the dashboard

```bash
# after a collect run (or generate pack against an existing date)
python -c "from collector.publish_pack import write_research_pack, mirror_latest, write_index_json; d='2026-07-26'; write_research_pack(d); mirror_latest(d); write_index_json(d)"

# backfill research_pack.json for older output/<date>/ folders from CSV + trades ledger
python -m collector.publish_pack --backfill --force --mirror-latest

mkdir -p site/data && cp output/latest/research_pack.json site/data/ && cp output/index.json site/data/
python -m http.server 8080 --directory site
# open http://localhost:8080
```

## One-time: enable GitHub Pages

Repo **Settings → Pages → Build and deployment → Source: GitHub Actions**.

Dashboard deploy is a **separate** workflow: [`.github/workflows/pages.yml`](../.github/workflows/pages.yml)
(**Deploy Parkhu Pages**).

| Trigger | What happens |
|---------|----------------|
| Push to `site/**` | UI-only redeploy (no collector) |
| Push to `output/latest/research_pack.json` | Data refresh after collect commits |
| Actions → **Deploy Parkhu Pages** → Run workflow | Manual deploy |

Local UI preview: copy pack into `site/data/` and serve `site/` (see above).
