import { api, STATIC } from "./api.js";
import { h, icon, svg } from "./dom.js";
import { renderAnalyze } from "./views/analyze.js";
import { renderBenchmarks } from "./views/benchmarks.js";
import { renderSchema } from "./views/schema.js";

const ROUTES = {
  analyze: { label: "Analyze", icon: "analyze", render: renderAnalyze },
  benchmarks: { label: "Benchmarks", icon: "bench", render: renderBenchmarks },
  schema: { label: "Schema", icon: "schema", render: renderSchema },
};

function logo() {
  return svg(
    "svg",
    { viewBox: "0 0 32 32", "aria-hidden": "true" },
    svg("rect", { width: "32", height: "32", rx: "9", fill: "#142130" }),
    svg("path", { d: "M3 17h7l3-8 4 15 3-9 2 2h7", fill: "none", stroke: "#74e0d0", "stroke-width": "2.4", "stroke-linecap": "round", "stroke-linejoin": "round" }),
  );
}

function demoBanner() {
  return h(
    "div",
    { class: "demo-banner", role: "note" },
    h("strong", {}, "Hosted demo."),
    " Everything below is replayed from a real benchmark run on a 1,020,000-row database. To analyze your own queries, run it locally: ",
    h("code", {}, "pip install -e . && querydoctor seed && querydoctor serve"),
    ". ",
    h("a", { href: "https://github.com/ContentbyShanu/querydoctor" }, "View the source on GitHub"),
    ".",
  );
}

function currentRoute() {
  const fallback = STATIC ? "benchmarks" : "analyze";
  const key = location.hash.replace(/^#\/?/, "") || fallback;
  return ROUTES[key] ? key : fallback;
}

function build() {
  const app = document.getElementById("app");
  const main = h("main", { class: "main", id: "main" });
  const foot = h("div", { class: "rail-foot" }, "Checking database...");
  const nav = h(
    "nav",
    { class: "nav", "aria-label": "Sections" },
    Object.entries(ROUTES).map(([key, r]) => h("a", { href: `#/${key}`, dataset: { route: key } }, icon(r.icon), h("span", {}, r.label))),
  );
  app.replaceChildren(
    h("div", { class: "shell" }, h("aside", { class: "rail" }, h("a", { class: "brand", href: STATIC ? "#/benchmarks" : "#/analyze" }, logo(), h("b", {}, "QueryDoctor")), nav, foot), main),
  );
  return { main, nav, foot };
}

async function paintStatus(foot) {
  try {
    const health = await api.health();
    if (health.demo) {
      foot.replaceChildren(h("strong", {}, h("span", { class: "dot ok" }), "Demo mode"), `Replaying real results, v${health.version}`);
      return;
    }
    foot.replaceChildren(
      h("strong", {}, h("span", { class: `dot ${health.database_ready ? "ok" : "off"}` }), health.database_ready ? "Database ready" : "No database"),
      health.database_ready ? `SQLite ${health.sqlite_version}, v${health.version}` : "Run querydoctor seed",
    );
  } catch {
    foot.replaceChildren(h("strong", {}, h("span", { class: "dot off" }), "Server offline"));
  }
}

function start() {
  const { main, nav, foot } = build();
  const show = () => {
    const key = currentRoute();
    for (const link of nav.children) link.toggleAttribute("aria-current", link.dataset.route === key);
    for (const link of nav.children) if (link.dataset.route === key) link.setAttribute("aria-current", "page");
    document.title = `${ROUTES[key].label} - QueryDoctor`;
    ROUTES[key].render(main);
    if (STATIC) main.prepend(demoBanner());
  };
  window.addEventListener("hashchange", show);
  show();
  paintStatus(foot);
}

start();
