import { h, svg } from "./dom.js";
import { ms, speedup } from "./format.js";

const WIDTH = 600;
const HEIGHT = 46;
const MID = 30;

// One heartbeat: flat lead-in, P wave, QRS spike, T wave, flat lead-out.
function beat(x, width, amp) {
  const at = (f) => (x + width * f).toFixed(1);
  const y = (d) => (MID + d).toFixed(1);
  return [
    `L${at(0.1)} ${y(0)}`,
    `Q${at(0.17)} ${y(-amp * 0.3)} ${at(0.24)} ${y(0)}`,
    `L${at(0.34)} ${y(0)}`,
    `L${at(0.385)} ${y(amp * 0.2)}`,
    `L${at(0.44)} ${y(-amp)}`,
    `L${at(0.495)} ${y(amp * 0.4)}`,
    `L${at(0.54)} ${y(0)}`,
    `Q${at(0.69)} ${y(-amp * 0.5)} ${at(0.83)} ${y(0)}`,
    `L${at(1)} ${y(0)}`,
  ].join(" ");
}

function trace(beats, amp) {
  const width = WIDTH / beats;
  let d = `M0 ${MID}`;
  for (let i = 0; i < beats; i += 1) d += ` ${beat(i * width, width, amp)}`;
  return d;
}

function strip(kind, label, time, beats, amp) {
  const path = svg("path", { d: trace(beats, amp), pathLength: "1" });
  return h(
    "div",
    { class: `vital ${kind} animate` },
    h("span", { class: "tag" }, label),
    svg("svg", { viewBox: `0 0 ${WIDTH} ${HEIGHT}`, preserveAspectRatio: "none", role: "img", "aria-label": `${label}: ${time}` }, path),
    h("span", { class: "time" }, time),
  );
}

// Both strips cover the same stretch of time: how long the old query took to run once.
// The healthy strip fits as many beats as the faster query could run in that window.
export function vitals(beforeMs, afterMs, gain) {
  const runs = Math.max(2, Math.min(48, Math.round(gain || 1)));
  return h(
    "div",
    { class: "vitals" },
    strip("before", "Before", ms(beforeMs), 1, 24),
    strip("after", "After", ms(afterMs), runs, 15),
    h(
      "p",
      { class: "vitals-note" },
      `Each beat is one execution. In the time the old query ran once, the new plan can run about ${runs >= 48 ? "48 or more" : runs} times.`,
    ),
  );
}

function logPercent(value, lo, hi) {
  const clamped = Math.max(value, lo);
  const pct = ((Math.log10(clamped) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo))) * 100;
  return Math.max(2, Math.min(100, pct));
}

// Horizontal bars on a log scale so a 1,000x win and a 3x win can share one chart.
export function latencyBars(queries) {
  const rows = queries.filter((q) => q.status !== "error" && q.baseline_ms != null);
  const hi = Math.max(...rows.map((q) => q.baseline_ms), 1) * 1.15;
  const lo = 0.005;
  return h(
    "div",
    { class: "bars", role: "img", "aria-label": "Latency before and after, log scale" },
    h(
      "div",
      { class: "legend" },
      h("span", {}, h("i", { style: "background: var(--slow)" }), "Before"),
      h("span", {}, h("i", { style: "background: var(--fast)" }), "After"),
      h("span", {}, "Log scale"),
    ),
    rows.map((q, i) =>
      h(
        "div",
        { class: "bar-row" },
        h("span", { class: "name" }, q.title || q.id),
        h(
          "div",
          { class: "bar-pair" },
          h("div", { class: "bar before", style: `width:${logPercent(q.baseline_ms, lo, hi)}%; animation-delay:${i * 60}ms`, title: ms(q.baseline_ms) }),
          h("div", { class: "bar after", style: `width:${logPercent(q.final_ms ?? q.baseline_ms, lo, hi)}%; animation-delay:${i * 60 + 200}ms`, title: ms(q.final_ms) }),
        ),
        h("span", { class: "gain" }, q.speedup && q.speedup > 1.05 ? speedup(q.speedup) : "ok"),
      ),
    ),
  );
}
