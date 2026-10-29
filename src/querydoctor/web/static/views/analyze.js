import { api } from "../api.js";
import { clear, h, icon } from "../dom.js";
import { migration, queryList, summary } from "./report.js";

const state = { sql: "", report: null, error: null, running: false };

function results(report) {
  return h("section", { id: "results" }, summary(report), queryList(report), h("div", { style: "margin-top:18px" }, migration(report)));
}

export async function renderAnalyze(root) {
  clear(root);
  const status = h("div", {});
  const output = h("div", {});
  const input = h("textarea", {
    class: "sql-input",
    spellcheck: "false",
    placeholder: "SELECT id, total_cents FROM orders WHERE user_id = 42 ORDER BY created_at DESC LIMIT 20;",
    "aria-label": "SQL queries to analyze",
  });
  input.value = state.sql;
  input.addEventListener("input", () => { state.sql = input.value; });

  const run = h("button", { class: "btn primary" }, icon("play"), "Run analysis");
  const chips = h("div", { class: "chips" });

  const paint = () => {
    run.disabled = state.running;
    output.replaceChildren();
    if (state.error) output.append(h("div", { class: "error", role: "alert", style: "margin-top:18px" }, state.error));
    else if (state.running) output.append(h("div", { style: "margin-top:22px; display:grid; gap:14px" }, h("div", { class: "skeleton" }), h("div", { class: "skeleton" })));
    else if (state.report) output.append(results(state.report));
  };

  const analyze = async () => {
    if (state.running) return;
    const sql = input.value.trim();
    if (!sql) {
      state.error = "Paste at least one SELECT query, or pick an example below the editor.";
      paint();
      return;
    }
    state.running = true;
    state.error = null;
    const started = Date.now();
    status.replaceChildren(h("div", { class: "working" }, h("span", { class: "pulse-dot" }), h("span", { id: "elapsed" }, "Copying the database and testing candidate indexes...")));
    const timer = setInterval(() => {
      const el = document.getElementById("elapsed");
      if (el) el.textContent = `Testing candidate indexes on a sandbox copy... ${Math.round((Date.now() - started) / 1000)} s`;
    }, 1000);
    paint();
    try {
      state.report = await api.analyze(sql);
    } catch (err) {
      state.report = null;
      state.error = err.message;
    } finally {
      clearInterval(timer);
      state.running = false;
      status.replaceChildren();
      paint();
      document.getElementById("results")?.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    }
  };
  run.addEventListener("click", analyze);
  input.addEventListener("keydown", (e) => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") analyze(); });

  root.append(
    h("header", { class: "page-head" }, h("h1", {}, "Find the index your query is missing"), h("p", {}, "Paste slow SELECT statements. QueryDoctor tries every index idea on a private copy of your database, measures the difference, and only recommends what it can prove.")),
    h("section", { class: "card editor" }, input, h("div", { class: "row" }, run, h("span", { class: "muted" }, "Up to 10 read-only queries. Press Ctrl+Enter to run.")), chips, status),
    output,
  );
  paint();

  try {
    const samples = await api.samples();
    chips.append(h("span", { class: "muted" }, "Try an example:"));
    for (const s of samples) {
      chips.append(h("button", { class: "chip", onclick: () => { input.value = `-- name: ${s.title}\n${s.sql};`; state.sql = input.value; input.focus(); } }, s.title));
    }
  } catch {
    /* examples are optional */
  }
}
