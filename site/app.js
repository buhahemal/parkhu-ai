// Prefer embedded data/ (Pages artifact). Never use ../output on github.io/repo.
const DATA_CANDIDATES = [
  "./data/research_pack.json",
  "https://raw.githubusercontent.com/buhahemal/parkhu-ai/main/output/latest/research_pack.json",
];

const CHART_COLORS = {
  ink: "#e7eee6",
  muted: "#7f9080",
  line: "#2a352e",
  accent: "#c4a35a",
  good: "#6fbf8a",
  warn: "#d4a15c",
  bad: "#d97b6c",
  bar: "#4a6b55",
};

const charts = [];

async function loadPack() {
  let lastErr;
  for (const url of DATA_CANDIDATES) {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error(`${url} → ${res.status}`);
      return { pack: JSON.parse(await res.text()), source: url };
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr || new Error("No research_pack.json found");
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
  Chart.defaults.font.family = "'IBM Plex Mono', monospace";
  Chart.defaults.font.size = 11;
}

function makeChart(canvas, config) {
  if (!window.Chart || !canvas) return null;
  const c = new Chart(canvas, config);
  charts.push(c);
  return c;
}

function renderHeader(pack, source) {
  const r = pack.regime || {};
  const badge = document.getElementById("regime-badge");
  const cls = trendClass(r.market_regime);
  badge.className = `badge ${cls}`;
  badge.textContent = r.market_regime || "—";

  document.getElementById("meta").replaceChildren(
    el("span", {}, el("strong", {}, "collection "), pack.collection_date || "—"),
    el("span", {}, el("strong", {}, "session "), pack.session_date || "—"),
    el(
      "span",
      {},
      el("strong", {}, "trading day "),
      pack.is_trading_day === false ? "no" : pack.is_trading_day ? "yes" : "—",
    ),
    el("span", {}, el("strong", {}, "as-of "), pack.generated_at_ist || r.generated_at_ist || "—"),
    el("span", {}, el("strong", {}, "kb "), pack.kb_version || "—"),
    el("span", {}, el("strong", {}, "source "), source.includes("data/") ? "artifact" : "raw"),
  );

  const a = pack.analytics || {};
  const book = a.book || {};
  const kpis = [
    ["regime", r.market_regime || "—", trendClass(r.market_regime)],
    ["india vix", fmt(r.india_vix, 2), ""],
    ["open book", fmt(book.open ?? (pack.ledger?.open || []).length, 0), ""],
    ["needs action", fmt(book.needs_action ?? (pack.ledger?.needs_action || []).length, 0), book.needs_action ? "warn" : ""],
    ["new ideas", fmt(a.ideas_count ?? (pack.ideas || []).length, 0), ""],
    ["score coverage", a.score_coverage_pct != null ? `${fmt(a.score_coverage_pct, 1)}%` : "—", ""],
    ["avg mfe %", fmt(book.avg_mfe_pct), book.avg_mfe_pct > 0 ? "bull" : ""],
    ["avg mae %", fmt(book.avg_mae_pct), book.avg_mae_pct < 0 ? "bear" : ""],
  ];
  document.getElementById("kpi").replaceChildren(
    ...kpis.map(([label, val, cls]) =>
      el("div", { class: "cell" }, el("span", {}, label), el("b", { class: cls }, val)),
    ),
  );
}

function renderFunnel(pack) {
  const steps = pack.analytics?.funnel_conversions || [];
  const funnel = steps.length
    ? steps
    : (pack.funnel || []).map((s, i, arr) => ({
        gate: s.gate,
        surviving: s.surviving,
        keep_pct: i === 0 || !arr[i - 1]?.surviving
          ? null
          : round(100 * s.surviving / arr[i - 1].surviving, 1),
        dropped:
          i === 0 ? null : Math.max((arr[i - 1]?.surviving || 0) - (s.surviving || 0), 0),
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
          backgroundColor: CHART_COLORS.bar,
          borderWidth: 0,
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
        x: { grid: { color: CHART_COLORS.line }, ticks: { color: CHART_COLORS.muted } },
        y: { grid: { display: false }, ticks: { color: CHART_COLORS.ink, font: { size: 10 } } },
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

function round(n, d) {
  return Math.round(n * 10 ** d) / 10 ** d;
}

function renderRegime(pack) {
  const r = pack.regime || {};
  const items = [
    ["nifty", `${fmt(r.nifty_trend)} (${fmt(r.nifty_pct_change)}%)`, trendClass(r.nifty_trend)],
    ["banknifty", `${fmt(r.banknifty_trend)} (${fmt(r.banknifty_pct_change)}%)`, trendClass(r.banknifty_trend)],
    ["vix level", fmt(r.vix_level, 0), ""],
    ["overall risk", fmt(r.overall_risk, 0), ""],
    ["global risk", fmt(r.global_risk, 0), ""],
    ["best sector", `${fmt(r.best_sector, 0)} (${fmt(r.best_sector_perf_1m)}%)`, "bull"],
    ["worst sector", `${fmt(r.worst_sector, 0)} (${fmt(r.worst_sector_perf_1m)}%)`, "bear"],
    ["crude", `${fmt(r.crude)} (${fmt(r.crude_pct_change)}%)`, ""],
    ["usdinr", `${fmt(r.usdinr)} (${fmt(r.usdinr_pct_change)}%)`, ""],
  ];
  document.getElementById("regime-stats").replaceChildren(
    ...items.map(([k, v, cls]) =>
      el("div", { class: "stat" }, el("dt", {}, k), el("dd", { class: cls }, v)),
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
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        title: { display: true, text: "Institutional flow (₹ cr)", color: CHART_COLORS.muted },
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
    ["US (S&P)", (r.us_sp500_pct ?? 0) > 0.15 ? "Bullish" : (r.us_sp500_pct ?? 0) < -0.15 ? "Bearish" : "Neutral"],
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
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        title: { display: true, text: "Global cues (−1 / 0 / +1)", color: CHART_COLORS.muted },
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
}

function renderIdeas(pack) {
  const body = document.getElementById("ideas-body");
  const ideas = pack.ideas || [];
  if (!ideas.length) {
    body.replaceChildren(el("p", { class: "empty" }, "No new ideas cleared the gates."));
    makeChart(document.getElementById("scores-chart"), {
      type: "bar",
      data: { labels: [], datasets: [] },
      options: { plugins: { title: { display: true, text: "Idea scores", color: CHART_COLORS.muted } } },
    });
    return;
  }

  makeChart(document.getElementById("scores-chart"), {
    type: "bar",
    data: {
      labels: ideas.map((i) => i.symbol),
      datasets: [
        {
          label: "Parkhu score",
          data: ideas.map((i) => i.parkhu_score),
          backgroundColor: CHART_COLORS.accent,
          borderWidth: 0,
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        title: { display: true, text: "Scores (no capital sizing)", color: CHART_COLORS.muted },
      },
      scales: {
        x: { min: 0, max: 100, grid: { color: CHART_COLORS.line } },
        y: { grid: { display: false } },
      },
    },
  });

  const table = el("table");
  table.append(
    el(
      "thead",
      {},
      el(
        "tr",
        {},
        ...["Symbol", "Band", "Score", "Entry", "Stop", "T1", "R:R", "Hold d"].map((h) => el("th", {}, h)),
      ),
    ),
  );
  const tbody = el("tbody");
  for (const idea of ideas) {
    const lv = idea.levels || {};
    const band = String(idea.band || "").toLowerCase();
    tbody.append(
      el(
        "tr",
        {},
        el(
          "td",
          { "data-label": "Symbol" },
          idea.symbol || "—",
          el("div", { class: "muted" }, idea.risk_sector || ""),
        ),
        el("td", { "data-label": "Band" }, el("span", { class: `band ${band}` }, idea.band || "—")),
        el("td", { class: "num", "data-label": "Score" }, fmt(idea.parkhu_score, 1)),
        el("td", { class: "num", "data-label": "Entry" }, fmt(lv.entry)),
        el("td", { class: "num", "data-label": "Stop" }, fmt(lv.stop)),
        el("td", { class: "num", "data-label": "T1" }, fmt(lv.t1)),
        el("td", { class: "num", "data-label": "R:R" }, fmt(lv.rr_t1)),
        el("td", { class: "num", "data-label": "Hold d" }, fmt(lv.hold_days_t1, 0)),
      ),
    );
  }
  table.append(tbody);
  body.replaceChildren(table);
}

function renderLedger(pack) {
  const rows = pack.ledger?.open || [];
  const actions = pack.ledger?.needs_action || [];
  const actionRoot = document.getElementById("action-body");
  if (!actions.length) {
    actionRoot.replaceChildren(el("p", { class: "empty" }, "No positions flagged for action."));
  } else {
    actionRoot.replaceChildren(
      ...actions.map((r) =>
        el(
          "div",
          { class: "item" },
          el("strong", {}, r.symbol || "?"),
          ` — ${r.action || "ACTION"}: ${r.detail || ""}`,
        ),
      ),
    );
  }

  const body = document.getElementById("ledger-body");
  if (!rows.length) {
    body.replaceChildren(el("p", { class: "empty" }, "No open suggestions."));
    return;
  }

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
        },
        {
          label: "MAE %",
          data: rows.map((r) => r.mae_pct ?? 0),
          backgroundColor: CHART_COLORS.bad,
          borderWidth: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        title: { display: true, text: "Excursion (MFE / MAE %)", color: CHART_COLORS.muted },
      },
      scales: {
        x: { grid: { display: false }, ticks: { maxRotation: 45, minRotation: 0 } },
        y: { grid: { color: CHART_COLORS.line } },
      },
    },
  });

  const table = el("table");
  table.append(
    el(
      "thead",
      {},
      el(
        "tr",
        {},
        ...["Symbol", "Opened", "Entry", "Last", "P&L %", "MFE", "MAE"].map((h) => el("th", {}, h)),
      ),
    ),
  );
  const tbody = el("tbody");
  for (const r of rows) {
    let pnl = null;
    if (r.entry && r.last_price != null) {
      pnl = ((r.last_price - r.entry) / r.entry) * 100;
    }
    tbody.append(
      el(
        "tr",
        {},
        el("td", { "data-label": "Symbol" }, r.symbol || "—"),
        el("td", { class: "num", "data-label": "Opened" }, r.date_opened || "—"),
        el("td", { class: "num", "data-label": "Entry" }, fmt(r.entry)),
        el("td", { class: "num", "data-label": "Last" }, fmt(r.last_price)),
        el("td", { class: "num", "data-label": "P&L %" }, fmt(pnl)),
        el("td", { class: "num", "data-label": "MFE" }, fmt(r.mfe_pct)),
        el("td", { class: "num", "data-label": "MAE" }, fmt(r.mae_pct)),
      ),
    );
  }
  table.append(tbody);
  body.replaceChildren(table);
}

function renderSectors(pack) {
  const sectors = pack.analytics?.sector_counts || [];
  const canvas = document.getElementById("sector-chart");
  if (!sectors.length) {
    canvas.parentElement.replaceChildren(el("p", { class: "empty" }, "No sector counts."));
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
          backgroundColor: CHART_COLORS.bar,
          borderWidth: 0,
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
  const root = document.getElementById("quality-body");
  const cov =
    a.score_coverage_pct != null
      ? el("div", { class: "cov" }, `Score coverage: ${fmt(a.score_coverage_pct, 1)}% of KB-14 weights live`)
      : null;
  if (!caveats.length) {
    root.replaceChildren(cov || el("p", { class: "empty" }, "No caveats listed."), el("p", { class: "muted" }, "Capital & deployment live in Claude — omitted from this desk."));
    return;
  }
  root.replaceChildren(
    cov,
    el(
      "ul",
      { class: "quality" },
      ...caveats.map((c) => el("li", {}, c)),
    ),
    el("p", { class: "muted" }, "Capital & fund deployment are tracked in Claude, not on this desk."),
  );
}

function renderLinks(pack) {
  const urls = pack.urls || {};
  const deep = urls.deep_dive || {};
  const items = [
    ["Pack (md)", urls.pack_md],
    ["Pack (json)", urls.pack_json],
    ["Brief", urls.brief_md],
    ["stock_analysis", deep["stock_analysis.csv"]?.latest_url],
    ["Latest folder", urls.latest_folder],
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

try {
  await waitForChart();
  chartDefaults();
  const { pack, source } = await loadPack();
  renderHeader(pack, source);
  renderFunnel(pack);
  renderRegime(pack);
  renderIdeas(pack);
  renderLedger(pack);
  renderSectors(pack);
  renderQuality(pack);
  renderLinks(pack);
} catch (err) {
  document.getElementById("meta").textContent = `Failed to load pack: ${err.message}`;
}
