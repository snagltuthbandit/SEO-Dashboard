"""Generates output/dashboard.html from the SQLite DB. No server needed —
Chart.js loaded via CDN, all data embedded as JSON, vanilla JS for
sorting/filtering/expand-row interactivity.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db, parser

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "output" / "dashboard.html"


def _fetch_all(conn):
    rows = conn.execute(
        """
        SELECT r.id AS run_id, r.run_date, r.prompt_id, r.prompt_text, r.engine,
               r.raw_response, m.entity_name, m.mentioned, m.position,
               m.is_recommended, m.mention_count
        FROM runs r
        JOIN mentions m ON m.run_id = r.id
        ORDER BY r.run_date ASC, r.id ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def build_data(conn, brand_name: str, entity_order: list, brand_terms: list) -> dict:
    rows = _fetch_all(conn)
    run_dates = sorted(set(r["run_date"] for r in rows))

    # --- headline: brand mention rate, this run_date vs prior run_date ---
    this_week = run_dates[-1] if run_dates else None
    prior_week = run_dates[-2] if len(run_dates) > 1 else None

    def brand_rate_for_date(rd):
        brand_rows = [r for r in rows if r["run_date"] == rd and r["entity_name"] == brand_name]
        if not brand_rows:
            return None
        return sum(r["mentioned"] for r in brand_rows) / len(brand_rows)

    this_week_rate = brand_rate_for_date(this_week) if this_week else None
    prior_week_rate = brand_rate_for_date(prior_week) if prior_week else None
    delta = (
        this_week_rate - prior_week_rate
        if this_week_rate is not None and prior_week_rate is not None
        else None
    )

    # --- trend: brand mention rate per engine, over all run_dates ---
    engines = sorted(set(r["engine"] for r in rows))
    trend_series = {}
    for engine in engines:
        series = []
        for rd in run_dates:
            subset = [
                r
                for r in rows
                if r["run_date"] == rd and r["engine"] == engine and r["entity_name"] == brand_name
            ]
            rate = (sum(r["mentioned"] for r in subset) / len(subset)) if subset else None
            series.append(rate)
        trend_series[engine] = series

    # --- per-run detail: one entry per (prompt, engine), with every entity's
    # mention record nested. This is the pivot the client uses for the entity
    # switcher, the gap view, and both share-of-voice modes. ---
    runs_detail = {}
    for rd in run_dates:
        # group this run's rows by (prompt_id, engine)
        by_pe = {}
        for r in rows:
            if r["run_date"] != rd:
                continue
            key = (r["prompt_id"], r["engine"])
            if key not in by_pe:
                by_pe[key] = {
                    "prompt_id": r["prompt_id"],
                    "prompt_text": r["prompt_text"],
                    "engine": r["engine"],
                    "raw_response": r["raw_response"],
                    "mentions": {},
                }
            by_pe[key]["mentions"][r["entity_name"]] = {
                "mentioned": r["mentioned"],
                "position": r["position"],
                "is_recommended": r["is_recommended"],
                "mention_count": r["mention_count"],
            }
        runs_detail[rd] = list(by_pe.values())

    return {
        "brand_name": brand_name,
        "brand_terms": brand_terms,
        "entities": entity_order,
        "run_dates": run_dates,
        "headline": {
            "this_week": this_week,
            "prior_week": prior_week,
            "this_week_rate": this_week_rate,
            "prior_week_rate": prior_week_rate,
            "delta": delta,
        },
        "trend": {"dates": run_dates, "series": trend_series},
        "runs": runs_detail,
        "has_data": len(rows) > 0,
    }


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>__BRAND_NAME__ — AI Citation Tracker</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    margin: 0; padding: 32px; background: #f6f7f9; color: #1c1e21;
  }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .subtitle { color: #666; font-size: 13px; margin-bottom: 24px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 20px; margin-bottom: 24px; }
  .card { background: #fff; border: 1px solid #e2e4e8; border-radius: 10px; padding: 20px; }
  .card h2 { font-size: 14px; text-transform: uppercase; letter-spacing: .04em; color: #666; margin: 0 0 12px; }
  .card-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 12px; }
  .card-head h2 { margin: 0; }
  .headline-number { font-size: 42px; font-weight: 700; line-height: 1; }
  .headline-delta { font-size: 15px; margin-top: 8px; }
  .up { color: #1a7f37; }
  .down { color: #cf222e; }
  .flat { color: #666; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #eee; }
  th { cursor: pointer; user-select: none; color: #444; background: #fafbfc; position: sticky; top: 0; }
  th:hover { background: #f0f1f3; }
  tr.data-row { cursor: pointer; }
  tr.data-row:hover { background: #f9fafb; }
  tr.detail-row td { background: #fbfbfc; white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; padding: 14px; max-height: 400px; overflow-y: auto; cursor: default; }
  tr.detail-row mark { background: #fff3ba; padding: 0 1px; border-radius: 2px; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 600; }
  .badge.yes { background: #dafbe1; color: #1a7f37; }
  .badge.no { background: #f0f1f3; color: #666; }
  .badge.pos-first { background: #dafbe1; color: #1a7f37; }
  .badge.pos-early { background: #e8f5e0; color: #3f7f2f; }
  .badge.pos-mid { background: #fff3ba; color: #8a6d00; }
  .badge.pos-late { background: #fbe0d0; color: #9a4a1a; }
  .controls { margin-bottom: 12px; display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
  select, input[type=text] { padding: 6px 10px; border: 1px solid #d0d2d6; border-radius: 6px; font-size: 13px; }
  button.btn { padding: 6px 12px; border: 1px solid #d0d2d6; border-radius: 6px; font-size: 13px; background: #fff; cursor: pointer; }
  button.btn:hover { background: #f0f1f3; }
  .toggle { display: inline-flex; border: 1px solid #d0d2d6; border-radius: 6px; overflow: hidden; font-size: 12px; }
  .toggle button { border: 0; background: #fff; padding: 5px 10px; cursor: pointer; color: #444; }
  .toggle button.active { background: #2563eb; color: #fff; }
  .full-width { grid-column: 1 / -1; }
  .empty-state { color: #888; font-size: 14px; padding: 20px 0; }
  .table-note { color: #8a6d00; background: #fff8e1; border: 1px solid #f3e2a0; border-radius: 6px; padding: 8px 12px; font-size: 13px; margin-bottom: 12px; }
  canvas { max-height: 280px; }
  .baseline-note { color: #666; font-size: 14px; line-height: 1.5; padding: 40px 8px; text-align: center; }
  .baseline-big { font-size: 18px; font-weight: 600; color: #1c1e21; margin-bottom: 8px; }
  .spacer { flex: 1; }
</style>
</head>
<body>

<h1>__BRAND_NAME__ — AI Citation Tracker</h1>
<div class="subtitle">Generated __GENERATED_AT__</div>

<div id="empty-state" class="empty-state" style="display:none;">
  No data yet. Run <code>src/runner.py</code> at least once to populate this dashboard.
</div>

<div id="dashboard-content">
  <div class="grid">
    <div class="card">
      <h2>Mention rate this run</h2>
      <div id="headline-number" class="headline-number">—</div>
      <div id="headline-delta" class="headline-delta"></div>
    </div>
    <div class="card">
      <h2>Mention rate trend by engine</h2>
      <canvas id="trend-chart"></canvas>
      <div id="trend-baseline" class="baseline-note" style="display:none;">
        <div class="baseline-big">Baseline week</div>
        <div>This is your first run. The week-over-week trend line appears here
        once a second run is collected.</div>
      </div>
    </div>
    <div class="card">
      <div class="card-head">
        <h2>Share of voice</h2>
        <div class="toggle" id="sov-toggle">
          <button data-mode="count" class="active">Mention count</button>
          <button data-mode="weighted">Visibility score</button>
        </div>
      </div>
      <canvas id="sov-chart"></canvas>
    </div>
  </div>

  <div class="card full-width">
    <h2 id="table-title">Prompt-level detail</h2>
    <div class="controls">
      <select id="filter-date" title="Run date"></select>
      <select id="filter-view" title="Entity / view"></select>
      <select id="filter-engine"><option value="">All engines</option></select>
      <select id="filter-mentioned">
        <option value="">Mentioned: all</option>
        <option value="Y">Mentioned: Yes</option>
        <option value="N">Mentioned: No</option>
      </select>
      <input type="text" id="filter-text" placeholder="Filter by prompt text...">
      <span class="spacer"></span>
      <button class="btn" id="export-csv">Export CSV</button>
    </div>
    <div id="table-note" class="table-note" style="display:none;"></div>
    <table id="prompt-table">
      <thead id="prompt-table-head"></thead>
      <tbody id="prompt-table-body"></tbody>
    </table>
  </div>
</div>

<script>
const DATA = __DATA_JSON__;

// Position -> visibility weight. Being named first is worth far more than being
// buried last; "mentioned Y/N" alone hides that. Used by the Visibility score
// share-of-voice mode.
const POSITION_WEIGHT = { first: 1.0, early: 0.7, mid: 0.4, late: 0.2, not_mentioned: 0 };
const GAPS = "__gaps__";

const state = {
  date: DATA.run_dates.length ? DATA.run_dates[DATA.run_dates.length - 1] : null,
  view: DATA.brand_name,   // an entity name, or GAPS
  sovMode: "count",
  sortKey: null,
  sortAsc: true,
};

let sovChart = null;

function pct(x) { return x === null || x === undefined ? "—" : (x * 100).toFixed(0) + "%"; }

function currentRows() { return DATA.runs[state.date] || []; }

function renderHeadline() {
  const h = DATA.headline;
  document.getElementById("headline-number").textContent = pct(h.this_week_rate);
  const deltaEl = document.getElementById("headline-delta");
  if (h.delta === null) {
    deltaEl.textContent = h.prior_week ? "" : "No prior run to compare yet";
    deltaEl.className = "headline-delta flat";
  } else {
    const pts = (h.delta * 100).toFixed(0);
    const sign = h.delta > 0 ? "+" : "";
    deltaEl.textContent = `${sign}${pts} pts vs prior run (${h.prior_week})`;
    deltaEl.className = "headline-delta " + (h.delta > 0 ? "up" : h.delta < 0 ? "down" : "flat");
  }
}

function renderTrend() {
  const ctx = document.getElementById("trend-chart");
  // With a single run there's no line to draw — a lone dot reads as broken.
  // Show an intentional baseline note instead until a second run exists.
  if (DATA.trend.dates.length < 2) {
    ctx.style.display = "none";
    document.getElementById("trend-baseline").style.display = "block";
    return;
  }
  const colors = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c"];
  const datasets = Object.entries(DATA.trend.series).map(([engine, series], i) => ({
    label: engine,
    data: series.map(v => v === null ? null : v * 100),
    borderColor: colors[i % colors.length],
    backgroundColor: colors[i % colors.length],
    spanGaps: true,
    tension: 0.25,
  }));
  new Chart(ctx, {
    type: "line",
    data: { labels: DATA.trend.dates, datasets },
    options: {
      scales: { y: { min: 0, max: 100, ticks: { callback: v => v + "%" } } },
      plugins: { legend: { position: "bottom" } },
    },
  });
}

// Share-of-voice value per entity for the selected run, in either mode.
function sovValues(mode) {
  const totals = {};
  DATA.entities.forEach(e => { totals[e] = 0; });
  currentRows().forEach(row => {
    DATA.entities.forEach(e => {
      const m = row.mentions[e];
      if (!m) return;
      if (mode === "weighted") totals[e] += POSITION_WEIGHT[m.position] || 0;
      else totals[e] += m.mention_count;
    });
  });
  return DATA.entities.map(e => totals[e]);
}

function renderSov() {
  const ctx = document.getElementById("sov-chart");
  const isBrand = DATA.entities.map(l => l === DATA.brand_name);
  const values = sovValues(state.sovMode);
  const rounded = values.map(v => Math.round(v * 10) / 10);
  if (sovChart) sovChart.destroy();
  sovChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: DATA.entities,
      datasets: [{
        data: rounded,
        backgroundColor: isBrand.map(b => b ? "#2563eb" : "#c7cad1"),
      }],
    },
    options: {
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { title: items => items[0].label,
          label: item => state.sovMode === "weighted"
            ? `Visibility score: ${item.raw}` : `Mentions: ${item.raw}` } },
      },
      scales: { x: { ticks: { autoSkip: false, maxRotation: 40, minRotation: 0 } } },
    },
  });
}

function posBadge(position) {
  const cls = { first: "pos-first", early: "pos-early", mid: "pos-mid", late: "pos-late" }[position] || "no";
  return `<span class="badge ${cls}">${position}</span>`;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Highlight brand name/aliases/domain inside the raw response so a reviewer
// can eyeball parser accuracy at a glance (supports the "spot-check ~10
// responses" success criterion).
function highlightBrand(text) {
  let html = escapeHtml(text);
  const terms = (DATA.brand_terms || []).filter(Boolean)
    .sort((a, b) => b.length - a.length)
    .map(t => t.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&"));
  if (!terms.length) return html;
  const re = new RegExp("(" + terms.join("|") + ")", "gi");
  return html.replace(re, "<mark>$1</mark>");
}

// Build the flat rows the table renders, depending on the selected view.
function tableModel() {
  const rows = currentRows();
  if (state.view === GAPS) {
    const brand = DATA.brand_name;
    const competitors = DATA.entities.filter(e => e !== brand);
    const out = [];
    rows.forEach(row => {
      const brandM = row.mentions[brand];
      if (brandM && brandM.mentioned) return;   // brand present -> not a gap
      const present = competitors.filter(c => row.mentions[c] && row.mentions[c].mentioned);
      if (!present.length) return;               // no competitor either -> skip
      out.push({
        prompt_id: row.prompt_id, prompt_text: row.prompt_text, engine: row.engine,
        competitors: present.join(", "), raw_response: row.raw_response,
      });
    });
    return { mode: "gaps", rows: out };
  }
  const entity = state.view;
  const out = rows.map(row => {
    const m = row.mentions[entity] || { mentioned: 0, position: "not_mentioned", is_recommended: 0, mention_count: 0 };
    return {
      prompt_id: row.prompt_id, prompt_text: row.prompt_text, engine: row.engine,
      mentioned: m.mentioned ? "Y" : "N", position: m.position,
      recommended: m.is_recommended ? "Y" : "N", mention_count: m.mention_count,
      raw_response: row.raw_response,
    };
  });
  return { mode: "entity", rows: out };
}

function applyFilters(rows) {
  const engine = document.getElementById("filter-engine").value;
  const mentioned = document.getElementById("filter-mentioned").value;
  const text = document.getElementById("filter-text").value.toLowerCase();
  let out = rows.filter(r =>
    (!engine || r.engine === engine) &&
    (!mentioned || r.mentioned === mentioned) &&
    (!text || r.prompt_text.toLowerCase().includes(text))
  );
  if (state.sortKey) {
    out = out.slice().sort((a, b) => {
      let av = a[state.sortKey], bv = b[state.sortKey];
      if (typeof av === "string") { av = av.toLowerCase(); bv = bv.toLowerCase(); }
      if (av < bv) return state.sortAsc ? -1 : 1;
      if (av > bv) return state.sortAsc ? 1 : -1;
      return 0;
    });
  }
  return out;
}

const COLS = {
  entity: [
    { key: "prompt_text", label: "Prompt" },
    { key: "engine", label: "Engine" },
    { key: "mentioned", label: "Mentioned" },
    { key: "position", label: "Position" },
    { key: "recommended", label: "Recommended" },
    { key: "mention_count", label: "# Mentions" },
  ],
  gaps: [
    { key: "prompt_text", label: "Prompt" },
    { key: "engine", label: "Engine" },
    { key: "competitors", label: "Competitors present" },
  ],
};

function renderTableHead(mode) {
  const thead = document.getElementById("prompt-table-head");
  thead.innerHTML = "<tr>" + COLS[mode].map(c => `<th data-key="${c.key}">${c.label}</th>`).join("") + "</tr>";
  thead.querySelectorAll("th[data-key]").forEach(th => {
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      if (state.sortKey === key) { state.sortAsc = !state.sortAsc; }
      else { state.sortKey = key; state.sortAsc = true; }
      renderTable();
    });
  });
}

function cellHtml(mode, r, key) {
  if (key === "mentioned" || key === "recommended")
    return `<span class="badge ${r[key] === 'Y' ? 'yes' : 'no'}">${r[key]}</span>`;
  if (key === "position") return posBadge(r.position);
  return escapeHtml(String(r[key]));
}

function renderTable() {
  const model = tableModel();
  renderTableHead(model.mode);
  const colspan = COLS[model.mode].length;

  const note = document.getElementById("table-note");
  if (model.mode === "gaps") {
    note.style.display = "block";
    note.textContent = `Showing prompts where ${DATA.brand_name} is absent but at least one competitor appears — these are your content-gap targets.`;
  } else {
    note.style.display = "none";
  }
  document.getElementById("table-title").textContent =
    model.mode === "gaps" ? "Content gaps — where a competitor appears and " + DATA.brand_name + " does not"
                          : "Prompt-level detail — " + state.view;

  // mentioned filter is meaningless in gaps mode
  document.getElementById("filter-mentioned").disabled = model.mode === "gaps";

  const tbody = document.getElementById("prompt-table-body");
  tbody.innerHTML = "";
  const rows = applyFilters(model.rows);

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="${colspan}" style="color:#888;padding:16px;">No rows match.</td></tr>`;
    return;
  }

  rows.forEach(r => {
    const tr = document.createElement("tr");
    tr.className = "data-row";
    tr.innerHTML = COLS[model.mode].map(c => `<td>${cellHtml(model.mode, r, c.key)}</td>`).join("");

    const detailTr = document.createElement("tr");
    detailTr.className = "detail-row";
    detailTr.style.display = "none";
    const td = document.createElement("td");
    td.colSpan = colspan;
    td.innerHTML = highlightBrand(r.raw_response || "");
    detailTr.appendChild(td);

    tr.addEventListener("click", () => {
      detailTr.style.display = detailTr.style.display === "none" ? "table-row" : "none";
    });
    tbody.appendChild(tr);
    tbody.appendChild(detailTr);
  });
}

function exportCsv() {
  const model = tableModel();
  const rows = applyFilters(model.rows);
  const cols = COLS[model.mode];
  const esc = v => `"${String(v).replace(/"/g, '""')}"`;
  const lines = [cols.map(c => esc(c.label)).join(",")];
  rows.forEach(r => lines.push(cols.map(c => esc(r[c.key])).join(",")));
  const blob = new Blob([lines.join("\\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `citations_${state.date}_${state.view === GAPS ? "gaps" : state.view.replace(/\\s+/g, "_")}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function populateControls() {
  const dateSel = document.getElementById("filter-date");
  DATA.run_dates.slice().reverse().forEach(d => {
    const o = document.createElement("option");
    o.value = d; o.textContent = d;
    dateSel.appendChild(o);
  });
  dateSel.value = state.date;

  const viewSel = document.getElementById("filter-view");
  DATA.entities.forEach(e => {
    const o = document.createElement("option");
    o.value = e; o.textContent = e === DATA.brand_name ? e + " (brand)" : e;
    viewSel.appendChild(o);
  });
  const gapOpt = document.createElement("option");
  gapOpt.value = GAPS; gapOpt.textContent = "\\u26a0 Gaps (brand missing, competitor present)";
  viewSel.appendChild(gapOpt);
  viewSel.value = state.view;

  const engines = [...new Set(currentRows().map(r => r.engine))].sort();
  const engSel = document.getElementById("filter-engine");
  engines.forEach(e => {
    const o = document.createElement("option");
    o.value = e; o.textContent = e;
    engSel.appendChild(o);
  });

  dateSel.addEventListener("change", () => { state.date = dateSel.value; renderSov(); renderTable(); });
  viewSel.addEventListener("change", () => { state.view = viewSel.value; state.sortKey = null; renderTable(); });
  engSel.addEventListener("change", renderTable);
  document.getElementById("filter-mentioned").addEventListener("change", renderTable);
  document.getElementById("filter-text").addEventListener("input", renderTable);
  document.getElementById("export-csv").addEventListener("click", exportCsv);

  document.querySelectorAll("#sov-toggle button").forEach(b => {
    b.addEventListener("click", () => {
      state.sovMode = b.dataset.mode;
      document.querySelectorAll("#sov-toggle button").forEach(x => x.classList.toggle("active", x === b));
      renderSov();
    });
  });
}

if (!DATA.has_data) {
  document.getElementById("empty-state").style.display = "block";
  document.getElementById("dashboard-content").style.display = "none";
} else {
  renderHeadline();
  renderTrend();
  populateControls();
  renderSov();
  renderTable();
}
</script>
</body>
</html>
"""


def render_html(data: dict, generated_at: str) -> str:
    html = HTML_TEMPLATE
    html = html.replace("__BRAND_NAME__", data["brand_name"])
    html = html.replace("__GENERATED_AT__", generated_at)
    html = html.replace("__DATA_JSON__", json.dumps(data))
    return html


def generate():
    from datetime import datetime

    entities = parser.load_entities()
    brand = entities[0]
    brand_name = brand["name"]
    entity_order = [e["name"] for e in entities]
    brand_terms = [brand_name] + list(brand.get("aliases", []))
    if brand.get("domain"):
        brand_terms.append(brand["domain"])

    db.init_db()
    conn = db.get_connection()
    try:
        data = build_data(conn, brand_name, entity_order, brand_terms)
    finally:
        conn.close()

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = render_html(data, generated_at)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html)
    print(f"Dashboard written to {OUTPUT_PATH}")


if __name__ == "__main__":
    generate()
