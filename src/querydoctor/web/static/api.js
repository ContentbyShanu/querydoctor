import { bytes, ms, speedup } from "./format.js";

// On GitHub Pages there is no Python server. index.html sets this flag and the API layer
// replays the results of a real benchmark run instead of calling the backend.
export const STATIC = globalThis.QUERYDOCTOR_STATIC === true;

const DEMO_MESSAGE =
  "This hosted demo replays the ten benchmark queries. To analyze your own SQL, run QueryDoctor locally with `querydoctor serve`.";

async function request(path, options) {
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new Error("Cannot reach the QueryDoctor server. Is `querydoctor serve` still running?");
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d) => d.msg).join("; ");
    } catch {
      /* keep default message */
    }
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

// ---- static demo adapter -------------------------------------------------------------

let benchCache = null;
function loadBench() {
  benchCache ??= request(new URL("docs/benchmarks.json", document.baseURI).href).catch((err) => {
    benchCache = null;
    throw new Error(`Benchmark data could not be loaded. ${err.message}`);
  });
  return benchCache;
}

function normalize(sql) {
  return sql
    .split("\n")
    .filter((line) => !line.trim().startsWith("--"))
    .join(" ")
    .replace(/;\s*$/, "")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function statements(sql) {
  return sql
    .split(";")
    .map((part) => part.trim())
    .filter((part) => normalize(part).length > 0);
}

function migrationFor(queries) {
  const unique = new Map();
  for (const q of queries) {
    for (const rec of q.recommendations) {
      if (!unique.has(rec.candidate.name)) unique.set(rec.candidate.name, { rec, title: q.title || q.id });
    }
  }
  const up = ["-- QueryDoctor migration (replayed from the benchmark run)", "-- Every index below was validated on a sandbox copy of the database.", ""];
  const down = ["-- QueryDoctor rollback", ""];
  for (const { rec, title } of unique.values()) {
    up.push(`-- ${title}: ${ms(rec.baseline_ms)} to ${ms(rec.after_ms)} (${speedup(rec.speedup)}), +${bytes(rec.size_bytes)}, confidence ${rec.confidence}`);
    up.push(`${rec.create_sql.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ")};`, "");
    down.push(`${rec.rollback_sql};`);
  }
  if (!unique.size) up.push("-- No index changes recommended.");
  return [`${up.join("\n").trimEnd()}\n`, `${down.join("\n").trimEnd()}\n`];
}

async function analyzeStatic(sql) {
  const { report } = await loadBench();
  const wanted = statements(sql);
  if (!wanted.length) throw new Error("No SQL statements found.");
  const matches = wanted.map((stmt) => {
    const hit = report.queries.find((q) => normalize(q.sql) === normalize(stmt));
    if (!hit) throw new Error(DEMO_MESSAGE);
    return hit;
  });
  const [migrationSql, rollbackSql] = migrationFor(matches);
  const improved = matches.filter((q) => q.status === "optimized");
  const best = improved.sort((a, b) => b.speedup - a.speedup)[0];
  return {
    ...report,
    queries: matches,
    total_baseline_ms: matches.reduce((sum, q) => sum + (q.baseline_ms || 0), 0),
    total_final_ms: matches.reduce((sum, q) => sum + (q.final_ms || 0), 0),
    headline: best ? `${best.title}: ${ms(best.baseline_ms)} to ${ms(best.final_ms)} (${speedup(best.speedup)} faster)` : "No index changes were needed.",
    migration_sql: migrationSql,
    rollback_sql: rollbackSql,
  };
}

const staticApi = {
  health: async () => {
    const { environment } = await loadBench();
    return { status: "ok", version: environment.querydoctor, sqlite_version: environment.sqlite, database_ready: true, demo: true };
  },
  schema: async () => (await loadBench()).report.tables,
  samples: async () => (await loadBench()).report.queries.map((q) => ({ id: q.id, title: q.title, sql: q.sql })),
  benchmarks: loadBench,
  analyze: analyzeStatic,
};

// ---- live backend --------------------------------------------------------------------

const liveApi = {
  health: () => request("/api/health"),
  schema: () => request("/api/schema"),
  samples: () => request("/api/samples"),
  benchmarks: () => request("/api/benchmarks"),
  analyze: (sql) =>
    request("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql }),
    }),
};

export const api = STATIC ? staticApi : liveApi;
