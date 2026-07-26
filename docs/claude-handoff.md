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

- Market regime and funnel
- New ideas with entry / stop / targets / sizing
- Open suggestion ledger + **needs action** from the brief review
- Top swing candidates (not the full 364-row universe)
- Deep-dive raw URLs for `stock_analysis.csv`, `manifest.json`, `report.json`, brief

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
Use index.json / stock_analysis.csv URLs only if drilling into a symbol.
Do not ask me for a zip.
```

## Local preview of the dashboard

```bash
# after a collect run (or generate pack against an existing date)
python -c "from collector.publish_pack import write_research_pack, mirror_latest, write_index_json; d='2026-07-26'; write_research_pack(d); mirror_latest(d); write_index_json(d)"
mkdir -p site/data && cp output/latest/research_pack.json site/data/
python -m http.server 8080 --directory site
# open http://localhost:8080
```

## One-time: enable GitHub Pages

Repo **Settings → Pages → Build and deployment → Source: GitHub Actions**.  
The collect workflow deploys `site/` with that day’s `research_pack.json` embedded under `data/`.
