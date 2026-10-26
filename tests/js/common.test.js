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
