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

// 最小 DOM 替身：只模擬 mountSearch 用到的部分
function fakeSearchEnv(results) {
  const el = () => ({ style: {}, classList: { add() {} }, appendChild() {}, addEventListener() {}, replaceChildren() {} });
  globalThis.document = { createElement: el };
  globalThis.location = { href: "" };
  const fetched = [];
  globalThis.fetch = url => {
    const q = decodeURIComponent(url.split("q=")[1]);
    fetched.push(q);
    return Promise.resolve({ ok: true, json: () => Promise.resolve(results[q] || []) });
  };
  const handlers = {};
  const input = {
    value: "", addEventListener(t, f) { handlers[t] = f; }, blur() {},
    getBoundingClientRect: () => ({ left: 0, bottom: 0, width: 100 }),
  };
  C.mountSearch(input, el());
  const type = v => { input.value = v; handlers.input(); };
  const key = k => handlers.keydown({ key: k });
  return { type, key, fetched };
}
const wait = ms => new Promise(r => setTimeout(r, ms));

test("Enter during debounce searches the current text, not the previous hits", async () => {
  const env = fakeSearchEnv({
    "聯": [{ stock_id: "2454", node_id: "N102", major_id: "M01" }],
    "台積": [{ stock_id: "2330", node_id: "N201", major_id: "M01" }],
  });
  env.type("聯");
  await wait(320);                        // 第一次查詢完成，下拉有 2454
  env.type("台積");
  env.key("Enter");                       // 仍在 250ms debounce 內
  await wait(20);
  assert.strictEqual(location.href, "/industry/M01?node=N201&company=2330");
  assert.deepStrictEqual(env.fetched, ["聯", "台積"]);
  await wait(300);
  assert.deepStrictEqual(env.fetched, ["聯", "台積"]);   // 被 Enter 取代的計時器不會再查一次
});
