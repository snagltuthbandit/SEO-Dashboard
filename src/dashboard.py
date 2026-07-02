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


def build_data(conn, brand_name: str) -> dict:
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

    # --- share of voice: total mention_count per entity, latest run_date ---
    sov_rows = [r for r in rows if r["run_date"] == this_week] if this_week else []
    sov_totals = {}
    entity_order = []
    for r in sov_rows:
        if r["entity_name"] not in sov_totals:
            sov_totals[r["entity_name"]] = 0
            entity_order.append(r["entity_name"])
        sov_totals[r["entity_name"]] += r["mention_count"]

    # --- prompt-level table: brand mentions for latest run_date ---
    table_rows = []
    for r in sov_rows:
        if r["entity_name"] != brand_name:
            continue
        table_rows.append(
            {
                "prompt_id": r["prompt_id"],
                "prompt_text": r["prompt_text"],
                "engine": r["engine"],
                "mentioned": "Y" if r["mentioned"] else "N",
                "position": r["position"],
                "recommended": "Y" if r["is_recommended"] else "N",
                "mention_count": r["mention_count"],
                "raw_response": r["raw_response"],
            }
        )

    return {
        "brand_name": brand_name,
        "headline": {
            "this_week": this_week,
            "prior_week": prior_week,
            "this_week_rate": this_week_rate,
            "prior_week_rate": prior_week_rate,
            "delta": delta,
        },
        "trend": {"dates": run_dates, "series": trend_series},
        "share_of_voice": {
            "labels": entity_order,
            "counts": [sov_totals[e] for e in entity_order],
        },
        "prompt_table": table_rows,
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
  tr.detail-row td { background: #fbfbfc; white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; padding: 14px; max-height: 400px; overflow-y: auto; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 600; }
  .badge.yes { background: #dafbe1; color: #1a7f37; }
  .badge.no { background: #f0f1f3; color: #666; }
  .controls { margin-bottom: 12px; display: flex; gap: 10px; flex-wrap: wrap; }
  select, input[type=text] { padding: 6px 10px; border: 1px solid #d0d2d6; border-radius: 6px; font-size: 13px; }
  .full-width { grid-column: 1 / -1; }
  .empty-state { color: #888; font-size: 14px; padding: 20px 0; }
  canvas { max-height: 280px; }
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
    </div>
    <div class="card">
      <h2>Share of voice (this run, mention count)</h2>
      <canvas id="sov-chart"></canvas>
    </div>
  </div>

  <div class="card full-width">
    <h2>Prompt-level detail — __BRAND_NAME__ (this run)</h2>
    <div class="controls">
      <select id="filter-engine"><option value="">All engines</option></select>
      <select id="filter-mentioned">
        <option value="">Mentioned: all</option>
        <option value="Y">Mentioned: Yes</option>
        <option value="N">Mentioned: No</option>
      </select>
      <input type="text" id="filter-text" placeholder="Filter by prompt text...">
    </div>
    <table id="prompt-table">
      <thead>
        <tr>
          <th data-key="prompt_text">Prompt</th>
          <th data-key="engine">Engine</th>
          <th data-key="mentioned">Mentioned</th>
          <th data-key="position">Position</th>
          <th data-key="recommended">Recommended</th>
          <th data-key="mention_count"># Mentions</th>
        </tr>
      </thead>
      <tbody id="prompt-table-body"></tbody>
    </table>
  </div>
</div>

<script>
const DATA = __DATA_JSON__;

function pct(x) { return x === null || x === undefined ? "—" : (x * 100).toFixed(0) + "%"; }

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

function renderSov() {
  const ctx = document.getElementById("sov-chart");
  const isBrand = DATA.share_of_voice.labels.map(l => l === DATA.brand_name);
  new Chart(ctx, {
    type: "bar",
    data: {
      labels: DATA.share_of_voice.labels,
      datasets: [{
        data: DATA.share_of_voice.counts,
        backgroundColor: isBrand.map(b => b ? "#2563eb" : "#c7cad1"),
      }],
    },
    options: {
      plugins: { legend: { display: false } },
      scales: { x: { ticks: { autoSkip: false, maxRotation: 40, minRotation: 0 } } },
    },
  });
}

let sortKey = null, sortAsc = true;

function populateFilters() {
  const engines = [...new Set(DATA.prompt_table.map(r => r.engine))].sort();
  const sel = document.getElementById("filter-engine");
  engines.forEach(e => {
    const opt = document.createElement("option");
    opt.value = e; opt.textContent = e;
    sel.appendChild(opt);
  });
}

function getFilteredRows() {
  const engine = document.getElementById("filter-engine").value;
  const mentioned = document.getElementById("filter-mentioned").value;
  const text = document.getElementById("filter-text").value.toLowerCase();
  let rows = DATA.prompt_table.filter(r =>
    (!engine || r.engine === engine) &&
    (!mentioned || r.mentioned === mentioned) &&
    (!text || r.prompt_text.toLowerCase().includes(text))
  );
  if (sortKey) {
    rows = rows.slice().sort((a, b) => {
      let av = a[sortKey], bv = b[sortKey];
      if (typeof av === "string") { av = av.toLowerCase(); bv = bv.toLowerCase(); }
      if (av < bv) return sortAsc ? -1 : 1;
      if (av > bv) return sortAsc ? 1 : -1;
      return 0;
    });
  }
  return rows;
}

function renderTable() {
  const tbody = document.getElementById("prompt-table-body");
  tbody.innerHTML = "";
  const rows = getFilteredRows();
  rows.forEach((r, idx) => {
    const tr = document.createElement("tr");
    tr.className = "data-row";
    tr.innerHTML = `
      <td>${r.prompt_text}</td>
      <td>${r.engine}</td>
      <td><span class="badge ${r.mentioned === 'Y' ? 'yes' : 'no'}">${r.mentioned}</span></td>
      <td>${r.position}</td>
      <td><span class="badge ${r.recommended === 'Y' ? 'yes' : 'no'}">${r.recommended}</span></td>
      <td>${r.mention_count}</td>
    `;
    const detailTr = document.createElement("tr");
    detailTr.className = "detail-row";
    detailTr.style.display = "none";
    const td = document.createElement("td");
    td.colSpan = 6;
    td.textContent = r.raw_response;
    detailTr.appendChild(td);

    tr.addEventListener("click", () => {
      detailTr.style.display = detailTr.style.display === "none" ? "table-row" : "none";
    });

    tbody.appendChild(tr);
    tbody.appendChild(detailTr);
  });
}

document.querySelectorAll("th[data-key]").forEach(th => {
  th.addEventListener("click", () => {
    const key = th.dataset.key;
    if (sortKey === key) { sortAsc = !sortAsc; } else { sortKey = key; sortAsc = true; }
    renderTable();
  });
});
document.getElementById("filter-engine").addEventListener("change", renderTable);
document.getElementById("filter-mentioned").addEventListener("change", renderTable);
document.getElementById("filter-text").addEventListener("input", renderTable);

if (!DATA.has_data) {
  document.getElementById("empty-state").style.display = "block";
  document.getElementById("dashboard-content").style.display = "none";
} else {
  renderHeadline();
  renderTrend();
  renderSov();
  populateFilters();
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
    brand_name = entities[0]["name"]

    db.init_db()
    conn = db.get_connection()
    try:
        data = build_data(conn, brand_name)
    finally:
        conn.close()

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = render_html(data, generated_at)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html)
    print(f"Dashboard written to {OUTPUT_PATH}")


if __name__ == "__main__":
    generate()
