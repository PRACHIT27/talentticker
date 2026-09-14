/* TalentTicker dashboard.
   No framework and no build step - one file, readable top to bottom. */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = { window: 30, sectorWindow: 90 };


const STATIC = typeof window !== "undefined" && window.TT_STATIC === true;
const PROFILE = (typeof window !== "undefined" && window.TT_PROFILE) || "swe";
let BUNDLE = null;

async function bundle() {
  if (!BUNDLE) {
    const res = await fetch(`data/${PROFILE}.json`);
    if (!res.ok) throw new Error("could not load the data file");
    BUNDLE = await res.json();
  }
  return BUNDLE;
}

function openingsFor(b, predicate) {
  return b.jobs.filter(predicate).slice(0, 40);
}

async function staticApi(path) {
  const b = await bundle();
  const [route, query = ""] = path.split("?");
  const q = new URLSearchParams(query);
  const win = q.get("window") || "30";
  const pick = (map, fallback = "30") => map[win] || map[fallback] || {};

  switch (route) {
    case "/api/summary":
      return b.summary;
    case "/api/ticker": {
      const rows = pick(b.ticker);
      const limit = Number(q.get("limit") || 60);
      return { window: Number(win), rows: rows.slice(0, limit), total: rows.length };
    }
    case "/api/movers":
      return pick(b.movers);
    case "/api/emerging":
      return { rows: b.emerging.slice(0, Number(q.get("limit") || 30)) };
    case "/api/skill": {
      const name = q.get("name");
      const d = b.skills[name];
      if (!d) throw new Error(`nothing recorded for '${name}'`);
      return { ...d, openings: openingsFor(b, (j) => (j.skills || []).includes(name)) };
    }
    case "/api/sectors":
      return { rows: pick(b.sectors.board) };
    case "/api/sector": {
      const name = q.get("name");
      const d = b.sectors.detail[name];
      if (!d) throw new Error(`nothing recorded for sector '${name}'`);
      return { ...d, openings: openingsFor(b, (j) => j.sector === name) };
    }
    case "/api/metros":
      return pick(b.geo);
    case "/api/companies":
      return pick(b.geo).companies || { growing: [], shrinking: [], boards: [] };
    case "/api/building":
      if (!b.building) throw new Error("no repo data in this export");
      return b.building;
    case "/api/themes":
      if (!b.themes || !b.themes.themes) throw new Error("no write-up in this export");
      return b.themes;
    case "/api/jobs": {
      const days = Number(q.get("days") || 14);
      const cutoff = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
      const skill = q.get("skill");
      const metro = q.get("metro");
      const company = (q.get("company") || "").toLowerCase();
      const remote = q.get("remote") === "1";
      const spon = q.get("sponsorship");
      let rows = b.jobs.filter((j) => (j.first_published || "") >= cutoff);
      if (skill) rows = rows.filter((j) => (j.skills || []).some((s) => s.toLowerCase() === skill.toLowerCase()));
      if (metro) rows = rows.filter((j) => (j.metro || "").toLowerCase().includes(metro.toLowerCase()));
      if (company) rows = rows.filter((j) => (j.company_name || "").toLowerCase().includes(company));
      if (remote) rows = rows.filter((j) => j.remote);
      if (spon === "open") rows = rows.filter((j) => !["no", "clearance"].includes(j.sponsorship));
      else if (spon) rows = rows.filter((j) => (j.sponsorship || "unknown") === spon);
      return { rows: rows.slice(0, Number(q.get("limit") || 5000)) };
    }
    case "/api/alert-config":
      return {
        to: "", smtp_host: "", dry_run: false, configured: false,
        mode: "alerts are sent by the scheduled job, not from this page",
      };
    case "/api/watchlists":
      return { rows: [] };
    case "/api/alerts":
      return { rows: [] };
    default:
      throw new Error(`no static data for ${route}`);
  }
}

async function api(path) {
  if (STATIC) return staticApi(path);
  const res = await fetch(path);
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `request failed (${res.status})`);
  }
  return res.json();
}

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------------- formatters ---------------- */

function changeCell(value) {
  if (value === null || value === undefined) return '<span class="flat">&ndash;</span>';
  const cls = value > 0.5 ? "up" : value < -0.5 ? "down" : "flat";
  const arrow = value > 0.5 ? "▲" : value < -0.5 ? "▼" : "–";
  return `<span class="${cls}">${arrow} ${Math.abs(value).toFixed(1)}%</span>`;
}

const kd = (n) => "$" + Math.round(n / 1000) + "k";

function money(low, high) {
  if (!low) return "";
  return high && high !== low ? `${kd(low)}–${kd(high)}` : kd(low);
}

function years(row) {
  if (row.yoe_min === null || row.yoe_min === undefined) return "not stated";
  if (row.yoe_max && row.yoe_max !== row.yoe_min) return `${row.yoe_min}–${row.yoe_max} yrs`;
  return row.yoe_min === 0 ? "entry" : `${row.yoe_min}+ yrs`;
}

function ago(iso) {
  if (!iso) return "";
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days}d ago`;
  return `${Math.floor(days / 30)}mo ago`;
}


/* Visa sponsorship. For anyone on OPT this is the first thing they need to
   know, so it gets a column of its own rather than being buried in the text. */
const SPONSOR = {
  yes: { label: "Sponsors", cls: "spon-yes" },
  no: { label: "No sponsorship", cls: "spon-no" },
  clearance: { label: "Clearance", cls: "spon-clear" },
  unknown: { label: "Not stated", cls: "spon-unknown" },
};

function sponsorCell(row) {
  const key = row.sponsorship || "unknown";
  const meta = SPONSOR[key] || SPONSOR.unknown;
  const note = row.sponsorship_note
    ? ` data-tip="${esc(row.sponsorship_note)}"`
    : ' data-tip="The posting does not mention sponsorship either way."';
  return `<span class="pill ${meta.cls} hot"${note}>${meta.label}</span>`;
}

const SPONSOR_RANK = { no: 0, clearance: 1, unknown: 2, yes: 3 };

/* ---------------- shared tooltip ---------------- */

const tip = () => $("#tooltip");

function showTip(html, event) {
  const el = tip();
  el.innerHTML = html;
  el.classList.add("on");
  const pad = 14;
  let x = event.clientX + pad;
  let y = event.clientY + pad;
  const box = el.getBoundingClientRect();
  if (x + box.width > window.innerWidth - 8) x = event.clientX - box.width - pad;
  if (y + box.height > window.innerHeight - 8) y = event.clientY - box.height - pad;
  el.style.left = x + "px";
  el.style.top = y + "px";
}

function hideTip() {
  tip().classList.remove("on");
}

/* ---------------- sortable table ---------------- */

/* Every table on the dashboard is built through this, so sorting behaves the
   same everywhere: click a heading to sort, click again to reverse. Numeric
   columns start descending, because "most" is the interesting end. */

const sortState = {};
const pageState = {};
const PAGE_SIZE = 100;

function dataTable(containerSel, columns, rows, options = {}) {
  const container = $(containerSel);
  if (!container) return;
  const key = options.id || containerSel;

  if (!sortState[key]) {
    const initial = options.sortKey || columns[0].key;
    const column = columns.find((c) => c.key === initial);
    sortState[key] = { key: initial, dir: options.sortDir || (column && column.num ? -1 : 1) };
  }
  const sort = sortState[key];

  if (!rows || !rows.length) {
    container.innerHTML = `<div class="empty">${esc(options.empty || "Nothing to show yet.")}</div>`;
    return;
  }

  const column = columns.find((c) => c.key === sort.key) || columns[0];
  const valueOf = (row) => (column.sortValue ? column.sortValue(row) : row[column.key]);
  if (pageState[key] === undefined) pageState[key] = options.pageSize || PAGE_SIZE;
  const limit = pageState[key];

  const sorted = rows.slice().sort((a, b) => {
    const x = valueOf(a);
    const y = valueOf(b);
    if (x === null || x === undefined) return 1;
    if (y === null || y === undefined) return -1;
    if (typeof x === "number" && typeof y === "number") return (x - y) * sort.dir;
    return String(x).localeCompare(String(y)) * sort.dir;
  }).slice(0, limit);

  // Bar columns are scaled against the largest value in the table.
  const maxima = {};
  columns.filter((c) => c.bar).forEach((c) => {
    maxima[c.key] = Math.max(...rows.map((r) => Math.abs(Number(r[c.key]) || 0)), 1);
  });

  const head = columns
    .map((c) => {
      const active = c.key === sort.key;
      const arrow = active ? (sort.dir === 1 ? "↑" : "↓") : "";
      return `<th class="${c.num ? "num" : ""} ${active ? "sorted" : ""}"
                  data-sort="${esc(c.key)}" style="${c.width ? `width:${c.width}` : ""}"
                  title="Sort by ${esc(c.label)}">${esc(c.label)}<span class="arrow">${arrow}</span></th>`;
    })
    .join("");

  const body = sorted
    .map((row, index) => {
      const cells = columns
        .map((c) => {
          let content = c.fmt ? c.fmt(row, index) : esc(row[c.key] ?? "");
          if (c.bar) {
            const pct = (Math.abs(Number(row[c.key]) || 0) / maxima[c.key]) * 100;
            content = `<div class="cell-bar"><span class="cell-bar-fill" style="width:${pct}%"></span>
                       <span class="cell-bar-text">${content}</span></div>`;
          }
          return `<td class="${c.num ? "num" : ""}">${content}</td>`;
        })
        .join("");
      const id = options.rowKey ? ` data-row="${esc(options.rowKey(row))}"` : "";
      return `<tr class="${options.onRowClick ? "clickable" : ""}"${id}>${cells}</tr>`;
    })
    .join("");

  const shown = sorted.length;
  const footer =
    rows.length > shown
      ? `<div class="table-foot">
           Showing <b>${shown.toLocaleString()}</b> of ${rows.length.toLocaleString()}
           <button class="btn ghost" data-more="1">Show 100 more</button>
           <button class="btn ghost" data-more="all">Show all</button>
         </div>`
      : rows.length > PAGE_SIZE
        ? `<div class="table-foot">Showing all ${rows.length.toLocaleString()}</div>`
        : "";

  container.innerHTML =
    `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>${footer}`;

  container.querySelectorAll("[data-more]").forEach((btn) =>
    btn.addEventListener("click", () => {
      pageState[key] = btn.dataset.more === "all"
        ? Number.MAX_SAFE_INTEGER
        : (pageState[key] || PAGE_SIZE) + 100;
      dataTable(containerSel, columns, rows, options);
    })
  );

  container.querySelectorAll("th[data-sort]").forEach((th) =>
    th.addEventListener("click", () => {
      const clicked = th.dataset.sort;
      const col = columns.find((c) => c.key === clicked);
      if (sort.key === clicked) sort.dir *= -1;
      else {
        sort.key = clicked;
        sort.dir = col && col.num ? -1 : 1;
      }
      pageState[key] = options.pageSize || PAGE_SIZE;
      dataTable(containerSel, columns, rows, options);
    })
  );

  if (options.onRowClick) {
    container.querySelectorAll("tr[data-row]").forEach((tr) =>
      tr.addEventListener("click", () => options.onRowClick(tr.dataset.row))
    );
  }
}

/* ---------------- charts ---------------- */

/* Sequential blue ramp, low to high, stepped for a dark surface. The middle
   step of the full ramp was dropped: at that lightness neither white nor dark
   label text clears 4.5:1, so the scale skips it. */
const RAMP = ["#104281", "#184f95", "#1c5cab", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"];
const RAMP_DARK_TEXT_FROM = 3; // steps at this index and above take dark text

function rampStep(value, max) {
  if (!value) return -1;
  const fraction = Math.sqrt(value / max); // square root keeps the long tail visible
  return Math.min(RAMP.length - 1, Math.max(0, Math.round(fraction * (RAMP.length - 1))));
}

function sparkline(points, trend = null, width = 96, height = 26) {
  if (!points || points.length < 2) return "";
  const values = points.map((p) => p.share);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = width / (values.length - 1);
  const path = values
    .map((v, i) => {
      const x = (i * step).toFixed(1);
      const y = (height - 3 - ((v - min) / span) * (height - 6)).toFixed(1);
      return `${i ? "L" : "M"}${x},${y}`;
    })
    .join(" ");
  const rising = trend === null ? values[values.length - 1] >= values[0] : trend >= 0;
  return `<svg class="spark" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">
      <path d="${path}" fill="none" stroke="${rising ? "var(--up)" : "var(--down)"}"
            stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
    </svg>`;
}

function areaChart(series, valueKey = "share", suffix = "%", width = 620, height = 150) {
  if (!series || series.length < 2) return '<div class="empty">Not enough history yet.</div>';
  const values = series.map((p) => p[valueKey]);
  const max = Math.max(...values, 1);
  const step = width / (series.length - 1);
  const y = (v) => height - 22 - (v / max) * (height - 34);
  const line = series
    .map((p, i) => `${i ? "L" : "M"}${(i * step).toFixed(1)},${y(p[valueKey]).toFixed(1)}`)
    .join(" ");
  const area = `${line} L${width},${height - 22} L0,${height - 22} Z`;
  const dots = series
    .map(
      (p, i) =>
        `<circle cx="${(i * step).toFixed(1)}" cy="${y(p[valueKey]).toFixed(1)}" r="8"
           fill="transparent" class="hot"
           data-tip="${esc(p.month)}: ${p[valueKey]}${suffix}"/>`
    )
    .join("");
  const labels = series
    .map((p, i) =>
      i % 3 === 0
        ? `<text x="${(i * step).toFixed(0)}" y="${height - 6}" fill="#898781" font-size="10">${p.month.slice(2)}</text>`
        : ""
    )
    .join("");
  return `<svg class="chart" width="100%" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
    <path d="${area}" fill="rgba(57,135,229,0.14)"/>
    <path d="${line}" fill="none" stroke="#3987e5" stroke-width="2" stroke-linejoin="round"/>
    <text x="2" y="12" fill="#898781" font-size="10">${max.toFixed(0)}${suffix}</text>
    ${labels}${dots}
  </svg>`;
}

/* Horizontal range bars. A pay range has two numbers, so the bar spans from
   the low figure to the high one rather than starting at zero - a single-value
   bar would throw away half the information. */
function payRangeChart(rows, labelKey, lowKey = "pay_low", highKey = "pay_high") {
  const usable = rows.filter((r) => r[lowKey] && r[highKey]);
  if (!usable.length) return '<div class="empty">No published pay ranges yet.</div>';

  const max = Math.max(...usable.map((r) => r[highKey]));
  const min = Math.min(...usable.map((r) => r[lowKey]));
  const floor = Math.max(0, min - (max - min) * 0.12);
  const pos = (v) => ((v - floor) / (max - floor)) * 100;

  const ticks = [];
  const stepSize = max - floor > 200000 ? 100000 : 50000;
  for (let v = Math.ceil(floor / stepSize) * stepSize; v <= max; v += stepSize) {
    ticks.push(`<span class="axis-tick" style="left:${pos(v)}%">${kd(v)}</span>`);
  }

  return (
    `<div class="range-chart">` +
    usable
      .map((r) => {
        const left = pos(r[lowKey]);
        const width = Math.max(1.5, pos(r[highKey]) - left);
        const samples = r.pay_samples || r.samples || 0;
        const label =
          `${esc(r[labelKey])} &middot; ${kd(r[lowKey])} to ${kd(r[highKey])}` +
          (samples ? ` &middot; ${samples} posting(s)` : "");
        return `<div class="range-row">
          <div class="range-label">${esc(r[labelKey])}</div>
          <div class="range-track">
            <span class="range-fill hot" style="left:${left}%;width:${width}%"
                  data-tip="${label}"></span>
          </div>
          <div class="range-value">${kd(r[lowKey])}&ndash;${kd(r[highKey])}</div>
        </div>`;
      })
      .join("") +
    `<div class="range-axis"><div class="range-label"></div>
       <div class="range-track">${ticks.join("")}</div>
       <div class="range-value"></div></div>` +
    `</div>`
  );
}

/* A real choropleth of the United States.

   The shapes come from us-atlas (US Census boundaries), already projected to
   Albers USA and converted to plain SVG paths by scripts/build_us_map.py. That
   conversion happens once at build time, so the browser needs no mapping
   library, no CDN and no projection maths - just <path> elements. */

let mapShapes = null;

async function loadMapShapes() {
  if (!mapShapes) mapShapes = await (await fetch("us-states.json")).json();
  return mapShapes;
}

/* The nine small north-eastern states are too narrow to hold a label, so they
   get leader lines out to a column on the right. Without this they are either
   unlabelled or covered in overlapping text - the usual failure of US maps. */
const LEADER_STATES = ["VT", "NH", "MA", "RI", "CT", "NJ", "DE", "MD", "DC"];
const LEADER_X = 1000;
const LEADER_TOP = 96;
const LEADER_GAP = 26;
const MIN_AREA_FOR_INLINE_LABEL = 1200;

async function usHeatMap(states, unplaced = 0) {
  const shapes = await loadMapShapes();
  const byState = {};
  states.forEach((s) => (byState[s.state] = s.postings));
  const max = Math.max(...Object.values(byState), 1);
  const placed = Object.values(byState).reduce((a, b) => a + b, 0);

  const leaderIndex = {};
  LEADER_STATES.forEach((abbr, i) => (leaderIndex[abbr] = LEADER_TOP + i * LEADER_GAP));

  const paths = [];
  const labels = [];
  const leaders = [];

  shapes.states.forEach((shape) => {
    const count = byState[shape.abbr] || 0;
    const step = rampStep(count, max);
    // States with no roles still need to read as land, not as background.
    const fill = step < 0 ? "#242932" : RAMP[step];
    const ink = step < 0 ? "#8b929e" : step >= RAMP_DARK_TEXT_FROM ? "#0b0d10" : "#ffffff";
    const tip = `<b>${shape.name}</b><br>${count.toLocaleString()} early-career role(s)`;

    paths.push(
      `<path d="${shape.d}" fill="${fill}" stroke="#14171c" stroke-width="1.1"
             class="state hot" data-tip="${tip}" data-state="${shape.abbr}"/>`
    );

    if (shape.abbr in leaderIndex) {
      const y = leaderIndex[shape.abbr];
      leaders.push(
        `<path d="M${shape.cx},${shape.cy} L${LEADER_X - 32},${y} L${LEADER_X - 8},${y}"
               fill="none" stroke="#383835" stroke-width="1"/>
         <circle cx="${shape.cx}" cy="${shape.cy}" r="2" fill="#383835"/>
         <text x="${LEADER_X}" y="${y + 4}" fill="#c3c2b7" font-size="13"
               font-weight="600">${shape.abbr}</text>
         <text x="${LEADER_X + 30}" y="${y + 4}" fill="${count ? "#c3c2b7" : "#5d646f"}"
               font-size="13">${count}</text>`
      );
    } else if (shape.area >= MIN_AREA_FOR_INLINE_LABEL) {
      labels.push(
        `<text x="${shape.cx}" y="${shape.cy}" fill="${ink}" font-size="13"
               font-weight="600" text-anchor="middle">${shape.abbr}</text>` +
          (count
            ? `<text x="${shape.cx}" y="${shape.cy + 14}" fill="${ink}" font-size="12"
                     text-anchor="middle" opacity="0.9">${count}</text>`
            : "")
      );
    }
  });

  const legendSteps = RAMP.map(
    (c, i) =>
      `<span class="legend-swatch" style="background:${c}"
             title="${Math.round(Math.pow(i / (RAMP.length - 1), 2) * max)} or more"></span>`
  ).join("");

  const legend =
    `<div class="map-legend"><span class="legend-label">Fewer roles</span>${legendSteps}` +
    `<span class="legend-label">More</span>
     <span class="legend-label" style="margin-left:18px">
       <span class="legend-swatch" style="background:#242932"></span> none recorded
     </span>
     <span class="legend-label" style="margin-left:18px">Peak: ${max.toLocaleString()}</span>
     </div>`;

  // Plenty of postings say only "Remote" or "United States", which cannot be
  // put on a map. Saying so is better than letting the map look complete.
  const caveat = unplaced
    ? `<p class="foot">${placed.toLocaleString()} role(s) name a specific state and are shaded
       above. A further <b>${unplaced.toLocaleString()}</b> are advertised only as remote or
       US-wide, so they belong to no single state and are not on the map.
       Alaska and Hawaii are drawn as insets, as they are on any Albers map of the US.</p>`
    : "";

  // The viewBox is taken from the data rather than hardcoded: the Albers USA
  // layout puts the Alaska inset at a negative x, so a box starting at 0
  // quietly slices the western end of Alaska off.
  const [bx0, by0, bx1, by1] = shapes.bbox;
  const x0 = bx0 - 8;
  const y0 = by0 - 8;
  const width = LEADER_X + 62 - x0;
  const height = by1 + 10 - y0;

  return `<svg class="us-map" viewBox="${x0.toFixed(1)} ${y0.toFixed(1)} ${width.toFixed(1)} ${height.toFixed(1)}"
               preserveAspectRatio="xMidYMid meet">
      <g class="states">${paths.join("")}</g>
      <g class="leaders">${leaders.join("")}</g>
      <g class="labels" pointer-events="none">${labels.join("")}</g>
    </svg>${legend}${caveat}`;
}

/* Attach tooltips to anything marked .hot inside a container. */
function wireTips(containerSel) {
  $$(`${containerSel} .hot`).forEach((el) => {
    el.addEventListener("mousemove", (e) => showTip(el.dataset.tip, e));
    el.addEventListener("mouseleave", hideTip);
  });
}

function barList(rows, labelKey, valueKey, formatter) {
  if (!rows || !rows.length) return '<div class="empty">Nothing to show yet.</div>';
  const max = Math.max(...rows.map((r) => Math.abs(r[valueKey]) || 0)) || 1;
  return rows
    .map((row) => {
      const value = row[valueKey] || 0;
      return `<div class="bar-row">
        <div class="label">${esc(row[labelKey])}</div>
        <div class="track"><div class="fill" style="width:${(Math.abs(value) / max) * 100}%"></div></div>
        <div class="value">${formatter ? formatter(row) : value}</div>
      </div>`;
    })
    .join("");
}

/* ---------------- navigation ---------------- */

const loaders = {};
$$("nav button").forEach((button) => {
  button.addEventListener("click", () => {
    $$("nav button").forEach((b) => b.classList.remove("active"));
    $$(".page").forEach((p) => p.classList.remove("active"));
    button.classList.add("active");
    $("#page-" + button.dataset.page).classList.add("active");
    const load = loaders[button.dataset.page];
    if (load) load().catch((e) => console.error(e));
  });
});

/* ---------------- header ---------------- */

async function loadSummary() {
  const d = await api("/api/summary");
  // Which role profile these numbers describe.
  if (d.profile_label) {
    const sub = document.querySelector("header .sub");
    if (sub) sub.textContent = d.profile_label;
    document.title = "TalentTicker - " + d.profile_label;
  }
  $("#stats").innerHTML = [
    ["Early-career roles", d.total.toLocaleString()],
    ["Posted in 30 days", d.last30.toLocaleString()],
    ["This week", d.last7.toLocaleString()],
    ["Postings scanned", d.scanned.toLocaleString()],
    ["Companies", d.companies.toLocaleString()],
  ]
    .map(([label, value]) => `<div class="stat"><b>${value}</b><span>${label}</span></div>`)
    .join("");
}

/* ---------------- ticker ---------------- */

let tickerRows = [];

async function loadTicker() {
  state.window = $("#tickerWindow").value;
  $("#tickerTable").innerHTML = '<div class="loading">Loading&hellip;</div>';
  const d = await api(`/api/ticker?window=${state.window}&limit=250`);
  tickerRows = d.rows;

  const select = $("#tickerCategory");
  if (select.options.length <= 1) {
    // Show the readable label ("AI / ML"), keep the raw key as the value.
    const seen = new Map();
    d.rows.forEach((r) => seen.set(r.category, r.category_label || r.category));
    [...seen.entries()]
      .sort((a, b) => a[1].localeCompare(b[1]))
      .forEach(([key, label]) => select.add(new Option(label, key)));
  }
  renderTicker();
}

function renderTicker() {
  const category = $("#tickerCategory").value;
  const term = $("#tickerSearch").value.trim().toLowerCase();
  const rows = tickerRows.filter(
    (r) => (!category || r.category === category) && (!term || r.skill.toLowerCase().includes(term))
  );

  dataTable(
    "#tickerTable",
    [
      { key: "rank", label: "#", num: true, width: "48px", fmt: (r) => `<span class="flat">${r.rank}</span>` },
      {
        key: "skill",
        label: "Skill",
        fmt: (r) => `<b>${esc(r.skill)}</b>${r.is_new ? ' <span class="pill new">new</span>' : ""}`,
      },
      {
        key: "category",
        label: "Category",
        sortValue: (r) => r.category_label || r.category,
        fmt: (r) => `<span class="flat">${esc(r.category_label || r.category)}</span>`,
      },
      { key: "postings", label: "Jobs", num: true },
      { key: "share", label: "Share", num: true, fmt: (r) => r.share.toFixed(1) + "%" },
      { key: "change", label: "Change", num: true, fmt: (r) => changeCell(r.change) },
      {
        key: "series",
        label: "12 months",
        width: "110px",
        sortValue: (r) => (r.series.length ? r.series[r.series.length - 1].share : 0),
        fmt: (r) => sparkline(r.series, r.change),
      },
    ],
    rows,
    {
      id: "ticker",
      sortKey: "rank",
      sortDir: 1,
      empty: "No skills match that filter.",
      rowKey: (r) => r.skill,
      onRowClick: openSkill,
    }
  );
}

$("#tickerWindow").addEventListener("change", () => loadTicker().catch(console.error));
$("#tickerCategory").addEventListener("change", renderTicker);
$("#tickerSearch").addEventListener("input", renderTicker);
loaders.ticker = loadTicker;

/* ---------------- skill drawer ---------------- */

function openDrawer() {
  $("#drawer").classList.add("open");
  $("#backdrop").classList.add("open");
  $("#drawerBody").innerHTML = '<div class="loading">Loading&hellip;</div>';
}

async function openSkill(skill) {
  openDrawer();
  let d;
  try {
    d = await api(`/api/skill?name=${encodeURIComponent(skill)}`);
  } catch (err) {
    $("#drawerBody").innerHTML = `<div class="empty">${esc(err.message)}</div>`;
    return;
  }

  const pay =
    d.pay.samples > 0
      ? `<p class="hint">Published pay averages ${money(d.pay.low, d.pay.high)} across
         ${d.pay.samples} posting(s) that disclosed a range.</p>`
      : '<p class="hint">No published pay ranges in this sample.</p>';

  $("#drawerBody").innerHTML = `
    <h2>${esc(skill)}</h2>
    <p class="hint">Share of early-career US software postings, by month</p>
    ${areaChart(d.series)}
    ${pay}
    <h2 style="margin-top:20px">Which sectors want it</h2>
    <p class="hint">Share of that sector's early-career postings that mention it.</p>
    ${barList(d.sectors || [], "sector", "share", (r) => `${r.share}% (${r.postings})`)}
    <div class="grid two" style="margin-top:18px">
      <div><h2>Who is asking</h2>${barList(d.companies, "name", "n", (r) => r.n)}</div>
      <div><h2>Where</h2>${barList(d.metros, "metro", "n", (r) => r.n)}</div>
    </div>
    <h2 style="margin-top:22px">Also asked for</h2>
    <div>${d.co_occurring.map((c) => `<span class="pill tag">${esc(c.skill)} ${c.share}%</span>`).join("")}</div>
    <h2 style="margin-top:22px">Open roles (${d.openings.length})</h2>
    ${d.openings.map(jobRow).join("")}
  `;
  wireTips("#drawerBody");
}

function jobRow(j) {
  const pay = money(j.salary_min, j.salary_max);
  return `<div class="job">
    <div class="title"><a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a></div>
    <div class="meta">${esc(j.company_name)} &middot; ${esc(j.metro || "location not given")}
      &middot; ${years(j)}${pay ? " &middot; " + pay : ""} &middot; ${ago(j.first_published)}</div>
  </div>`;
}

$("#drawerClose").addEventListener("click", closeDrawer);
$("#backdrop").addEventListener("click", closeDrawer);
function closeDrawer() {
  $("#drawer").classList.remove("open");
  $("#backdrop").classList.remove("open");
  hideTip();
}
document.addEventListener("keydown", (e) => e.key === "Escape" && closeDrawer());

/* ---------------- movers ---------------- */

loaders.movers = async function () {
  const d = await api(`/api/movers?window=${state.window}`);
  const render = (rows) =>
    rows.length
      ? rows
          .map(
            (r) => `<div class="bar-row">
              <div class="label link" data-skill="${esc(r.skill)}">${esc(r.skill)}</div>
              <div class="value" style="width:auto;flex:1;text-align:left;color:var(--dim)">${r.postings} jobs</div>
              <div class="value">${changeCell(r.change)}</div>
            </div>`
          )
          .join("")
      : '<div class="empty">Nothing yet.</div>';
  $("#gainers").innerHTML = render(d.gainers);
  $("#losers").innerHTML = render(d.losers);
  $("#emergingSkills").innerHTML = render(d.emerging);
  $$("#page-movers [data-skill]").forEach((el) =>
    el.addEventListener("click", () => openSkill(el.dataset.skill))
  );
};

/* ---------------- emerging phrases ---------------- */

loaders.emerging = async function () {
  $("#emergingTable").innerHTML = '<div class="loading">Reading every posting&hellip;</div>';
  const d = await api("/api/emerging?limit=40");
  dataTable(
    "#emergingTable",
    [
      {
        key: "phrase",
        label: "Term",
        fmt: (r) => `<span class="mono">${esc(r.phrase)}</span>${r.is_new ? ' <span class="pill new">new</span>' : ""}`,
      },
      { key: "recent", label: "Postings now", num: true, bar: true },
      { key: "companies", label: "Companies", num: true },
      { key: "baseline", label: "Before", num: true, fmt: (r) => `<span class="flat">${r.baseline}</span>` },
      { key: "lift", label: "Growth", num: true, fmt: (r) => `<span class="up">${r.lift}&times;</span>` },
    ],
    d.rows,
    { id: "emerging", sortKey: "lift", empty: "Not enough history yet. Collect a few more days." }
  );
};

/* ---------------- sectors ---------------- */

loaders.sectors = async function () {
  state.sectorWindow = $("#sectorWindow").value;
  $("#sectorTable").innerHTML = '<div class="loading">Loading&hellip;</div>';
  const d = await api(`/api/sectors?window=${state.sectorWindow}`);

  $("#sectorChart").innerHTML = barList(
    d.rows,
    "sector",
    "postings",
    (r) => `${r.postings} &middot; ${r.share}%`
  );
  $("#sectorPayChart").innerHTML = payRangeChart(d.rows, "sector");
  wireTips("#sectorPayChart");

  dataTable(
    "#sectorTable",
    [
      { key: "sector", label: "Sector", fmt: (r) => `<b>${esc(r.sector)}</b>` },
      { key: "postings", label: "Jobs", num: true, bar: true },
      { key: "companies", label: "Companies", num: true },
      { key: "share", label: "Share", num: true, fmt: (r) => r.share.toFixed(1) + "%" },
      { key: "change", label: "Change", num: true, fmt: (r) => changeCell(r.change) },
      {
        key: "pay_low",
        label: "Typical pay",
        num: true,
        fmt: (r) => (r.pay_low ? money(r.pay_low, r.pay_high) : '<span class="flat">&ndash;</span>'),
      },
    ],
    d.rows,
    { id: "sectors", sortKey: "postings", rowKey: (r) => r.sector, onRowClick: openSector }
  );
};

$("#sectorWindow").addEventListener("change", () => loaders.sectors().catch(console.error));

async function openSector(name) {
  openDrawer();
  let d;
  try {
    d = await api(`/api/sector?name=${encodeURIComponent(name)}`);
  } catch (err) {
    $("#drawerBody").innerHTML = `<div class="empty">${esc(err.message)}</div>`;
    return;
  }

  $("#drawerBody").innerHTML = `
    <h2>${esc(name)}</h2>
    <p class="hint">Share of all early-career US software postings, by month</p>
    ${areaChart(d.series)}
    <h2 style="margin-top:20px">Skills this sector wants</h2>
    <p class="hint">
      "Lift" compares against the whole market. Above 1.0 means this sector asks
      for it more than everyone else does &mdash; that is what makes it worth learning
      for this sector specifically.
    </p>
    <div id="sectorSkills"></div>
    <div class="grid two" style="margin-top:18px">
      <div><h2>Who is hiring</h2>${barList(d.companies, "name", "n", (r) => r.n)}</div>
      <div><h2>Where</h2>${barList(d.metros, "metro", "n", (r) => r.n)}</div>
    </div>
    <h2 style="margin-top:22px">Open roles (${d.openings.length})</h2>
    ${d.openings.map(jobRow).join("")}
  `;

  dataTable(
    "#sectorSkills",
    [
      { key: "skill", label: "Skill" },
      { key: "postings", label: "Jobs", num: true, bar: true },
      { key: "share", label: "In sector", num: true, fmt: (r) => r.share + "%" },
      { key: "market_share", label: "Market", num: true, fmt: (r) => `<span class="flat">${r.market_share}%</span>` },
      {
        key: "lift",
        label: "Lift",
        num: true,
        fmt: (r) =>
          r.lift === null
            ? '<span class="flat">&ndash;</span>'
            : `<span class="${r.lift >= 1.3 ? "up" : r.lift <= 0.7 ? "down" : "flat"}">${r.lift}&times;</span>`,
      },
    ],
    d.skills,
    { id: "sectorSkills", sortKey: "lift" }
  );
  wireTips("#drawerBody");
}

loaders.building = async function () {
  const months = $("#buildingMonths").value;
  $("#buildingTable").innerHTML = '<div class="loading">Loading&hellip;</div>';
  const d = await api(`/api/building?months=${months}`);

  $("#buildingMeta").textContent = d.summary.repos
    ? `${d.summary.repos.toLocaleString()} repos, ${d.summary.stars.toLocaleString()} stars`
    : "no repo data yet";

  const ahead = d.board.filter((r) => r.gap > 0).slice(0, 12);
  $("#buildingAhead").innerHTML = barList(
    ahead, "skill", "gap",
    (r) => `${r.repo_share}% built vs ${r.job_share}% hired`
  );
  $("#buildingLangs").innerHTML = barList(
    d.languages, "language", "repos", (r) => `${r.repos} (${r.share}%)`
  );

  dataTable(
    "#buildingTable",
    [
      { key: "skill", label: "Skill", fmt: (r) => `<b>${esc(r.skill)}</b>` },
      { key: "category_label", label: "Category", fmt: (r) => `<span class="flat">${esc(r.category_label)}</span>` },
      { key: "repos", label: "Repos", num: true, bar: true },
      { key: "repo_share", label: "Built %", num: true, fmt: (r) => r.repo_share + "%" },
      { key: "job_share", label: "Hired %", num: true, fmt: (r) => `<span class="flat">${r.job_share}%</span>` },
      {
        key: "gap", label: "Gap", num: true,
        fmt: (r) => `<span class="${r.gap > 0 ? "up" : r.gap < 0 ? "down" : "flat"}">${r.gap >= 0 ? "+" : ""}${r.gap}</span>`,
      },
    ],
    d.board,
    { id: "building", sortKey: "gap", empty: "Run `tt building --refresh` first." }
  );

  dataTable(
    "#buildingRepos",
    [
      {
        key: "full_name", label: "Repository",
        fmt: (r) => `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.full_name)}</a>`,
      },
      { key: "description", label: "What it is", fmt: (r) => `<span class="flat">${esc((r.description || "").slice(0, 90))}</span>` },
      { key: "language", label: "Language", fmt: (r) => `<span class="flat">${esc(r.language || "–")}</span>` },
      { key: "stars", label: "Stars", num: true, fmt: (r) => r.stars.toLocaleString() },
      { key: "created_at", label: "Created", num: true, fmt: (r) => `<span class="flat">${ago(r.created_at)}</span>` },
    ],
    d.repos,
    { id: "buildingRepos", sortKey: "stars", pageSize: 20 }
  );
};
$("#buildingMonths").addEventListener("change", () => loaders.building().catch(console.error));

/* ---------------- geography ---------------- */

loaders.map = async function () {
  const [geo, companies] = await Promise.all([
    api(`/api/metros?window=${state.window}`),
    api(`/api/companies?window=${state.window}`),
  ]);

  $("#usMap").innerHTML = await usHeatMap(geo.states, geo.unplaced);
  wireTips("#usMap");

  $("#payChart").innerHTML = payRangeChart(
    geo.pay.slice(0, 14).map((r) => ({ ...r, pay_low: r.low, pay_high: r.high })),
    "metro"
  );
  wireTips("#payChart");

  $("#remoteChart").innerHTML = areaChart(geo.remote, "share", "%");
  wireTips("#remoteChart");

  dataTable(
    "#metroTable",
    [
      { key: "metro", label: "Metro", fmt: (r) => `<b>${esc(r.metro)}</b>` },
      { key: "postings", label: "Jobs", num: true, bar: true },
      { key: "share", label: "Share", num: true, fmt: (r) => r.share + "%" },
      {
        key: "share_change",
        label: "Share change",
        num: true,
        fmt: (r) =>
          `<span class="${r.share_change > 0 ? "up" : r.share_change < 0 ? "down" : "flat"}">
             ${r.share_change >= 0 ? "+" : ""}${r.share_change}pt</span>`,
      },
      { key: "change", label: "Change", num: true, fmt: (r) => changeCell(r.change) },
    ],
    geo.metros,
    { id: "metros", sortKey: "postings" }
  );

  dataTable(
    "#growingTable",
    [
      { key: "company", label: "Opening more roles", fmt: (r) => `<b>${esc(r.company)}</b>` },
      { key: "postings", label: "Now", num: true },
      { key: "prev_postings", label: "Before", num: true, fmt: (r) => `<span class="flat">${r.prev_postings}</span>` },
      {
        key: "delta",
        label: "Change",
        num: true,
        bar: true,
        fmt: (r) => `<span class="up">+${r.delta}</span>`,
      },
    ],
    companies.growing.filter((r) => r.delta > 0).slice(0, 15),
    { id: "growing", sortKey: "delta", empty: "Nobody grew this period." }
  );

  dataTable(
    "#shrinkingTable",
    [
      { key: "company", label: "Pulling back", fmt: (r) => `<b>${esc(r.company)}</b>` },
      { key: "postings", label: "Now", num: true },
      { key: "prev_postings", label: "Before", num: true, fmt: (r) => `<span class="flat">${r.prev_postings}</span>` },
      {
        key: "delta",
        label: "Change",
        num: true,
        bar: true,
        sortValue: (r) => Math.abs(r.delta),
        fmt: (r) => `<span class="down">${r.delta}</span>`,
      },
    ],
    companies.shrinking.slice(0, 15),
    { id: "shrinking", sortKey: "delta", empty: "Nobody pulled back this period." }
  );
};

/* ---------------- themes ---------------- */

async function loadThemes(refresh = false) {
  const box = $("#themes");
  box.innerHTML = refresh
    ? '<div class="loading">Asking Claude to read the postings&hellip; this takes a moment.</div>'
    : '<div class="loading">Loading&hellip;</div>';
  let d;
  try {
    d = await api(`/api/themes?scope=market&subject=&refresh=${refresh ? "true" : "false"}`);
  } catch (err) {
    box.innerHTML = `<div class="empty">${esc(err.message)}<br><br>
      <span style="color:var(--dim)">This page needs an Anthropic API key.
      Put <code>ANTHROPIC_API_KEY</code> in your .env file and press
      "Rebuild with Claude".</span></div>`;
    return;
  }

  $("#themeMeta").textContent = d.built_at
    ? `built ${ago(d.built_at)} from ${d.posting_count ?? "?"} postings${d.cached ? " (cached)" : ""}`
    : "";

  if (!d.themes || !d.themes.length) {
    box.innerHTML = `<div class="empty">${esc(d.summary || "Nothing to report yet.")}</div>`;
    return;
  }

  box.innerHTML =
    `<p style="font-size:15px;color:#c8ccd3;margin-top:0">${esc(d.summary)}</p>` +
    d.themes
      .map(
        (t) => `<div class="theme">
        <h3>${esc(t.title)} <span class="pill ${t.momentum === "new" ? "new" : "hot-pill"}">${esc(t.momentum)}</span></h3>
        <p>${esc(t.problem)}</p>
        <div>${(t.skills || []).map((s) => `<span class="pill tag">${esc(s)}</span>`).join("")}</div>
        <div class="evidence">From ${(t.evidence || []).length} posting(s):
          ${(t.evidence || []).slice(0, 4).map((e) => `${esc(e.company)} &mdash; ${esc(e.title)}`).join(" &middot; ")}
        </div>
      </div>`
      )
      .join("");
}
loaders.themes = () => loadThemes(false);
$("#themeRefresh").addEventListener("click", () => loadThemes(true));

/* ---------------- jobs ---------------- */

loaders.jobs = async function () {
  const params = new URLSearchParams({ days: $("#jobDays").value, limit: "5000" });
  if ($("#jobSkill").value.trim()) params.set("skill", $("#jobSkill").value.trim());
  if ($("#jobMetro").value.trim()) params.set("metro", $("#jobMetro").value.trim());
  if ($("#jobCompany").value.trim()) params.set("company", $("#jobCompany").value.trim());
  if ($("#jobRemote").checked) params.set("remote", "1");
  if ($("#jobSponsor").value) params.set("sponsorship", $("#jobSponsor").value);
  if ($("#jobSponsor").value) params.set("sponsorship", $("#jobSponsor").value);

  $("#jobsTable").innerHTML = '<div class="loading">Loading&hellip;</div>';
  const d = await api("/api/jobs?" + params.toString());

  dataTable(
    "#jobsTable",
    [
      {
        key: "title",
        label: "Role",
        fmt: (r) => `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>`,
      },
      { key: "company_name", label: "Company" },
      {
        key: "metro",
        label: "Where",
        fmt: (r) =>
          `<span class="flat">${esc(r.metro || "–")}</span>` +
          (r.remote ? ' <span class="pill">remote</span>' : ""),
      },
      {
        key: "yoe_min",
        label: "Experience",
        num: true,
        sortValue: (r) => (r.yoe_min === null ? 99 : r.yoe_min),
        fmt: (r) => `<span class="flat">${years(r)}</span>`,
      },
      {
        key: "salary_max",
        label: "Pay",
        num: true,
        sortValue: (r) => r.salary_max || 0,
        fmt: (r) => `<span class="flat">${money(r.salary_min, r.salary_max) || "–"}</span>`,
      },
      {
        key: "sponsorship",
        label: "Sponsorship",
        sortValue: (r) => SPONSOR_RANK[r.sponsorship || "unknown"],
        fmt: sponsorCell,
      },
      {
        key: "first_published",
        label: "Posted",
        num: true,
        fmt: (r) => `<span class="flat">${ago(r.first_published)}</span>`,
      },
    ],
    d.rows,
    { id: "jobs", sortKey: "first_published", empty: "Nothing matches that." }
  );
  wireTips("#jobsTable");
  $("#jobCount").textContent =
    `${d.rows.length} role(s)` + (d.rows.length >= 200 ? " (showing the newest 200)" : "");
};
function runJobSearch() {
  pageState["jobs"] = undefined;
  loaders.jobs().catch(console.error);
}

$("#jobSearch").addEventListener("click", runJobSearch);
$("#jobClear").addEventListener("click", () => {
  ["jobSkill", "jobMetro", "jobCompany"].forEach((id) => ($("#" + id).value = ""));
  $("#jobRemote").checked = false;
  $("#jobSponsor").value = "";
  runJobSearch();
});
["jobSkill", "jobMetro", "jobCompany"].forEach((id) =>
  $("#" + id).addEventListener("keydown", (e) => {
    if (e.key === "Enter") runJobSearch();
  })
);
["jobRemote", "jobSponsor", "jobDays"].forEach((id) =>
  $("#" + id).addEventListener("change", runJobSearch)
);
$("#jobSponsor").addEventListener("change", () => loaders.jobs().catch(console.error));
$("#jobDays").addEventListener("change", () => loaders.jobs().catch(console.error));

/* ---------------- alerts ---------------- */

loaders.alerts = async function () {
  const cfg = await api("/api/alert-config");
  const good = cfg.configured;
  $("#alertConfig").innerHTML = `<div class="note ${good ? "ok" : ""}">
    <b>${good ? "Alerts are on." : "Alerts are not sending yet."}</b>
    ${
      cfg.to
        ? `New matching jobs go to <b class="mono">${esc(cfg.to)}</b>`
        : "No recipient is set."
    }
    ${cfg.smtp_host ? `via ${esc(cfg.smtp_host)}:${cfg.smtp_port}` : ""}.
    <br><span style="opacity:.85">Status: ${esc(cfg.mode)}.
    ${
      good
        ? ""
        : "Set TT_ALERT_TO, TT_SMTP_HOST, TT_SMTP_USER and TT_SMTP_PASS in your .env file, then restart."
    }</span>
  </div>`;

  const lists = await api("/api/watchlists");
  $("#watchlists").innerHTML = lists.rows.length
    ? lists.rows
        .map(
          (w) => `<div class="job">
        <div class="title"><b>${esc(w.name)}</b>
          <button class="pill btn-inline" data-delete="${esc(w.name)}">remove</button></div>
        <div class="meta">
          skills: ${esc(w.skills || "any")} &middot;
          states: ${esc(w.states || "anywhere in the US")} &middot;
          up to ${w.max_years} years${w.remote_ok ? " &middot; remote included" : ""}
          ${w.query ? "&middot; must mention: " + esc(w.query) : ""}
        </div>
      </div>`
        )
        .join("")
    : '<div class="empty">No watchlists yet. Add one below.</div>';

  $$("[data-delete]").forEach((b) =>
    b.addEventListener("click", async () => {
      await fetch("/api/watchlists/" + encodeURIComponent(b.dataset.delete), { method: "DELETE" });
      loaders.alerts();
    })
  );

  const sent = await api("/api/alerts");
  $("#sentAlerts").innerHTML = sent.rows.length
    ? sent.rows
        .map(
          (a) => `<div class="job">
        <div class="title"><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.title)}</a></div>
        <div class="meta">${esc(a.company_name)} &middot; ${esc(a.metro || "")}
          &middot; via ${esc(a.watchlist)} &middot; ${ago(a.sent_at)}</div>
      </div>`
        )
        .join("")
    : '<div class="empty">Nothing sent yet. Alerts appear here once a new job matches.</div>';
};

$("#wlSave").addEventListener("click", async () => {
  const payload = {
    name: $("#wlName").value.trim(),
    skills: $("#wlSkills").value.trim(),
    states: $("#wlStates").value.trim(),
    query: $("#wlQuery").value.trim(),
    max_years: Number($("#wlYears").value || 4),
    remote_ok: $("#wlRemote").checked ? 1 : 0,
  };
  if (!payload.name) {
    alert("Give the watchlist a name.");
    return;
  }
  const res = await fetch("/api/watchlists", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (res.ok) {
    $("#wlName").value = $("#wlSkills").value = $("#wlStates").value = $("#wlQuery").value = "";
    loaders.alerts();
  } else {
    alert("Could not save that watchlist.");
  }
});

/* ---------------- boot ---------------- */

loadSummary().catch(console.error);
loadTicker().catch(console.error);
