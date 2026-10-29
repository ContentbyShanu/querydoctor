import { h } from "./dom.js";

const KEYWORDS = new Set(
  ("select from where and or not in is null join inner left right outer cross on as group by order having limit offset " +
    "union all distinct case when then else end exists between like asc desc with create index unique drop if " +
    "count sum avg min max cast over partition values insert update delete set").split(" "),
);
const TOKEN = /(--[^\n]*)|('(?:[^']|'')*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|(\s+|.)/g;

export function highlightSql(sql) {
  const frag = document.createDocumentFragment();
  for (const match of sql.matchAll(TOKEN)) {
    const [text, comment, string, number, word] = match;
    let cls = null;
    if (comment) cls = "tok-c";
    else if (string) cls = "tok-s";
    else if (number) cls = "tok-n";
    else if (word && KEYWORDS.has(word.toLowerCase())) cls = "tok-k";
    else if (word && word.startsWith("idx_")) cls = "tok-i";
    frag.append(cls ? h("span", { class: cls }, text) : document.createTextNode(text));
  }
  return frag;
}

export function codeBlock(sql, { wrap = false } = {}) {
  return h("pre", { class: wrap ? "code wrap" : "code" }, highlightSql(sql));
}
