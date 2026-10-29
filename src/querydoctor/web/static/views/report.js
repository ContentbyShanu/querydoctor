import { codeBlock } from "../highlight.js";
import { h, icon, copyText, download } from "../dom.js";
import { vitals } from "../charts.js";
import { bytes, ms, number, percent, speedup } from "../format.js";

const STATUS = {
  optimized: ["Optimized", "fast"],
  already_fast: ["Already fast", "info"],
  no_improvement: ["No better index", "slow"],
  error: ["Could not analyze", "bad"],
};

const CANDIDATE_STATUS = {
  recommended: ["Recommended", "fast"],
  alternative: ["Also works", "info"],
  not_used: ["Planner ignored it", ""],
  too_small_gain: ["Gain too small", "slow"],
  result_mismatch: ["Changed results", "bad"],
  error: ["Error", "bad"],
};

function planLine(node) {
  let cls = "plan-line";
  if (/^SCAN /.test(node.detail) && !/USING INDEX/.test(node.detail)) cls += " scan";
  else if (/TEMP B-TREE/.test(node.detail)) cls += " sort";
  else if (/^SEARCH /.test(node.detail)) cls += " good";
  return h("div", { class: cls, style: `padding-left:${node.depth * 16}px` }, node.detail);
}

function planPanel(title, plan, findings, chip) {
  return h(
    "div",
    { class: "plan" },
    h("h4", {}, title, chip),
    plan.map(planLine),
    h(
      "div",
      { class: "findings" },
      findings.length
        ? findings.map((f) => h("div", { class: `finding ${f.severity}` }, f.message))
        : h("div", { class: "finding clear" }, "No full scans or temporary sorts."),
    ),
  );
}

function recommendation(rec) {
  const write = rec.write_overhead == null ? "inserts n/a" : `inserts +${percent(rec.write_overhead)}`;
  const trust = { high: "fast", medium: "info", low: "slow" }[rec.confidence];
  return h(
    "div",
    { class: "rec" },
    h(
      "div",
      { class: "rec-top" },
      h("div", {}, h("span", { class: "rank" }, `${rec.rank}.`), h("strong", {}, rec.candidate.name)),
      h("button", { class: "btn small", onclick: () => copyText(`${rec.create_sql};`, "Index SQL copied"), "aria-label": "Copy index SQL" }, icon("copy"), "Copy"),
    ),
    codeBlock(`${rec.create_sql};`, { wrap: true }),
    h(
      "div",
      { class: "metrics" },
      h("span", { class: "chip fast" }, `${ms(rec.baseline_ms)} to ${ms(rec.after_ms)}`),
      h("span", { class: "chip fast" }, `${speedup(rec.speedup)} faster`),
      h("span", { class: "chip" }, `+${bytes(rec.size_bytes)} on disk`),
      h("span", { class: "chip" }, write),
      h("span", { class: "chip" }, `built in ${ms(rec.build_ms)}`),
      h("span", { class: `chip ${trust}` }, `${rec.confidence} confidence`),
    ),
    h("p", { class: "explain" }, rec.explanation),
  );
}

function candidatesTable(tested) {
  const rows = tested.map((t) => {
    const [label, tone] = CANDIDATE_STATUS[t.status] || [t.status, ""];
    return h(
      "tr",
      {},
      h("td", {}, h("code", {}, t.candidate.create_sql || `${t.candidate.name}`)),
      h("td", {}, t.candidate.kind),
      h("td", {}, h("span", { class: `chip ${tone}` }, label)),
      h("td", { class: "num" }, t.speedup ? speedup(t.speedup) : "n/a"),
      h("td", { class: "num" }, t.size_bytes != null ? bytes(t.size_bytes) : "n/a"),
      h("td", { class: "num" }, t.write_overhead != null ? `+${percent(t.write_overhead)}` : "n/a"),
      h("td", { class: "muted" }, t.note || ""),
    );
  });
  return h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      {},
      h(
        "thead",
        {},
        h("tr", {}, ["Candidate", "Type", "Outcome", "Speedup", "Size", "Insert cost", "Note"].map((c, i) => h("th", { class: i >= 3 && i <= 5 ? "num" : "" }, c))),
      ),
      h("tbody", {}, rows),
    ),
  );
}

export function queryCard(q, open = false) {
  const [statusLabel, tone] = STATUS[q.status] || [q.status, ""];
  const head = h(
    "summary",
    {},
    h("div", { class: "qtitle" }, h("h3", {}, q.title || q.id), h("span", { class: `chip ${tone}` }, statusLabel)),
    q.status === "error"
      ? null
      : h("div", { class: "qgain" }, h("div", { class: "big" }, q.speedup > 1.05 ? speedup(q.speedup) : "ok"), h("div", { class: "sub" }, `${ms(q.baseline_ms)} to ${ms(q.final_ms)}`)),
    h("div", { class: "qmeta" }, q.message),
  );
  const body = [h("div", {}, h("div", { class: "section-title" }, "Query"), codeBlock(q.sql, { wrap: true }))];
  if (q.status === "error") {
    body.push(h("div", { class: "error" }, q.message));
  } else {
    if (q.recommendations.length) {
      body.push(vitals(q.baseline_ms, q.final_ms, q.speedup));
    }
    body.push(
      h(
        "div",
        { class: "plans" },
        planPanel("Plan before", q.plan_before, q.findings_before, null),
        planPanel("Plan with recommended indexes", q.plan_after, q.findings_after, q.recommendations.length ? h("span", { class: "chip fast" }, `${q.recommendations.length} new`) : null),
      ),
    );
    if (q.recommendations.length) {
      body.push(h("div", {}, h("div", { class: "section-title" }, "Recommendations", h("span", {}, "validated on a sandbox copy")), h("div", { class: "recs" }, q.recommendations.map(recommendation))));
    }
    if (q.tested.length) {
      body.push(h("div", {}, h("div", { class: "section-title" }, "Every candidate tested", h("span", {}, `${q.tested.length} indexes tried and dropped`)), candidatesTable(q.tested)));
    }
  }
  return h("details", { class: "qcard", open: open || null }, head, h("div", { class: "qbody" }, body));
}

export function summary(report) {
  const optimized = report.queries.filter((q) => q.status === "optimized");
  const indexes = new Set(optimized.flatMap((q) => q.recommendations.map((r) => r.candidate.name)));
  const gain = report.total_final_ms > 0 ? report.total_baseline_ms / report.total_final_ms : 1;
  const stat = (value, label, cls = "") => h("div", { class: `stat ${cls}` }, h("div", { class: "v" }, value), h("div", { class: "l" }, label));
  return h(
    "div",
    { class: "summary" },
    stat(report.headline, "Biggest improvement", "hero"),
    stat(`${optimized.length} of ${report.queries.length}`, "queries improved"),
    stat(String(indexes.size), "indexes recommended"),
    stat(`${ms(report.total_baseline_ms)} to ${ms(report.total_final_ms)}`, `total workload, ${speedup(gain)} faster`),
    stat(`${report.duration_s.toFixed(1)} s`, `analysis time on ${number(report.tables.reduce((a, t) => a + t.rows, 0))} rows`),
  );
}

export function migration(report) {
  let mode = "up";
  const holder = h("div", {});
  const tabs = h("div", { class: "tabs", role: "tablist" });
  const render = () => {
    const sql = mode === "up" ? report.migration_sql : report.rollback_sql;
    holder.replaceChildren(
      codeBlock(sql.trimEnd()),
      h(
        "div",
        { class: "row", style: "margin-top:12px" },
        h("button", { class: "btn", onclick: () => copyText(sql, "SQL copied") }, icon("copy"), "Copy SQL"),
        h("button", { class: "btn", onclick: () => download(mode === "up" ? "querydoctor-migration.sql" : "querydoctor-rollback.sql", sql) }, icon("download"), "Download .sql"),
      ),
    );
    for (const btn of tabs.children) btn.setAttribute("aria-selected", String(btn.dataset.mode === mode));
  };
  for (const [key, label] of [["up", "Migration"], ["down", "Rollback"]]) {
    tabs.append(h("button", { role: "tab", dataset: { mode: key }, onclick: () => { mode = key; render(); } }, label));
  }
  render();
  return h("section", { class: "card migration" }, h("h2", {}, "Ready-to-run SQL"), h("p", { class: "muted" }, "Only indexes that were proven on the sandbox copy appear here. Review them, then apply with your normal deployment process."), tabs, holder);
}

export function queryList(report) {
  const first = Math.max(0, report.queries.findIndex((q) => q.status === "optimized"));
  return h("div", { class: "qlist" }, report.queries.map((q, i) => queryCard(q, i === first)));
}
