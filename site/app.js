// Prefer embedded data/ (Pages artifact). Never use ../output — on
// https://user.github.io/repo/ that resolves outside the project (404).
const DATA_CANDIDATES = [
  "./data/research_pack.json",
  "https://raw.githubusercontent.com/buhahemal/parkhu-ai/main/output/latest/research_pack.json",
];

async function loadPack() {
  let lastErr;
  for (const url of DATA_CANDIDATES) {
    try {
      const res = await fetch(url, { cache: "no-store" });
      if (!res.ok) throw new Error(`${url} → ${res.status}`);
      const text = await res.text();
      return { pack: JSON.parse(text), source: url };
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
    else if (k === "html") node.innerHTML = v;
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
  return "";
}

function renderMeta(pack, source) {
  const root = document.getElementById("meta");
  root.replaceChildren(
    el("span", {}, el("strong", {}, "collection "), pack.collection_date || "—"),
    el("span", {}, el("strong", {}, "session "), pack.session_date || "—"),
    el(
      "span",
      {},
      el("strong", {}, "trading day "),
      pack.is_trading_day === false ? "no" : pack.is_trading_day ? "yes" : "—",
    ),
    el("span", {}, el("strong", {}, "generated "), pack.generated_at_ist || "—"),
    el("span", {}, el("strong", {}, "source "), source),
  );
}

function renderRegime(pack) {
  const r = pack.regime || {};
  const items = [
    ["regime", r.market_regime, trendClass(r.market_regime)],
    ["nifty", `${fmt(r.nifty_trend)} (${fmt(r.nifty_pct_change)}%)`, trendClass(r.nifty_trend)],
    ["india vix", `${fmt(r.india_vix)} · ${fmt(r.vix_level, 0)}`, ""],
    ["fii net", fmt(r.fii_net, 0), ""],
    ["dii net", fmt(r.dii_net, 0), ""],
    ["overall risk", fmt(r.overall_risk, 0), ""],
    ["deployed %", fmt((pack.portfolio || {}).capital_deployed_pct), ""],
    ["open ideas", fmt((pack.portfolio || {}).ideas_count ?? (pack.ideas || []).length, 0), ""],
  ];
  const body = document.getElementById("regime-body");
  body.replaceChildren(
    ...items.map(([k, v, cls]) =>
      el("div", { class: "stat" }, el("dt", {}, k), el("dd", { class: cls }, v)),
    ),
  );
}

function renderIdeas(pack) {
  const body = document.getElementById("ideas-body");
  const ideas = pack.ideas || [];
  if (!ideas.length) {
    body.replaceChildren(el("p", { class: "empty" }, "No new ideas cleared the gates."));
    return;
  }
  const table = el("table");
  table.append(
    el(
      "thead",
      {},
      el(
        "tr",
        {},
        ...["Symbol", "Band", "Score", "Entry", "Stop", "T1", "Qty", "Risk ₹"].map((h) =>
          el("th", {}, h),
        ),
      ),
    ),
  );
  const tbody = el("tbody");
  for (const idea of ideas) {
    const lv = idea.levels || {};
    const sz = idea.sizing || {};
    const band = String(idea.band || "").toLowerCase();
    tbody.append(
      el(
        "tr",
        {},
        el("td", { "data-label": "Symbol" }, `${idea.symbol}`, el("div", { class: "muted" }, idea.risk_sector || "")),
        el(
          "td",
          { "data-label": "Band" },
          el("span", { class: `band ${band}` }, idea.band || "—"),
        ),
        el("td", { class: "num", "data-label": "Score" }, fmt(idea.parkhu_score, 1)),
        el("td", { class: "num", "data-label": "Entry" }, fmt(lv.entry)),
        el("td", { class: "num", "data-label": "Stop" }, fmt(lv.stop)),
        el("td", { class: "num", "data-label": "T1" }, fmt(lv.t1)),
        el("td", { class: "num", "data-label": "Qty" }, fmt(sz.qty, 0)),
        el("td", { class: "num", "data-label": "Risk ₹" }, fmt(sz.risk_rupees, 0)),
      ),
    );
  }
  table.append(tbody);
  body.replaceChildren(table);
}

function renderLedger(pack) {
  const body = document.getElementById("ledger-body");
  const rows = (pack.ledger || {}).open || [];
  if (!rows.length) {
    body.replaceChildren(el("p", { class: "empty" }, "No open suggestions."));
    return;
  }
  const table = el("table");
  table.append(
    el(
      "thead",
      {},
      el(
        "tr",
        {},
        ...["Symbol", "Opened", "Entry", "Last", "MFE %", "MAE %", "Status"].map((h) =>
          el("th", {}, h),
        ),
      ),
    ),
  );
  const tbody = el("tbody");
  for (const r of rows) {
    tbody.append(
      el(
        "tr",
        {},
        el("td", { "data-label": "Symbol" }, r.symbol || "—"),
        el("td", { class: "num", "data-label": "Opened" }, r.date_opened || "—"),
        el("td", { class: "num", "data-label": "Entry" }, fmt(r.entry)),
        el("td", { class: "num", "data-label": "Last" }, fmt(r.last_price)),
        el("td", { class: "num", "data-label": "MFE %" }, fmt(r.mfe_pct)),
        el("td", { class: "num", "data-label": "MAE %" }, fmt(r.mae_pct)),
        el("td", { "data-label": "Status" }, r.status || "—"),
      ),
    );
  }
  table.append(tbody);
  body.replaceChildren(table);
}

function renderAction(pack) {
  const body = document.getElementById("action-body");
  const rows = (pack.ledger || {}).needs_action || [];
  if (!rows.length) {
    body.replaceChildren(el("p", { class: "empty" }, "Nothing flagged for action."));
    return;
  }
  const list = el("div");
  for (const r of rows) {
    list.append(
      el(
        "p",
        {},
        el("strong", {}, r.symbol || "?"),
        ` — ${r.action || "ACTION"}: ${r.detail || ""}`,
      ),
    );
  }
  body.replaceChildren(list);
}

function renderFunnel(pack) {
  const body = document.getElementById("funnel-body");
  const steps = pack.funnel || [];
  if (!steps.length) {
    body.replaceChildren(el("p", { class: "empty" }, "No funnel data."));
    return;
  }
  body.replaceChildren(
    ...steps.map((s) =>
      el("span", { class: "chip" }, `${s.gate} · `, el("b", {}, String(s.surviving))),
    ),
  );
}

function renderLinks(pack) {
  const urls = pack.urls || {};
  const deep = urls.deep_dive || {};
  const items = [
    ["Research pack (md)", urls.pack_md],
    ["Research pack (json)", urls.pack_json],
    ["Index", urls.index],
    ["Brief", urls.brief_md],
    ["stock_analysis.csv", deep["stock_analysis.csv"]?.latest_url],
    ["Folder", urls.latest_folder],
  ].filter(([, href]) => href);
  const root = document.getElementById("links");
  root.replaceChildren(
    ...items.flatMap(([label, href], i) => {
      const a = el("a", { href, target: "_blank", rel: "noopener" }, label);
      return i ? [" · ", a] : [a];
    }),
  );
}

try {
  const { pack, source } = await loadPack();
  renderMeta(pack, source);
  renderRegime(pack);
  renderIdeas(pack);
  renderLedger(pack);
  renderAction(pack);
  renderFunnel(pack);
  renderLinks(pack);
} catch (err) {
  document.getElementById("meta").textContent = `Failed to load pack: ${err.message}`;
}
