// Prefer embedded data/ (Pages artifact). Dated packs come from raw GitHub.
const RAW_ROOT = "https://raw.githubusercontent.com/buhahemal/parkhu-ai/main/output";
const THEME_KEY = "parkhu-theme";

const CHART_THEMES = {
  light: {
    ink: "#0b1220",
    muted: "#64748b",
    line: "#e2e8f0",
    accent: "#2563eb",
    good: "#16a34a",
    warn: "#d97706",
    bad: "#dc2626",
    bar: "#2563eb",
    barSoft: "rgba(37,99,235,0.55)",
    tooltipBg: "#ffffff",
  },
  dark: {
    ink: "#f2f4f8",
    muted: "#8b93a7",
    line: "rgba(255,255,255,0.08)",
    accent: "#3b82f6",
    good: "#22c55e",
    warn: "#f59e0b",
    bad: "#ef4444",
    bar: "#3b82f6",
    barSoft: "rgba(59,130,246,0.55)",
    tooltipBg: "#121624",
  },
};

let CHART_COLORS = { ...CHART_THEMES.light };
const charts = [];
let catalog = { latest: null, dates: [] };
let currentDeskDate = "";

function currentTheme() {
  const t = document.documentElement.getAttribute("data-theme");
  return t === "dark" ? "dark" : "light";
}

function syncChartColors() {
  CHART_COLORS = { ...CHART_THEMES[currentTheme()] };
  chartDefaults();
}

function syncBrandLogos() {
  const theme = currentTheme();
  document.querySelectorAll("[data-logo-light][data-logo-dark]").forEach((img) => {
    const next = theme === "dark" ? img.dataset.logoDark : img.dataset.logoLight;
    if (next && img.getAttribute("src") !== next) img.setAttribute("src", next);
  });
}

function syncThemeToggle() {
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;
  const dark = currentTheme() === "dark";
  btn.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
  btn.title = dark ? "Light theme" : "Dark theme";
}

function applyTheme(theme, { persist = true, rerender = false } = {}) {
  const next = theme === "dark" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", next);
  if (persist) {
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      /* ignore */
    }
  }
  syncBrandLogos();
  syncThemeToggle();
  syncChartColors();
  if (rerender && currentDeskDate) {
    renderDesk(currentDeskDate).catch(() => {});
  }
}

function wireThemeToggle() {
  const btn = document.getElementById("theme-toggle");
  if (!btn) return;
  syncBrandLogos();
  syncThemeToggle();
  syncChartColors();
  btn.addEventListener("click", () => {
    applyTheme(currentTheme() === "dark" ? "light" : "dark", { rerender: true });
  });
}

async function fetchJson(urls) {
  let lastErr;
  for (const url of urls) {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error(`${url} → ${res.status}`);
      return { data: JSON.parse(await res.text()), source: url };
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr || new Error("fetch failed");
}

async function loadIndex() {
  try {
    const { data } = await fetchJson(["./data/index.json", `${RAW_ROOT}/index.json`]);
    const packDates = Array.isArray(data.pack_dates) ? data.pack_dates : [];
    const allDates = Array.isArray(data.dates) ? data.dates : [];
    // Prefer dates that have research_pack.json; fall back to all collection dates.
    const dates = [...new Set([...(packDates.length ? packDates : allDates), ...allDates])]
      .filter(Boolean)
      .sort()
      .reverse();
    return { latest: data.latest || dates[0] || null, dates, packDates };
  } catch {
    return { latest: null, dates: [], packDates: [] };
  }
}

function funnelConversions(funnel) {
  const out = [];
  let prev = null;
  for (const step of funnel || []) {
    if (!step || typeof step !== "object") continue;
    const surviving = Number(step.surviving) || 0;
    const keep = prev == null || prev === 0 ? null : round((100 * surviving) / prev, 1);
    const dropped = prev == null ? null : Math.max(prev - surviving, 0);
    const droppedCount =
      step.dropped_count != null && Number.isFinite(Number(step.dropped_count))
        ? Number(step.dropped_count)
        : dropped;
    out.push({
      gate: step.gate,
      surviving,
      from_prev: prev,
      keep_pct: keep,
      dropped: dropped ?? droppedCount,
      dropped_count: droppedCount,
      survivor_symbols: Array.isArray(step.survivor_symbols) ? step.survivor_symbols : [],
      dropped_symbols: Array.isArray(step.dropped_symbols) ? step.dropped_symbols : [],
      survivor_symbols_truncated: !!step.survivor_symbols_truncated,
      dropped_symbols_truncated: !!step.dropped_symbols_truncated,
    });
    prev = surviving;
  }
  return out;
}

function sectorCounts(ideas, openRows) {
  const counts = {};
  for (const row of [...(ideas || []), ...(openRows || [])]) {
    if (!row || typeof row !== "object") continue;
    const sec = String(row.risk_sector || row.sector || "Unknown").trim() || "Unknown";
    counts[sec] = (counts[sec] || 0) + 1;
  }
  return Object.entries(counts)
    .map(([sector, names]) => ({ sector, names }))
    .sort((a, b) => b.names - a.names || a.sector.localeCompare(b.sector));
}

function bookStats(openRows, needsAction) {
  const mfe = [];
  const mae = [];
  for (const r of openRows || []) {
    if (r?.mfe_pct != null && Number.isFinite(Number(r.mfe_pct))) mfe.push(Number(r.mfe_pct));
    if (r?.mae_pct != null && Number.isFinite(Number(r.mae_pct))) mae.push(Number(r.mae_pct));
  }
  return {
    open: (openRows || []).length,
    needs_action: (needsAction || []).length,
    avg_mfe_pct: mfe.length ? round(mfe.reduce((a, b) => a + b, 0) / mfe.length, 2) : null,
    avg_mae_pct: mae.length ? round(mae.reduce((a, b) => a + b, 0) / mae.length, 2) : null,
  };
}

/** Older days may only have swing_brief — adapt into desk pack shape. */
function briefToPack(brief, date) {
  const ideas = Array.isArray(brief.ideas) ? brief.ideas : [];
  const review = brief.review && typeof brief.review === "object" ? brief.review : {};
  const reviewed = Array.isArray(review.reviewed) ? review.reviewed : [];
  const openRows = reviewed
    .filter((r) => r && String(r.status || "open").toLowerCase() !== "closed")
    .map((r) => ({
      ...r,
      last_price: r.last_price ?? r.price ?? null,
    }));
  const needsAction = reviewed.filter((r) => {
    const a = String(r?.action || "").toUpperCase();
    return a && a !== "HOLD" && a !== "HOLD / TRAIL";
  });
  const scoring = brief.scoring && typeof brief.scoring === "object" ? brief.scoring : {};
  let coverage = null;
  if (scoring.weight_unavailable_pct != null) {
    const lost = Number(scoring.weight_unavailable_pct);
    if (Number.isFinite(lost)) coverage = round(100 - lost, 1);
  }
  return {
    schema: "parkhu.research_pack.v2",
    collection_date: brief.data_date || date,
    session_date: null,
    is_trading_day: null,
    generated_at_ist: brief.regime?.generated_at_ist || null,
    kb_version: brief.kb_version,
    limits: brief.limits || {},
    regime: brief.regime || {},
    funnel: brief.funnel || [],
    ideas,
    survivor_outcomes: Array.isArray(brief.survivor_outcomes) ? brief.survivor_outcomes : [],
    survivor_outcomes_total: brief.survivor_outcomes_total || 0,
    survivor_outcomes_truncated: !!brief.survivor_outcomes_truncated,
    analytics: {
      funnel_conversions: funnelConversions(brief.funnel || []),
      sector_counts: sectorCounts(ideas, openRows),
      book: bookStats(openRows, needsAction),
      ideas_count: ideas.length,
      score_coverage_pct: coverage,
      caveats: Array.isArray(brief.caveats) ? brief.caveats : [],
    },
    ledger: {
      open: openRows,
      review: reviewed,
      needs_action: needsAction,
      closed_today: review.closed_today || [],
    },
    urls: {
      brief_md: `${RAW_ROOT}/${date}/swing_brief.md`,
      pack_json: `${RAW_ROOT}/${date}/research_pack.json`,
      folder: `https://github.com/buhahemal/parkhu-ai/tree/main/output/${date}`,
      deep_dive: {
        "funnel_detail.json": {
          download_url: `${RAW_ROOT}/${date}/funnel_detail.json`,
        },
      },
    },
    _source_kind: "brief",
  };
}

async function loadPackForDate(date) {
  const latest = catalog.latest;
  const isLatest = !date || date === "latest" || (latest && date === latest);

  if (isLatest) {
    try {
      const { data, source } = await fetchJson([
        "./data/research_pack.json",
        `${RAW_ROOT}/latest/research_pack.json`,
        latest ? `${RAW_ROOT}/${latest}/research_pack.json` : null,
      ].filter(Boolean));
      if (!data.error) return { pack: data, source, kind: "pack", date: data.collection_date || latest };
    } catch {
      /* fall through to dated / brief */
    }
  }

  const target = date || latest;
  if (!target) throw new Error("No collection dates available");

  try {
    const { data, source } = await fetchJson([`${RAW_ROOT}/${target}/research_pack.json`]);
    return { pack: data, source, kind: "pack", date: target };
  } catch {
    /* try swing brief */
  }

  const { data, source } = await fetchJson([`${RAW_ROOT}/${target}/swing_brief.json`]);
  return { pack: briefToPack(data, target), source, kind: "brief", date: target };
}

function destroyCharts() {
  while (charts.length) {
    const c = charts.pop();
    try {
      c.destroy();
    } catch {
      /* ignore */
    }
  }
}

function selectedDateFromUrl() {
  const q = new URLSearchParams(location.search).get("date");
  if (q && /^\d{4}-\d{2}-\d{2}$/.test(q)) return q;
  return "";
}

function setDateInUrl(date) {
  const url = new URL(location.href);
  if (!date || date === catalog.latest) url.searchParams.delete("date");
  else url.searchParams.set("date", date);
  history.replaceState(null, "", url);
}

function fillDateSelect(preferred) {
  const sel = document.getElementById("date-select");
  const latest = catalog.latest;
  const dates = catalog.dates.length
    ? catalog.dates
    : latest
      ? [latest]
      : [];
  sel.replaceChildren(
    el("option", { value: latest || "" }, latest ? `Latest (${latest})` : "Latest"),
    ...dates
      .filter((d) => d !== latest)
      .map((d) => el("option", { value: d }, d)),
  );
  const value = preferred && dates.includes(preferred) ? preferred : latest || "";
  sel.value = value === latest ? latest || "" : value;
  return sel.value || latest || "";
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}

function fmt(v, digits = 2) {
  if (v == null || v === "") return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(digits);
  return String(v);
}

function round(n, d) {
  return Math.round(n * 10 ** d) / 10 ** d;
}

function nseSymbol(raw) {
  let s = String(raw || "").trim().toUpperCase();
  if (s.startsWith("NSE:")) s = s.slice(4);
  if (s.endsWith(".NS")) s = s.slice(0, -3);
  return s.trim();
}

function tradingViewUrl(symbol) {
  const s = nseSymbol(symbol);
  return s ? `https://in.tradingview.com/symbols/NSE-${encodeURIComponent(s)}/` : "";
}

function symbolLink(symbol, fallback = "—") {
  const s = nseSymbol(symbol);
  if (!s) return el("strong", {}, fallback);
  return el(
    "a",
    {
      class: "sym-link",
      href: tradingViewUrl(s),
      target: "_blank",
      rel: "noopener noreferrer",
      title: `Open ${s} on TradingView`,
    },
    el("strong", {}, s),
    el("span", { class: "sym-ext", "aria-hidden": "true" }, "↗"),
  );
}

function trendClass(label) {
  const s = String(label || "").toLowerCase();
  if (s.includes("bull")) return "bull";
  if (s.includes("bear")) return "bear";
  return "neutral";
}

function chartDefaults() {
  if (!window.Chart) return;
  Chart.defaults.color = CHART_COLORS.muted;
  Chart.defaults.borderColor = CHART_COLORS.line;
  Chart.defaults.font.family = "'Geist', 'IBM Plex Sans', system-ui, sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.font.weight = "500";
}

function makeChart(canvas, config) {
  if (!window.Chart || !canvas) return null;
  const c = new Chart(canvas, config);
  charts.push(c);
  return c;
}

function wireNav() {
  const links = [...document.querySelectorAll(".nav a")];
  const setActive = () => {
    const hash = location.hash || "#overview";
    links.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === hash));
  };
  links.forEach((a) => a.addEventListener("click", () => setTimeout(setActive, 0)));
  window.addEventListener("hashchange", setActive);
  setActive();
}

function fmtFlowCr(v) {
  if (v == null || v === "" || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  const abs = Math.abs(n);
  if (abs >= 1000) return `${n < 0 ? "−" : ""}${(abs / 1000).toFixed(1)}k`;
  return fmt(n, 0);
}

function avgOpenPnlPct(pack) {
  const rows = pack.ledger?.open || [];
  const vals = [];
  for (const r of rows) {
    if (r.entry && r.last_price != null && Number(r.entry) > 0) {
      vals.push(((Number(r.last_price) - Number(r.entry)) / Number(r.entry)) * 100);
    }
  }
  if (!vals.length) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function funnelSurvivors(pack) {
  const steps = pack.analytics?.funnel_conversions || pack.funnel || [];
  if (!steps.length) return null;
  const last = steps[steps.length - 1];
  return last?.surviving ?? null;
}

function avgIdeaScore(pack) {
  const ideas = pack.ideas || [];
  const vals = ideas.map((i) => Number(i.parkhu_score)).filter((n) => Number.isFinite(n));
  if (!vals.length) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function renderHeader(pack) {
  const r = pack.regime || {};
  const cls = trendClass(r.market_regime);

  const asOf = pack.generated_at_ist || r.generated_at_ist || "—";
  const asOfShort = String(asOf).replace(/\+\d{2}:\d{2}$/, "").replace("T", " ").slice(0, 16);
  document.getElementById("meta").replaceChildren(
    el("span", {}, el("strong", {}, "Date "), pack.collection_date || "—"),
    el("span", {}, el("strong", {}, "Updated "), asOfShort),
  );

  const a = pack.analytics || {};
  const book = a.book || {};
  const nifty = r.nifty_pct_change;
  const fii = r.fii_net;
  const survivors = funnelSurvivors(pack);
  const bookPnl = avgOpenPnlPct(pack);
  const ideaScore = avgIdeaScore(pack);
  const needs = book.needs_action ?? (pack.ledger?.needs_action || []).length;
  const ideasN = a.ideas_count ?? (pack.ideas || []).length;

  // Day pulse from pack (regime / funnel / ledger) — not Groq. Stance stays in AI strip.
  const kpis = [
    [
      "Nifty",
      nifty == null ? "—" : `${nifty > 0 ? "+" : ""}${fmt(nifty, 2)}%`,
      nifty > 0 ? "bull" : nifty < 0 ? "bear" : "",
      "Nifty session change. Negative tape → fewer aggressive new risk adds; positive → more room to act on high-score ideas.",
    ],
    [
      "FII flow",
      fii == null ? "—" : `${fmtFlowCr(fii)} cr`,
      fii > 0 ? "bull" : fii < 0 ? "bear" : "",
      "Foreign institutional net buy/sell (₹ crore). Heavy FII selling often pairs with defensive stance; buying supports risk-on.",
    ],
    [
      "India VIX",
      fmt(r.india_vix, 1),
      Number(r.india_vix) >= 18 ? "warn" : "",
      "India VIX — expected volatility. Rising/high VIX → cut aggression on new swings; calm VIX → environment more tradable.",
    ],
    [
      "Survivors",
      survivors == null ? "—" : fmt(survivors, 0),
      "",
      "Names left after all hard gates. Thin survivors → weak breadth / tight day; many survivors → process found more candidates.",
    ],
    [
      "New ideas",
      fmt(ideasN, 0),
      ideasN > 0 ? "bull" : "",
      "Buy-band ideas that cleared gates today. Zero is valid. Use as Claude shortlist — not automatic buys.",
    ],
    [
      "Needs action",
      fmt(needs, 0),
      needs ? "warn" : "",
      "Open-book flags (earnings, missing data, etc.). Clear these before adding new risk.",
    ],
    [
      "Book P&L",
      bookPnl == null ? "—" : `${bookPnl > 0 ? "+" : ""}${fmt(bookPnl, 1)}%`,
      bookPnl > 0 ? "bull" : bookPnl < 0 ? "bear" : "",
      "Average unrealized P&L% across open suggestions (entry → last). Pair with MFE/MAE in the ledger for management.",
    ],
    [
      "Idea score",
      ideaScore == null ? "—" : fmt(ideaScore, 0),
      ideaScore != null && ideaScore >= 80 ? "bull" : ideaScore != null && ideaScore < 75 ? "warn" : "",
      "Average Parkhu score of today’s new ideas. Higher = stronger process fit on the shortlist.",
    ],
  ];
  const tipBox = document.getElementById("kpi-tip");
  const root = document.getElementById("kpi");
  root.replaceChildren(
    ...kpis.map(([label, val, cls, tip]) => {
      const tone =
        cls === "bull" ? "tone-bull" : cls === "bear" ? "tone-bear" : cls === "warn" ? "tone-warn" : "";
      const cell = el(
        "div",
        {
          class: `cell ${tone}`.trim(),
          title: tip,
          role: "button",
          tabindex: "0",
          "aria-label": `${label}. ${tip}`,
        },
        el("span", {}, label),
        el("b", { class: cls }, val),
      );
      const showTip = () => {
        root.querySelectorAll(".cell").forEach((c) => c.classList.remove("active"));
        cell.classList.add("active");
        tipBox.hidden = false;
        tipBox.replaceChildren(el("strong", {}, `${label}: `), tip);
      };
      cell.addEventListener("click", showTip);
      cell.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          showTip();
        }
      });
      return cell;
    }),
  );

  const marketOpen = pack.is_trading_day === false ? "Closed" : pack.is_trading_day ? "Open session" : "—";
  const kill = pack.analytics?.kill_status || {};
  const killKids = [
    el(
      "span",
      { class: `pill ${cls}` },
      el("span", { class: "dot" }),
      "Regime ",
      el("b", {}, r.market_regime || "—"),
    ),
    el("span", { class: "pill" }, "Session ", el("b", {}, pack.session_date || "—")),
    el("span", { class: "pill" }, "Market ", el("b", {}, marketOpen)),
    el("span", { class: "pill" }, "Best sector ", el("b", {}, fmt(r.best_sector, 0))),
    el("span", { class: "pill" }, "Worst sector ", el("b", {}, fmt(r.worst_sector, 0))),
  ];
  if (kill.pause) {
    killKids.push(
      el(
        "span",
        {
          class: "pill pause",
          title: kill.detail || "Kill bar breached — pause new risk",
        },
        el("span", { class: "dot" }),
        "Kill ",
        el("b", {}, "PAUSE"),
      ),
    );
  } else if (kill.status === "ok") {
    killKids.push(
      el(
        "span",
        { class: "pill kill-ok", title: kill.detail || "Live sample clears kill bar" },
        el("span", { class: "dot" }),
        "Kill ",
        el("b", {}, "OK"),
      ),
    );
  } else if (kill.status === "insufficient_sample") {
    killKids.push(
      el(
        "span",
        {
          class: "pill",
          title: kill.detail || "Need more closed suggestions for kill bar",
        },
        "Kill ",
        el("b", {}, `${kill.closed ?? 0}/${kill.min_closed ?? "—"}`),
      ),
    );
  }
  document.getElementById("status-ribbon").replaceChildren(...killKids);
}

/** Plain-language help for each hard filter (matched by gate-name pattern). */
const FILTER_HELP = [
  {
    test: (g) => /^universe$/i.test(g),
    what: "Every stock in today’s scanned list that has a usable last price.",
    why: "Starting point — you cannot filter what you cannot price.",
  },
  {
    test: (g) => /trend\s*=\s*bullish/i.test(g),
    what: "The stock’s chart trend label is bullish (price structure pointing up, not sideways/down).",
    why: "Swing ideas are meant to ride strength; buying into a confirmed downtrend fights the tape.",
  },
  {
    test: (g) => /sma\s*200/i.test(g),
    what: "SMA = Simple Moving Average. SMA200 = average closing price over the last 200 trading days (about 10 months).",
    why: "Price above the long-term average is a classic “still in a long-term uptrend” check. Many traders trust SMA200 as a rough bull/bear line for the stock’s bigger picture.",
  },
  {
    test: (g) => /ema\s*50/i.test(g),
    what: "EMA = Exponential Moving Average (recent prices count more). EMA50 ≈ average of the last 50 sessions with more weight on the latest days.",
    why: "Confirms the medium-term trend is still supportive. It reacts faster than SMA200 — a stock can be above the long average but already rolling over; EMA50 catches that earlier.",
  },
  {
    test: (g) => /adx/i.test(g),
    what: "ADX = Average Directional Index, usually over 14 days. It measures how strong a trend is (0–100), not whether it is up or down.",
    why: "A stock can look “up” but be limp. ADX above ~25 means the trend has real force — better for swings than a weak drift. Below that, breakouts often fail.",
  },
  {
    test: (g) => /rsi/i.test(g),
    what: "RSI = Relative Strength Index (14-day). Oscillator from 0–100 for recent up vs down momentum — not “strength vs Nifty”.",
    why: "In an uptrend we want participation without extremes: too low can mean still weak; too high can mean stretched. The band keeps names that are constructive, not already exhausted.",
  },
  {
    test: (g) => /\brs\b/i.test(g) && /nifty/i.test(g),
    what: "RS = Relative Strength vs the index/sector (1-month): has this stock beaten Nifty and its sector?",
    why: "Prefer leaders. Even in a good market, laggards often keep lagging; outperformance improves odds for a swing.",
  },
  {
    test: (g) => /delivery/i.test(g),
    what: "Share of traded volume that was delivery (bought to hold) vs intraday squaring-off (NSE delivery %).",
    why: "Higher delivery often means real accumulation, not just day-trader noise. Low delivery can mean the move is fragile.",
  },
  {
    test: (g) => /earnings/i.test(g),
    what: "Next results are not inside the near-term earnings blackout window.",
    why: "Earnings can gap the stock through stops overnight. Stand aside in the blackout so a binary event does not own the trade.",
  },
  {
    test: (g) => /event_risk/i.test(g),
    what: "A simple event-risk flag/score from the analysis feed (corporate/event overhang).",
    why: "Skip names with elevated near-term event risk even if the chart looks fine.",
  },
  {
    test: (g) => /tv rating|tech_rating|not sell/i.test(g),
    what: "TradingView technical rating is not in the Sell zone.",
    why: "Avoid fighting a broad technical “Sell” consensus when we only want constructive setups.",
  },
];

function filterHelpFor(gate) {
  const g = String(gate || "");
  return FILTER_HELP.find((h) => h.test(g)) || null;
}

function closeFunnelTips(except) {
  document.querySelectorAll(".funnel-tip.is-open").forEach((tip) => {
    if (tip === except) return;
    tip.classList.remove("is-open", "is-pinned", "flip");
    const btn = tip.querySelector(".funnel-tip-btn");
    if (btn) btn.setAttribute("aria-expanded", "false");
  });
}

function positionFunnelTip(tip) {
  tip.classList.remove("flip");
  const pop = tip.querySelector(".funnel-tip-pop");
  if (!pop) return;
  const rect = pop.getBoundingClientRect();
  if (rect.bottom > window.innerHeight - 12) tip.classList.add("flip");
}

function wireFunnelTipGlobal() {
  if (wireFunnelTipGlobal.done) return;
  wireFunnelTipGlobal.done = true;
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeFunnelTips();
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".funnel-tip")) closeFunnelTips();
  });
}

function buildFunnelTip(gate) {
  const help = filterHelpFor(gate);
  if (!help) return null;

  const tipId = `funnel-tip-${String(gate).replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`;
  const btn = el(
    "button",
    {
      type: "button",
      class: "funnel-tip-btn",
      "aria-label": "What this filter means",
      "aria-expanded": "false",
      "aria-controls": tipId,
    },
    "?",
  );
  const pop = el(
    "div",
    { id: tipId, class: "funnel-tip-pop", role: "tooltip" },
    el("p", {}, el("strong", {}, "What"), " ", help.what),
    el("p", {}, el("strong", {}, "Why"), " ", help.why),
    el("p", {}, el("strong", {}, "Rule"), " ", String(gate)),
  );
  const tip = el("div", { class: "funnel-tip" }, btn, pop);

  const openTip = ({ pin = false } = {}) => {
    closeFunnelTips(tip);
    tip.classList.add("is-open");
    if (pin) tip.classList.add("is-pinned");
    btn.setAttribute("aria-expanded", "true");
    requestAnimationFrame(() => positionFunnelTip(tip));
  };
  const closeTip = () => {
    tip.classList.remove("is-open", "is-pinned", "flip");
    btn.setAttribute("aria-expanded", "false");
  };

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (tip.classList.contains("is-pinned")) closeTip();
    else openTip({ pin: true });
  });
  tip.addEventListener("mouseenter", () => openTip({ pin: tip.classList.contains("is-pinned") }));
  tip.addEventListener("mouseleave", () => {
    if (!tip.classList.contains("is-pinned")) closeTip();
  });
  btn.addEventListener("focus", () => openTip({ pin: tip.classList.contains("is-pinned") }));
  btn.addEventListener("blur", () => {
    // Delay so focus can move into the tip without flicker.
    setTimeout(() => {
      if (!tip.contains(document.activeElement) && !tip.classList.contains("is-pinned")) closeTip();
    }, 0);
  });

  return tip;
}

function mergeFunnelSteps(pack) {
  const raw = Array.isArray(pack.funnel) ? pack.funnel : [];
  const byGate = new Map(raw.map((s) => [s.gate, s]));
  const steps = pack.analytics?.funnel_conversions || [];
  const base = steps.length ? steps : funnelConversions(raw);
  return base.map((s) => {
    const src = byGate.get(s.gate) || {};
    return {
      ...s,
      survivor_symbols: s.survivor_symbols?.length
        ? s.survivor_symbols
        : src.survivor_symbols || [],
      dropped_symbols: s.dropped_symbols?.length ? s.dropped_symbols : src.dropped_symbols || [],
      survivor_symbols_truncated:
        s.survivor_symbols_truncated ?? !!src.survivor_symbols_truncated,
      dropped_symbols_truncated: s.dropped_symbols_truncated ?? !!src.dropped_symbols_truncated,
      dropped_count:
        s.dropped_count ??
        src.dropped_count ??
        (s.dropped != null ? s.dropped : null),
    };
  });
}

function symbolChipList(symbols, { total, shownLabel }) {
  const list = Array.isArray(symbols) ? symbols : [];
  const wrap = el("div", { class: "funnel-chip-list" });
  if (!list.length) {
    wrap.append(el("span", { class: "muted" }, "None listed"));
    return wrap;
  }
  if (total != null && total > list.length) {
    wrap.append(
      el("p", { class: "funnel-chip-note" }, `showing ${list.length} of ${total}`),
    );
  } else if (shownLabel) {
    wrap.append(el("p", { class: "funnel-chip-note" }, shownLabel));
  }
  wrap.append(
    ...list.map((sym) =>
      el("span", { class: "chip funnel-sym-chip" }, symbolLink(sym)),
    ),
  );
  return wrap;
}

function buildFunnelExpand(step) {
  const surviving = Number(step.surviving) || 0;
  const droppedN =
    step.dropped_count != null ? Number(step.dropped_count) : Number(step.dropped) || 0;
  const still = step.survivor_symbols || [];
  const removed = step.dropped_symbols || [];
  const details = el("details", { class: "funnel-expand" });
  const summaryLabel =
    still.length || removed.length
      ? `Symbols · still in ${Math.min(still.length, surviving)} of ${surviving}` +
        (droppedN ? ` · removed ${Math.min(removed.length, droppedN)} of ${droppedN}` : "")
      : surviving
        ? `Symbols (counts only — re-run collect for lists)`
        : "Symbols";
  details.append(el("summary", {}, summaryLabel));
  const body = el("div", { class: "funnel-expand-body" });
  body.append(
    el("h4", {}, "Still in"),
    symbolChipList(still, {
      total: surviving,
      shownLabel: still.length ? null : "No symbol sample for this step",
    }),
    el("h4", {}, "Removed"),
    symbolChipList(removed, {
      total: droppedN,
      shownLabel: removed.length ? null : "No removals or no sample",
    }),
  );
  details.append(body);
  return details;
}

function renderFunnel(pack) {
  const funnel = mergeFunnelSteps(pack);

  const viz = document.getElementById("funnel-viz");
  const drops = document.getElementById("funnel-drops");
  if (!viz || !drops) return;

  wireFunnelTipGlobal();

  if (!funnel.length) {
    viz.replaceChildren(el("p", { class: "empty" }, "No filter data for this day."));
    drops.replaceChildren();
    return;
  }

  const maxN = Math.max(...funnel.map((s) => Number(s.surviving) || 0), 1);

  viz.replaceChildren(
    ...funnel.map((s) => {
      const n = Number(s.surviving) || 0;
      const pctW = Math.max(8, Math.round((100 * n) / maxN));
      const tight = s.keep_pct != null && s.keep_pct < 50;
      const metaParts = [String(n)];
      if (s.keep_pct != null) metaParts.push(`keep ${s.keep_pct}%`);
      if (s.dropped != null) metaParts.push(`−${s.dropped}`);

      const labelKids = [el("span", { class: "funnel-name" }, s.gate || "—")];
      const tip = buildFunnelTip(s.gate);
      if (tip) labelKids.push(tip);
      const labelRow = el("div", { class: "funnel-label" }, ...labelKids);

      return el(
        "div",
        { class: `funnel-stage${tight ? " tight" : ""}` },
        labelRow,
        el(
          "div",
          { class: "funnel-track" },
          el(
            "div",
            {
              class: "funnel-bar",
              style: `width:${pctW}%`,
            },
            el("span", { class: "funnel-meta" }, metaParts.join(" · ")),
          ),
        ),
        buildFunnelExpand(s),
      );
    }),
  );

  const hot = funnel
    .filter((s) => s.keep_pct != null && s.keep_pct < 50)
    .sort((a, b) => a.keep_pct - b.keep_pct)
    .slice(0, 4);
  if (!hot.length) {
    drops.replaceChildren(
      el("span", { class: "chip" }, "No single filter cut more than half the remaining names."),
    );
    return;
  }
  drops.replaceChildren(
    el("span", { class: "chip" }, "Tightest filters:"),
    ...hot.map((s) =>
      el(
        "span",
        { class: "chip hot" },
        `${s.gate} · `,
        el("b", {}, `${s.keep_pct}%`),
        ` (−${s.dropped})`,
      ),
    ),
  );
}

function renderSurvivors(pack) {
  const body = document.getElementById("survivors-body");
  const filters = document.getElementById("survivors-filters");
  const sub = document.getElementById("survivors-sub");
  if (!body || !filters) return;

  const rows = Array.isArray(pack.survivor_outcomes) ? pack.survivor_outcomes : [];
  const total = Number(pack.survivor_outcomes_total) || rows.length;
  if (sub) {
    sub.textContent =
      total > rows.length
        ? `Top ${rows.length} of ${total} by score — why selected or not`
        : "Final gate passers — why selected or not";
  }

  if (!rows.length) {
    filters.replaceChildren();
    body.replaceChildren(el("p", { class: "empty" }, "No gate survivors for this day."));
    return;
  }

  const modes = [
    ["all", "All"],
    ["idea", "Ideas"],
    ["watchlist", "Watch"],
    ["rejected", "Rejected"],
  ];
  let mode = filters.dataset.mode || "all";
  if (!modes.some(([k]) => k === mode)) mode = "all";

  const paint = () => {
    filters.dataset.mode = mode;
    filters.replaceChildren(
      ...modes.map(([key, label]) => {
        const count =
          key === "all" ? rows.length : rows.filter((r) => r.status === key).length;
        const btn = el(
          "button",
          {
            type: "button",
            class: `survivors-filter${mode === key ? " active" : ""}`,
            "data-mode": key,
          },
          `${label} (${count})`,
        );
        btn.addEventListener("click", () => {
          mode = key;
          paint();
        });
        return btn;
      }),
    );

    const shown = mode === "all" ? rows : rows.filter((r) => r.status === mode);
    if (!shown.length) {
      body.replaceChildren(el("p", { class: "empty" }, "No names in this filter."));
      return;
    }

    const table = el("table", { class: "survivors-table" });
    table.append(
      el(
        "thead",
        {},
        el(
          "tr",
          {},
          el("th", {}, "Symbol"),
          el("th", {}, "Score"),
          el("th", {}, "Band"),
          el("th", {}, "Status"),
          el("th", {}, "Why"),
        ),
      ),
    );
    const tbody = el("tbody");
    for (const r of shown) {
      tbody.append(
        el(
          "tr",
          {},
          el("td", {}, symbolLink(r.symbol)),
          el("td", {}, fmt(r.score, 1)),
          el("td", {}, fmt(r.band, 0)),
          el("td", {}, el("span", { class: `status-pill status-${r.status || "rejected"}` }, r.status || "—")),
          el("td", { class: "survivors-reason" }, fmt(r.reason, 0)),
        ),
      );
    }
    table.append(tbody);
    body.replaceChildren(table);
  };

  paint();
}

function renderRegime(pack) {
  const r = pack.regime || {};
  const items = [
    ["Nifty", `${fmt(r.nifty_trend)} ${fmt(r.nifty_pct_change)}%`, trendClass(r.nifty_trend)],
    ["BankNifty", `${fmt(r.banknifty_trend)} ${fmt(r.banknifty_pct_change)}%`, trendClass(r.banknifty_trend)],
    ["VIX", fmt(r.vix_level, 0), ""],
    ["Risk", fmt(r.overall_risk, 0), ""],
    ["Best", `${fmt(r.best_sector, 0)}`, "bull"],
    ["Worst", `${fmt(r.worst_sector, 0)}`, "bear"],
    ["Crude", `${fmt(r.crude, 1)} (${fmt(r.crude_pct_change, 1)}%)`, ""],
    ["USDINR", `${fmt(r.usdinr, 2)}`, ""],
  ];
  document.getElementById("regime-stats").replaceChildren(
    ...items.map(([k, v, cls]) =>
      el("div", { class: "stat" }, el("dt", {}, k), el("dd", { class: cls || "" }, v)),
    ),
  );

  makeChart(document.getElementById("flow-chart"), {
    type: "bar",
    data: {
      labels: ["FII net", "DII net"],
      datasets: [
        {
          data: [r.fii_net ?? 0, r.dii_net ?? 0],
          backgroundColor: [
            (r.fii_net ?? 0) < 0 ? CHART_COLORS.bad : CHART_COLORS.good,
            (r.dii_net ?? 0) < 0 ? CHART_COLORS.bad : CHART_COLORS.good,
          ],
          borderWidth: 0,
          borderRadius: 6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        title: {
          display: true,
          text: "FII / DII flow (₹ cr)",
          color: CHART_COLORS.muted,
          font: { size: 13, weight: "600" },
        },
      },
      scales: {
        x: { grid: { display: false } },
        y: { grid: { color: CHART_COLORS.line } },
      },
    },
  });

  const world = pack.world_markets || [];
  const cueMap = { Bullish: 1, Mixed: 0, Neutral: 0, Bearish: -1 };
  const cues = world.length
    ? world.map((g) => {
        const tones = (g.markets || []).map((m) => m.tone);
        const bull = tones.filter((t) => t === "bull").length;
        const bear = tones.filter((t) => t === "bear").length;
        const label = bull > bear ? "Bullish" : bear > bull ? "Bearish" : "Neutral";
        return [g.region, label];
      })
    : [
        ["Asia", r.asia_cue],
        ["Europe", r.europe_cue],
        [
          "US",
          (r.us_sp500_pct ?? 0) > 0.15 ? "Bullish" : (r.us_sp500_pct ?? 0) < -0.15 ? "Bearish" : "Neutral",
        ],
      ];
  makeChart(document.getElementById("cues-chart"), {
    type: "bar",
    data: {
      labels: cues.map((c) => c[0]),
      datasets: [
        {
          data: cues.map((c) => cueMap[c[1]] ?? 0),
          backgroundColor: cues.map((c) => {
            const t = trendClass(c[1]);
            return t === "bull" ? CHART_COLORS.good : t === "bear" ? CHART_COLORS.bad : CHART_COLORS.warn;
          }),
          borderWidth: 0,
          borderRadius: 6,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        title: {
          display: true,
          text: "Global cues",
          color: CHART_COLORS.muted,
          font: { size: 13, weight: "600" },
        },
        tooltip: {
          callbacks: {
            label(ctx) {
              return cues[ctx.dataIndex]?.[1] || "";
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false } },
        y: {
          min: -1.2,
          max: 1.2,
          ticks: { stepSize: 1 },
          grid: { color: CHART_COLORS.line },
        },
      },
    },
  });

  renderMarketPulse(pack, cues);
}

function fmtPctSigned(v, digits = 2) {
  if (v == null || v === "" || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  const sign = n > 0 ? "+" : "";
  return `${sign}${fmt(n, digits)}%`;
}

function renderMarketPulse(pack, cues) {
  const root = document.getElementById("sentiment");
  if (!root) return;

  const world = Array.isArray(pack.world_markets) ? pack.world_markets : [];
  const toneCounts = { bull: 0, neutral: 0, bear: 0 };
  for (const group of world) {
    for (const m of group.markets || []) {
      const t = m.tone === "bull" || m.tone === "bear" ? m.tone : "neutral";
      toneCounts[t] += 1;
    }
  }
  // Fallback when pack has no world_markets yet (older dates).
  if (!world.length) {
    for (const [, label] of cues || []) {
      const t = trendClass(label);
      if (t === "bull") toneCounts.bull += 1;
      else if (t === "bear") toneCounts.bear += 1;
      else toneCounts.neutral += 1;
    }
  }

  const total = Math.max(toneCounts.bull + toneCounts.neutral + toneCounts.bear, 1);
  const pct = (n) => Math.round((100 * n) / total);

  const nodes = [
    el(
      "div",
      { class: "bar", title: "Cue mix across world markets that affect India" },
      el("div", { class: "seg bull", style: `flex:${toneCounts.bull || 0.001}` }),
      el("div", { class: "seg neutral", style: `flex:${toneCounts.neutral || 0.001}` }),
      el("div", { class: "seg bear", style: `flex:${toneCounts.bear || 0.001}` }),
    ),
    el(
      "div",
      { class: "legend" },
      el("span", {}, "Bullish ", el("b", {}, `${pct(toneCounts.bull)}%`)),
      el("span", {}, "Neutral ", el("b", {}, `${pct(toneCounts.neutral)}%`)),
      el("span", {}, "Bearish ", el("b", {}, `${pct(toneCounts.bear)}%`)),
    ),
  ];

  if (world.length) {
    nodes.push(
      el(
        "div",
        { class: "pulse-regions" },
        ...world.map((group) =>
          el(
            "div",
            { class: "pulse-region" },
            el("h3", {}, group.region || "—"),
            el(
              "ul",
              { class: "pulse-list" },
              ...(group.markets || []).map((m) =>
                el(
                  "li",
                  { class: `pulse-row ${m.tone || "neutral"}` },
                  el("span", { class: "pulse-name" }, m.label || m.metric || "—"),
                  el("span", { class: `pulse-pct ${m.tone || ""}` }, fmtPctSigned(m.pct_change)),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  } else {
    nodes.push(
      el(
        "p",
        { class: "empty" },
        "Detailed world markets appear after the next pack rebuild (from macro.csv).",
      ),
    );
  }

  root.replaceChildren(...nodes);
}

function field(label, value) {
  return el("div", {}, el("span", {}, label), " ", el("b", {}, value));
}

function renderIdeas(pack) {
  const body = document.getElementById("ideas-body");
  const ideas = pack.ideas || [];
  if (!ideas.length) {
    body.replaceChildren(el("p", { class: "empty" }, "No new ideas cleared the gates."));
    return;
  }

  makeChart(document.getElementById("scores-chart"), {
    type: "bar",
    data: {
      labels: ideas.map((i) => i.symbol),
      datasets: [
        {
          label: "Score",
          data: ideas.map((i) => i.parkhu_score),
          backgroundColor: CHART_COLORS.barSoft,
          borderColor: CHART_COLORS.accent,
          borderWidth: 1,
          borderRadius: 6,
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        title: {
          display: true,
          text: "Idea scores",
          color: CHART_COLORS.muted,
          font: { size: 13, weight: "600" },
        },
      },
      scales: {
        x: { min: 0, max: 100, grid: { color: CHART_COLORS.line } },
        y: {
          grid: { display: false },
          ticks: { color: CHART_COLORS.ink, font: { size: 12, weight: "600" } },
        },
      },
    },
  });

  const reviews = (pack.enrichment && pack.enrichment.stock_reviews) || [];
  const reviewBySym = Object.fromEntries(
    reviews.filter((r) => r && r.symbol).map((r) => [String(r.symbol), r]),
  );

  body.replaceChildren(
    ...ideas.map((idea) => {
      const lv = idea.levels || {};
      const band = String(idea.band || "").toLowerCase();
      const rev = reviewBySym[String(idea.symbol || "")];
      const kids = [
        el(
          "div",
          { class: "title" },
          symbolLink(idea.symbol),
          el("span", { class: `band ${band}` }, idea.band || "—"),
        ),
        el("div", { class: "sub" }, `${idea.risk_sector || "—"} · score ${fmt(idea.parkhu_score, 1)}`),
        el(
          "div",
          { class: "row" },
          field("Entry", fmt(lv.entry)),
          field("Stop", fmt(lv.stop)),
          field("T1", fmt(lv.t1)),
          field("R:R", fmt(lv.rr_t1)),
          field("Hold", `${fmt(lv.hold_days_t1, 0)}d`),
          field("T2", fmt(lv.t2)),
        ),
      ];
      if (rev && rev.status === "ok") {
        kids.push(
          el(
            "details",
            { class: "ai-review" },
            el(
              "summary",
              {},
              `AI review · ${rev.conviction || "medium"} conviction`,
            ),
            el("p", { class: "ai-review-thesis" }, rev.thesis || ""),
            rev.catalysts?.length
              ? el(
                  "p",
                  { class: "ai-review-meta" },
                  el("strong", {}, "Catalysts: "),
                  rev.catalysts.join(" · "),
                )
              : null,
            rev.risks?.length
              ? el(
                  "p",
                  { class: "ai-review-meta" },
                  el("strong", {}, "Risks: "),
                  rev.risks.join(" · "),
                )
              : null,
            rev.what_to_watch
              ? el(
                  "p",
                  { class: "ai-review-meta" },
                  el("strong", {}, "Watch: "),
                  rev.what_to_watch,
                )
              : null,
          ),
        );
      }
      return el("article", { class: "card" }, ...kids);
    }),
  );
}

function renderMarketNews(pack) {
  const root = document.getElementById("side-news");
  if (!root) return;
  const items = Array.isArray(pack.market_news_top10) ? pack.market_news_top10 : [];
  if (!items.length) {
    root.replaceChildren(
      el("p", { class: "empty" }, "No AI market news for this date (skipped or empty feed)."),
    );
    return;
  }
  root.replaceChildren(
    el(
      "ol",
      { class: "news-list" },
      ...items.map((n) =>
        el(
          "li",
          { class: `news-item impact-${String(n.impact || "medium").toLowerCase()}` },
          el(
            "div",
            { class: "news-head" },
            el("span", { class: `impact-pill ${String(n.impact || "medium").toLowerCase()}` }, n.impact || "medium"),
            n.symbol ? symbolLink(n.symbol) : null,
          ),
          el("p", { class: "news-headline" }, n.headline || "—"),
          n.why_it_matters ? el("p", { class: "news-why" }, n.why_it_matters) : null,
        ),
      ),
    ),
  );
}

function renderActionItems(actions) {
  const nodes = !actions.length
    ? [el("p", { class: "empty" }, "No positions flagged for action.")]
    : actions.map((r) =>
        el(
          "div",
          { class: "item" },
          symbolLink(r.symbol, "?"),
          ` — ${r.action || "ACTION"}: ${r.detail || ""}`,
        ),
      );
  document.getElementById("action-body").replaceChildren(...nodes);
  document.getElementById("side-action").replaceChildren(
    ...(!actions.length
      ? [el("p", { class: "empty" }, "Clear — no flags.")]
      : actions.slice(0, 5).map((r) =>
          el(
            "div",
            { class: "item" },
            symbolLink(r.symbol, "?"),
            ` — ${r.action || "ACTION"}`,
          ),
        )),
  );
}

function renderLedger(pack) {
  const rows = pack.ledger?.open || [];
  const actions = pack.ledger?.needs_action || [];
  renderActionItems(actions);

  const body = document.getElementById("ledger-body");
  const asOf = pack.ledger?.as_of || pack.collection_date || "";
  if (!rows.length) {
    body.replaceChildren(
      el(
        "p",
        { class: "empty" },
        asOf
          ? `No open suggestions as of ${asOf}. Ledger fills from trades/open.csv once ideas are tracked.`
          : "No open suggestions on the ledger for this date.",
      ),
    );
    const mfe = document.getElementById("mfe-chart");
    if (mfe) mfe.hidden = true;
    return;
  }
  const mfeCanvas = document.getElementById("mfe-chart");
  if (mfeCanvas) mfeCanvas.hidden = false;

  makeChart(document.getElementById("mfe-chart"), {
    type: "bar",
    data: {
      labels: rows.map((r) => r.symbol),
      datasets: [
        {
          label: "MFE %",
          data: rows.map((r) => r.mfe_pct ?? 0),
          backgroundColor: CHART_COLORS.good,
          borderWidth: 0,
          borderRadius: 4,
        },
        {
          label: "MAE %",
          data: rows.map((r) => r.mae_pct ?? 0),
          backgroundColor: CHART_COLORS.bad,
          borderWidth: 0,
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        title: {
          display: true,
          text: "MFE / MAE %",
          color: CHART_COLORS.muted,
          font: { size: 13, weight: "600" },
        },
        legend: {
          position: "bottom",
          labels: { boxWidth: 10, font: { size: 11 }, color: CHART_COLORS.muted },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: CHART_COLORS.ink, font: { size: 10, weight: "600" }, maxRotation: 40 },
        },
        y: { grid: { color: CHART_COLORS.line } },
      },
    },
  });

  body.replaceChildren(
    ...rows.map((r) => {
      let pnl = null;
      if (r.entry && r.last_price != null) {
        pnl = ((r.last_price - r.entry) / r.entry) * 100;
      }
      return el(
        "article",
        { class: "card" },
        el("div", { class: "title" }, symbolLink(r.symbol)),
        el("div", { class: "sub" }, `Opened ${r.date_opened || "—"}`),
        el(
          "div",
          { class: "row" },
          field("Entry", fmt(r.entry)),
          field("Last", fmt(r.last_price)),
          field("P&L", `${fmt(pnl)}%`),
          field("MFE", fmt(r.mfe_pct)),
          field("MAE", fmt(r.mae_pct)),
          field("Stop", fmt(r.stop)),
        ),
      );
    }),
  );
}

function renderSectors(pack) {
  const sectors = pack.analytics?.sector_counts || [];
  const canvas = document.getElementById("sector-chart");
  const wrap = canvas?.parentElement;
  if (!canvas || !wrap) return;
  const emptyId = "sector-empty";
  wrap.querySelector(`#${emptyId}`)?.remove();
  canvas.hidden = false;
  if (!sectors.length) {
    canvas.hidden = true;
    wrap.append(el("p", { class: "empty", id: emptyId }, "No sector counts."));
    return;
  }
  makeChart(canvas, {
    type: "bar",
    data: {
      labels: sectors.map((s) => s.sector),
      datasets: [
        {
          label: "Names",
          data: sectors.map((s) => s.names),
          backgroundColor: CHART_COLORS.barSoft,
          borderColor: CHART_COLORS.accent,
          borderWidth: 1,
          borderRadius: 6,
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { stepSize: 1 }, grid: { color: CHART_COLORS.line } },
        y: { grid: { display: false } },
      },
    },
  });
}

function renderQuality(pack) {
  const a = pack.analytics || {};
  const caveats = a.caveats || [];
  const pct = a.score_coverage_pct;
  const arc = document.getElementById("gauge-arc");
  const label = document.getElementById("gauge-pct");
  const circ = 2 * Math.PI * 52;
  if (pct == null) {
    label.textContent = "—";
    arc.style.strokeDashoffset = String(circ);
  } else {
    const clamped = Math.max(0, Math.min(100, pct));
    label.textContent = `${fmt(clamped, 0)}%`;
    arc.style.strokeDasharray = String(circ);
    arc.style.strokeDashoffset = String(circ * (1 - clamped / 100));
    arc.style.stroke = clamped >= 70 ? CHART_COLORS.good : clamped >= 40 ? CHART_COLORS.warn : CHART_COLORS.bad;
  }

  const root = document.getElementById("quality-body");
  if (!caveats.length) {
    root.replaceChildren(el("p", { class: "note" }, "No caveats listed. Capital stays in Claude."));
    return;
  }
  root.replaceChildren(
    el(
      "ul",
      { class: "quality" },
      ...caveats.map((c) => el("li", {}, c)),
    ),
  );
}

function renderLinks(pack) {
  const urls = pack.urls || {};
  const deep = urls.deep_dive || {};
  const items = [
    ["Pack", urls.pack_md],
    ["JSON", urls.pack_json],
    ["Brief", urls.brief_md],
    ["CSV", deep["stock_analysis.csv"]?.latest_url],
  ].filter(([, href]) => href);
  document.getElementById("links").replaceChildren(
    ...items.flatMap(([label, href], i) => {
      const a = el("a", { href, target: "_blank", rel: "noopener" }, label);
      return i ? [" · ", a] : [a];
    }),
  );
}

function waitForChart() {
  return new Promise((resolve) => {
    if (window.Chart) return resolve();
    const t = setInterval(() => {
      if (window.Chart) {
        clearInterval(t);
        resolve();
      }
    }, 20);
  });
}

function setDateNote(kind, date) {
  const note = document.getElementById("date-note");
  if (kind === "brief") {
    note.hidden = false;
    note.textContent = `${date}: no research pack yet — showing swing brief (desk metrics may be partial).`;
  } else {
    note.hidden = true;
    note.textContent = "";
  }
}

function shortModelName(model) {
  if (!model) return "—";
  const s = String(model);
  if (s.includes("70b")) return "llama-3.3-70b";
  if (s.includes("scout")) return "llama-4-scout";
  if (s.includes("8b")) return "llama-3.1-8b";
  return s.split("/").pop() || s;
}

function stanceClass(stance) {
  const s = String(stance || "").toLowerCase().replace(/-/g, "_");
  if (s === "defensive") return "defensive";
  if (s === "selective_aggressive") return "selective_aggressive";
  return "neutral";
}

function renderEnrichment(pack) {
  const enrich = pack.enrichment && typeof pack.enrichment === "object" ? pack.enrichment : null;
  const hero = document.getElementById("enrich-hero");
  const body = document.getElementById("enrich-body");
  const side = document.getElementById("side-enrich");

  if (!enrich) {
    hero.hidden = true;
    hero.replaceChildren();
    body.replaceChildren(
      el("p", { class: "enrich-skip" }, "No Groq note on this pack (enrichment not generated)."),
    );
    side.replaceChildren(el("p", { class: "enrich-skip" }, "—"));
    return;
  }

  if (enrich.status !== "ok") {
    const reason = enrich.reason || "skipped";
    const lastErr = Array.isArray(enrich.attempts)
      ? [...enrich.attempts].reverse().find((a) => a && !a.ok)?.error
      : null;
    hero.hidden = false;
    hero.replaceChildren(
      el("span", { class: "stance-chip neutral" }, "Skipped"),
      el(
        "p",
        { class: "brief-line" },
        `No Groq note — ${reason}${lastErr ? ` · ${String(lastErr).slice(0, 80)}` : ""}`,
      ),
      el("a", { class: "jump", href: "#ai-desk" }, "Details"),
    );
    const skipNodes = [
      el(
        "p",
        { class: "enrich-skip" },
        `Groq desk skipped: ${reason}. Deterministic regime / ideas still apply.`,
      ),
    ];
    if (lastErr) {
      skipNodes.push(
        el("p", { class: "enrich-skip" }, `Last error: ${String(lastErr).slice(0, 160)}`),
      );
    }
    body.replaceChildren(...skipNodes);
    side.replaceChildren(el("p", { class: "enrich-skip" }, "Skipped"));
    return;
  }

  const stance = enrich.stance || "neutral";
  const modelLabel = `Groq · ${shortModelName(enrich.model)}${enrich.fallback_used ? " (fallback)" : ""}`;
  const brief = enrich.market_brief || "—";

  hero.hidden = false;
  hero.replaceChildren(
    el("span", { class: `stance-chip ${stanceClass(stance)}` }, String(stance).replace(/_/g, " ")),
    el("p", { class: "brief-line" }, brief.length > 180 ? `${brief.slice(0, 177)}…` : brief),
    el("span", { class: `model-badge${enrich.fallback_used ? " fallback" : ""}` }, modelLabel),
    el("a", { class: "jump", href: "#ai-desk" }, "Full note →"),
  );

  const focus = Array.isArray(enrich.focus) ? enrich.focus : [];
  const suggestions = Array.isArray(enrich.suggestions) ? enrich.suggestions : [];
  const notes = Array.isArray(enrich.open_book_notes) ? enrich.open_book_notes : [];

  const table =
    suggestions.length === 0
      ? el("p", { class: "enrich-skip" }, "No symbol suggestions in this note.")
      : el(
          "div",
          { class: "enrich-table-wrap" },
          el(
            "table",
            { class: "enrich-table" },
            el(
              "thead",
              {},
              el(
                "tr",
                {},
                ...["Symbol", "Action", "Conv.", "Entry", "Stop", "T1", "Hold", "Rationale"].map((h) =>
                  el("th", {}, h),
                ),
              ),
            ),
            el(
              "tbody",
              {},
              ...suggestions.map((s) =>
                el(
                  "tr",
                  {},
                  el("td", { "data-label": "Symbol" }, symbolLink(s.symbol)),
                  el(
                    "td",
                    { class: "action", "data-label": "Action" },
                    String(s.action || "—").replace(/_/g, " "),
                  ),
                  el("td", { "data-label": "Conv." }, s.conviction || "—"),
                  el("td", { class: "mono", "data-label": "Entry" }, fmt(s.entry)),
                  el("td", { class: "mono", "data-label": "Stop" }, fmt(s.stop)),
                  el("td", { class: "mono", "data-label": "T1" }, fmt(s.t1)),
                  el(
                    "td",
                    { class: "mono", "data-label": "Hold" },
                    s.hold_days != null ? `${fmt(s.hold_days, 0)}d` : "—",
                  ),
                  el("td", { class: "rationale", "data-label": "Rationale" }, s.rationale || "—"),
                ),
              ),
            ),
          ),
        );

  const feed = enrich.claude_feed || "";
  const feedBlock = feed
    ? el(
        "details",
        { class: "claude-feed" },
        el("summary", {}, "Claude feed (copy for morning review)"),
        el("pre", {}, feed),
        el(
          "div",
          { class: "copy-row" },
          (() => {
            const btn = el("button", { type: "button" }, "Copy");
            btn.addEventListener("click", async () => {
              try {
                await navigator.clipboard.writeText(feed);
                btn.textContent = "Copied";
                setTimeout(() => {
                  btn.textContent = "Copy";
                }, 1500);
              } catch {
                btn.textContent = "Copy failed";
              }
            });
            return btn;
          })(),
        ),
      )
    : null;

  const bodyNodes = [
    el(
      "div",
      { class: "enrich-meta" },
      el("span", { class: `model-badge${enrich.fallback_used ? " fallback" : ""}` }, modelLabel),
    ),
    el("p", { class: "market-brief" }, brief),
  ];
  if (focus.length) {
    bodyNodes.push(
      el("div", { class: "enrich-meta" }, ...focus.map((f) => el("span", { class: "focus-chip" }, f))),
    );
  }
  bodyNodes.push(el("h3", { style: "margin:0 0 0.35rem;font-size:1rem" }, "Suggestions"), table);

  const reviews = Array.isArray(enrich.stock_reviews) ? enrich.stock_reviews.filter((r) => r?.status === "ok") : [];
  if (reviews.length) {
    bodyNodes.push(
      el("h3", { style: "margin:1rem 0 0.35rem;font-size:1rem" }, "Stock reviews"),
      el(
        "div",
        { class: "stock-reviews" },
        ...reviews.map((rev) =>
          el(
            "details",
            { class: "ai-review" },
            el("summary", {}, `${rev.symbol || "?"} · ${rev.conviction || "medium"}`),
            el("p", { class: "ai-review-thesis" }, rev.thesis || ""),
            rev.what_to_watch
              ? el("p", { class: "ai-review-meta" }, el("strong", {}, "Watch: "), rev.what_to_watch)
              : null,
          ),
        ),
      ),
    );
  }

  if (notes.length) {
    bodyNodes.push(el("ul", { class: "enrich-notes" }, ...notes.map((n) => el("li", {}, n))));
  }
  if (feedBlock) bodyNodes.push(feedBlock);
  body.replaceChildren(...bodyNodes);

  side.replaceChildren(
    el("div", { class: "side-enrich" },
      el("div", { class: `stance ${stanceClass(stance)}` }, String(stance).replace(/_/g, " ")),
      suggestions.length
        ? el(
            "ul",
            {},
            ...suggestions.slice(0, 3).map((s) =>
              el(
                "li",
                {},
                symbolLink(s.symbol),
                `: ${String(s.action || "").replace(/_/g, " ")}`,
              ),
            ),
          )
        : el("p", { class: "enrich-skip" }, "No suggestions"),
    ),
  );
}

async function renderDesk(date) {
  destroyCharts();
  syncChartColors();
  document.getElementById("meta").textContent = "Loading…";
  const { pack, kind } = await loadPackForDate(date);
  const shown = pack.collection_date || date || catalog.latest || "";
  currentDeskDate = shown || date || catalog.latest || "";
  setDateInUrl(shown === catalog.latest ? "" : shown);
  setDateNote(kind, shown);
  renderHeader(pack);
  renderEnrichment(pack);
  renderFunnel(pack);
  renderSurvivors(pack);
  renderRegime(pack);
  renderIdeas(pack);
  renderLedger(pack);
  renderSectors(pack);
  renderQuality(pack);
  renderMarketNews(pack);
  renderLinks(pack);
}

function wireDateSelect() {
  const sel = document.getElementById("date-select");
  sel.addEventListener("change", async () => {
    const date = sel.value || catalog.latest || "";
    try {
      await renderDesk(date);
    } catch (err) {
      document.getElementById("meta").textContent = `Failed to load ${date}: ${err.message}`;
      setDateNote(null, date);
    }
  });
}

try {
  await waitForChart();
  wireThemeToggle();
  chartDefaults();
  wireNav();
  catalog = await loadIndex();
  const initial = fillDateSelect(selectedDateFromUrl());
  wireDateSelect();
  await renderDesk(initial);
} catch (err) {
  document.getElementById("meta").textContent = `Failed to load pack: ${err.message}`;
}
