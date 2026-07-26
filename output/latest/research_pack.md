# Parkhu research pack — 2026-07-26

- **session_date:** 2026-07-24 (trading day: False)
- **generated_at_ist:** 2026-07-26T13:56:29.510968+05:30
- **kb:** KB v1.0 (2026-06-21) | capital: 100000.0

## Regime

- market_regime: **Bearish**
- nifty: Bearish (-0.43%)
- india_vix: 14.03 (Medium)
- fii_net: -3892.77 | dii_net: 5453.55
- overall_risk: Medium | global_risk: Neutral

## Funnel

- universe: 364
- trend = Bullish: 176
- price > SMA200: 148
- price > EMA50: 143
- ADX14 > 25: 80
- RSI14 in 40-80: 79
- RS > 0 vs NIFTY and sector: 54
- delivery% >= 40: 40
- no earnings within 21d: 17
- event_risk_score <= 1: 15
- TV rating not Sell: 15

## Ideas

### LODHA — Buy (score 90.3)
- Lodha Developers Ltd. | risk_sector: Real Estate
- entry 1144.1 | stop 1061.79 | t1 1308.72 | t2 1391.03 | t3 1473.34 | R:R 2.0
- qty 8 | deployed 9153.0 (9.15%) | risk ₹658.0

### ICICIBANK — Buy (score 82.8)
- ICICI Bank Limited | risk_sector: Banks
- entry 1432.9 | stop 1381.32 | t1 1536.05 | t2 1587.63 | t3 1639.2 | R:R 2.0
- qty 6 | deployed 8597.0 (8.6%) | risk ₹309.0

### IIFL — Buy (score 82.4)
- IIFL Finance Limited | risk_sector: NBFC & Capital Markets
- entry 556.55 | stop 515.37 | t1 638.9 | t2 680.08 | t3 721.25 | R:R 2.0
- qty 17 | deployed 9461.0 (9.46%) | risk ₹700.0

## Open ledger

- **ICICIBANK** status=open entry=1470.8 last=1432.9 mfe=0.0 mae=-2.85 opened=2026-07-21
- **IPCALAB** status=open entry=1828.2 last=1762.7 mfe=0.0 mae=-3.58 opened=2026-07-21
- **J&KBANK** status=open entry=184.33 last=179.01 mfe=0.6 mae=-2.89 opened=2026-07-21
- **ZYDUSLIFE** status=open entry=1146.2 last=1108.7 mfe=0.0 mae=-3.27 opened=2026-07-21
- **IIFL** status=open entry=556.55 last=556.55 mfe=0.0 mae=0.0 opened=2026-07-25
- **LODHA** status=open entry=1144.1 last=1144.1 mfe=0.0 mae=0.0 opened=2026-07-25

## Needs action

- **J&KBANK**: NO DATA — dropped out of today's universe — last seen ₹179.01 on 2026-07-23; check the chart manually
- **ZYDUSLIFE**: EARNINGS AHEAD — results inside 21 days — KB-05 says reduce or stand aside rather than hold through the print

## Swing candidates (top)

- CREDITACC: score=14 rs_nifty=10.95 deliv=55.56
- ADANIENSOL: score=13 rs_nifty=14.62 deliv=33.21
- SHYAMMETL: score=13 rs_nifty=7.11 deliv=48.32
- ATHERENERG: score=13 rs_nifty=20.85 deliv=47.89
- NESTLEIND: score=13 rs_nifty=4.61 deliv=56.32
- ANANDRATHI: score=12 rs_nifty=7.64 deliv=53.24
- MOTHERSON: score=12 rs_nifty=2.84 deliv=40.07
- NYKAA: score=12 rs_nifty=6.9 deliv=47.2
- IPCALAB: score=12 rs_nifty=10.21 deliv=42.98
- INDHOTEL: score=12 rs_nifty=1.54 deliv=48.53
- LAURUSLABS: score=12 rs_nifty=8.96 deliv=31.4
- GODREJIND: score=12 rs_nifty=17.92 deliv=40.89
- KARURVYSYA: score=12 rs_nifty=16.92 deliv=54.27
- PFOCUS: score=12 rs_nifty=38.95 deliv=36.72
- IDFCFIRSTB: score=12 rs_nifty=4.08 deliv=48.26

## Groq desk note

- **model:** llama-3.3-70b-versatile
- **stance:** defensive

The market remains in a bearish regime with a medium overall risk. The Nifty trend is bearish with a 0.43% decline, and the India VIX is at a medium level of 14.03. Foreign institutional investors have a net outflow of -3892.77, while domestic institutional investors have a net inflow of 5453.55.

- **LODHA** [consider_entry/high] entry=1144.1 stop=1061.79 t1=1308.72 hold=16d — High Parkhu score of 90.3 and buy band
- **ICICIBANK** [manage_open/medium] entry=1432.9 stop=1381.32 t1=1536.05 hold=16d — Already in open book with a buy band and high Parkhu score of 82.8
- **IIFL** [consider_entry/medium] entry=556.55 stop=515.37 t1=638.9 hold=16d — Buy band and high Parkhu score of 82.4
- **IPCALAB** [stand_aside/low] entry=1828.2 stop=1715.39 t1=2053.81 hold=16d — Already in open book but no clear trend
- **J&KBANK** [watch/low] entry=184.33 stop=169.92 t1=213.16 hold=16d — Dropped out of today's universe and requires manual chart check
- **ZYDUSLIFE** [stand_aside/low] entry=1146.2 stop=1074.19 t1=1290.23 hold=35d — Earnings ahead and reduce or stand aside recommended

### Claude feed

Bearish regime, defensive stance, top ideas: LODHA, ICICIBANK, IIFL; caveats: provisional scores, no promoter pledge and ownership data, trade levels rebuilt


## Deep-dive URLs (after push)

- `stock_analysis.csv`: https://raw.githubusercontent.com/buhahemal/parkhu-ai/main/output/latest/stock_analysis.csv
- `manifest.json`: https://raw.githubusercontent.com/buhahemal/parkhu-ai/main/output/latest/manifest.json
- `report.json`: https://raw.githubusercontent.com/buhahemal/parkhu-ai/main/output/latest/report.json
- `swing_brief.json`: https://raw.githubusercontent.com/buhahemal/parkhu-ai/main/output/latest/swing_brief.json
- `swing_brief.md`: https://raw.githubusercontent.com/buhahemal/parkhu-ai/main/output/latest/swing_brief.md
- `market_summary.csv`: https://raw.githubusercontent.com/buhahemal/parkhu-ai/main/output/latest/market_summary.csv

- index: https://raw.githubusercontent.com/buhahemal/parkhu-ai/main/output/index.json
- pack json: https://raw.githubusercontent.com/buhahemal/parkhu-ai/main/output/2026-07-26/research_pack.json

Start with this pack. Use urls.deep_dive for symbol-level CSVs. Prefer output/latest/ stable paths after the run is pushed. Do not require latest.zip. Capital / deployment sizing is for Claude; the Pages desk is process and market visibility only.
