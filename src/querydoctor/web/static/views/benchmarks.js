import { api } from "../api.js";
import { latencyBars } from "../charts.js";
import { clear, h } from "../dom.js";
import { bytes, number } from "../format.js";
import { migration, queryList, summary } from "./report.js";

export async function renderBenchmarks(root) {
  clear(root);
  root.append(h("header", { class: "page-head" }, h("h1", {}, "Benchmark results"), h("p", {}, "Ten realistic slow queries on a one million row shop database. Every number comes from a real run, not an estimate.")));
  const body = h("div", {}, h("div", { class: "skeleton" }));
  root.append(body);
  try {
    const { environment, report } = await api.benchmarks();
    const rows = report.tables.reduce((a, t) => a + t.rows, 0);
    body.replaceChildren(
      summary(report),
      h("section", { class: "card" }, h("h2", { style: "margin-bottom:14px" }, "Latency before and after"), latencyBars(report.queries)),
      h("p", { class: "muted", style: "margin:16px 2px" }, `${number(rows)} rows, ${bytes(report.database_bytes)} database. SQLite ${environment.sqlite}, Python ${environment.python}, ${environment.platform}.`),
      queryList(report),
      h("div", { style: "margin-top:18px" }, migration(report)),
    );
  } catch (err) {
    body.replaceChildren(
      h("div", { class: "empty" }, h("h3", {}, "No benchmark has been run yet"), h("p", {}, err.message), h("code", { class: "code" }, "querydoctor seed && querydoctor bench")),
    );
  }
}
