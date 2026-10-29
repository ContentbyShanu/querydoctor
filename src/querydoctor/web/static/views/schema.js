import { api } from "../api.js";
import { clear, h } from "../dom.js";
import { number } from "../format.js";

export async function renderSchema(root) {
  clear(root);
  root.append(h("header", { class: "page-head" }, h("h1", {}, "Database schema"), h("p", {}, "The tables QueryDoctor can see, and the indexes they already have. Recommendations never repeat an index that exists.")));
  const body = h("div", {}, h("div", { class: "skeleton" }));
  root.append(body);
  try {
    const tables = await api.schema();
    body.replaceChildren(
      h(
        "div",
        { class: "tables" },
        tables.map((t) =>
          h(
            "article",
            { class: "card tcard" },
            h("h3", {}, t.name, h("span", { class: "muted mono", style: "font-size:0.85rem" }, `${number(t.rows)} rows`)),
            h("div", { class: "cols" }, t.columns.map((c) => h("code", {}, c))),
            t.indexes.length ? h("div", { class: "row" }, t.indexes.map((i) => h("span", { class: "chip fast" }, i))) : h("span", { class: "chip slow" }, "Primary key only"),
          ),
        ),
      ),
    );
  } catch (err) {
    body.replaceChildren(h("div", { class: "empty" }, h("h3", {}, "No database found"), h("p", {}, err.message), h("code", { class: "code" }, "querydoctor seed")));
  }
}
