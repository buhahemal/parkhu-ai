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
    out.push({
      gate: step.gate,
      surviving,
      from_prev: prev,
      keep_pct: keep,
      dropped,
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
  Chart.defaults.font.family = "'DM Sans', 'Segoe UI', sans-serif";
  Chart.defaults.font.size = 12;
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

function renderHeader(pack) {
  const r = pack.regime || {};
  const badge = document.getElementById("regime-badge");
  const cls = trendClass(r.market_regime);
  badge.className = `badge ${cls}`;
  badge.textContent = r.market_regime || "—";

  const asOf = pack.generated_at_ist || r.generated_at_ist || "—";
  const asOfShort = String(asOf).replace(/\+\d{2}:\d{2}$/, "").replace("T", " ").slice(0, 16);
  document.getElementById("meta").replaceChildren(
    el("span", {}, el("strong", {}, "Date "), pack.collection_date || "—"),
    el("span", {}, el("strong", {}, "Updated "), asOfShort),
  );

  const a = pack.analytics || {};
  const book = a.book || {};
  const kpis = [
    [
      "India VIX",
      fmt(r.india_vix, 1),
      "",
      "India VIX — fear/volatility. Rising VIX → cut aggression on new swings; falling/stable → environment more tradable.",
    ],
    [
      "Open book",
      fmt(book.open ?? (pack.ledger?.open || []).length, 0),
      "",
      "Open suggestions still being tracked. High count → focus on management before adding new ideas.",
    ],
    [
      "Needs action",
      fmt(book.needs_action ?? (pack.ledger?.needs_action || []).length, 0),
      book.needs_action ? "warn" : "",
      "Positions flagged (earnings, missing data, etc.). Decide these first — exit/reduce/stand aside before new risk.",
    ],
    [
      "New ideas",
      fmt(a.ideas_count ?? (pack.ideas || []).length, 0),
      "",
      "New names that cleared all gates today. Zero is OK. Use as Claude shortlist — not automatic buys.",
    ],
    [
      "Coverage",
      a.score_coverage_pct != null ? `${fmt(a.score_coverage_pct, 0)}%` : "—",
      a.score_coverage_pct != null && a.score_coverage_pct >= 70 ? "bull" : "",
      "Share of KB score weights that are live. Low coverage → treat scores as provisional; demand stronger setup quality.",
    ],
    [
      "Avg MFE",
      fmt(book.avg_mfe_pct, 1),
      book.avg_mfe_pct > 0 ? "bull" : "",
      "Average best favorable move on open book. Healthy MFE with weak P&L → review trailing / profit-taking rules.",
    ],
    [
      "Avg MAE",
      fmt(book.avg_mae_pct, 1),
      book.avg_mae_pct < 0 ? "bear" : "",
      "Average worst drawdown on open book. Deep MAE → check stops and whether entries were too early.",
    ],
    [
      "Risk",
      fmt(r.overall_risk, 0),
      "",
      "Overall market risk label from regime. Elevated risk → fewer new ideas, tighter process discipline.",
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
  document.getElementById("status-ribbon").replaceChildren(
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
  );
}

function renderFunnel(pack) {
  const steps = pack.analytics?.funnel_conversions || [];
  const funnel = steps.length
    ? steps
    : (pack.funnel || []).map((s, i, arr) => ({
        gate: s.gate,
        surviving: s.surviving,
        keep_pct:
          i === 0 || !arr[i - 1]?.surviving
            ? null
            : round((100 * s.surviving) / arr[i - 1].surviving, 1),
        dropped: i === 0 ? null : Math.max((arr[i - 1]?.surviving || 0) - (s.surviving || 0), 0),
      }));

  const drops = document.getElementById("funnel-drops");
  if (!funnel.length) {
    drops.replaceChildren(el("p", { class: "empty" }, "No funnel data."));
    return;
  }

  const labels = funnel.map((s) => String(s.gate || "").replace(/^(.{28}).+/, "$1…"));
  makeChart(document.getElementById("funnel-chart"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Surviving",
          data: funnel.map((s) => s.surviving),
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
        tooltip: {
          backgroundColor: CHART_COLORS.tooltipBg,
          titleColor: CHART_COLORS.ink,
          bodyColor: CHART_COLORS.muted,
          borderColor: CHART_COLORS.line,
          borderWidth: 1,
          callbacks: {
            afterBody(items) {
              const i = items[0]?.dataIndex;
              const s = funnel[i];
              if (!s) return "";
              const keep = s.keep_pct != null ? `Keep ${s.keep_pct}%` : "Universe";
              const drop = s.dropped != null ? ` · dropped ${s.dropped}` : "";
              return keep + drop;
            },
          },
        },
      },
      scales: {
        x: {
          grid: { color: CHART_COLORS.line },
          ticks: { color: CHART_COLORS.muted },
        },
        y: {
          grid: { display: false },
          ticks: { color: CHART_COLORS.ink, font: { size: 10 } },
        },
      },
    },
  });

  const hot = funnel
    .filter((s) => s.keep_pct != null && s.keep_pct < 50)
    .sort((a, b) => a.keep_pct - b.keep_pct)
    .slice(0, 4);
  drops.replaceChildren(
    el("span", { class: "chip" }, "Tightest gates:"),
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

  const cueMap = { Bullish: 1, Neutral: 0, Bearish: -1 };
  const cues = [
    ["Asia", r.asia_cue],
    ["Europe", r.europe_cue],
    [
      "US (S&P)",
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

  renderSentiment(cues);
}

function renderSentiment(cues) {
  const counts = { bull: 0, neutral: 0, bear: 0 };
  for (const [, label] of cues) {
    const t = trendClass(label);
    if (t === "bull") counts.bull += 1;
    else if (t === "bear") counts.bear += 1;
    else counts.neutral += 1;
  }
  const total = Math.max(counts.bull + counts.neutral + counts.bear, 1);
  const pct = (n) => Math.round((100 * n) / total);
  const root = document.getElementById("sentiment");
  root.replaceChildren(
    el(
      "div",
      { class: "bar", title: "Cue mix across Asia / Europe / US" },
      el("div", { class: "seg bull", style: `flex:${counts.bull || 0.001}` }),
      el("div", { class: "seg neutral", style: `flex:${counts.neutral || 0.001}` }),
      el("div", { class: "seg bear", style: `flex:${counts.bear || 0.001}` }),
    ),
    el(
      "div",
      { class: "legend" },
      el("span", {}, "Bullish ", el("b", {}, `${pct(counts.bull)}%`)),
      el("span", {}, "Neutral ", el("b", {}, `${pct(counts.neutral)}%`)),
      el("span", {}, "Bearish ", el("b", {}, `${pct(counts.bear)}%`)),
    ),
  );
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

  body.replaceChildren(
    ...ideas.map((idea) => {
      const lv = idea.levels || {};
      const band = String(idea.band || "").toLowerCase();
      return el(
        "article",
        { class: "card" },
        el(
          "div",
          { class: "title" },
          el("strong", {}, idea.symbol || "—"),
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
      );
    }),
  );
}

function renderActionItems(actions) {
  const nodes = !actions.length
    ? [el("p", { class: "empty" }, "No positions flagged for action.")]
    : actions.map((r) =>
        el(
          "div",
          { class: "item" },
          el("strong", {}, r.symbol || "?"),
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
            el("strong", {}, r.symbol || "?"),
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
        el("div", { class: "title" }, el("strong", {}, r.symbol || "—")),
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
  renderFunnel(pack);
  renderRegime(pack);
  renderIdeas(pack);
  renderLedger(pack);
  renderSectors(pack);
  renderQuality(pack);
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
