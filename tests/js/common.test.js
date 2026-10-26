const test = require("node:test");
const assert = require("node:assert");
const C = require("../../static/js/common.js");
test("freshnessClass", () => {
  assert.strictEqual(C.freshnessClass("ok"), "fresh-ok");
  assert.strictEqual(C.freshnessClass("failed"), "fresh-failed");
  assert.strictEqual(C.freshnessClass(undefined), "fresh-stale");
});
test("searchUrl", () => {
  assert.strictEqual(C.searchUrl({ stock_id: "2330", node_id: "N201", major_id: "M01" }), "/industry/M01?node=N201&company=2330");
  assert.strictEqual(C.searchUrl({ stock_id: "2330", node_id: null, major_id: "M01" }), null);
  assert.strictEqual(C.searchUrl({ stock_id: "2330", node_id: "N201" }), null);
});
test("freshnessTooltip uses Chinese labels", () => {
  const t = C.freshnessTooltip([
    { dataset: "quotes", label: "股價", last_date: "2026-10-22", status: "ok" },
    { dataset: "revenue", label: "月營收", last_date: null, status: "failed" },
  ]);
  assert.strictEqual(t, "股價：2026-10-22（正常）\n月營收：—（失敗）");
  assert.strictEqual(C.freshnessTooltip(undefined), "");
});
