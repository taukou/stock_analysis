const test = require("node:test");
const assert = require("node:assert");
const F = require("../../static/js/format.js");

test("fmt keeps null as dash", () => {
  assert.strictEqual(F.fmtNum(null, " 元"), "—");
  assert.strictEqual(F.fmtSigned(0, "%"), "0%");
  assert.strictEqual(F.fmtSigned(1.5, "%"), "+1.5%");
});
test("heatColor", () => {
  assert.strictEqual(F.heatColor(null, 1), "#64748b");
  assert.strictEqual(F.heatColor(3, 1), "rgb(255, 77, 109)");
  assert.strictEqual(F.heatColor(-99, 20), "rgb(34, 197, 94)");
  assert.notStrictEqual(F.heatColor(1, 1), F.heatColor(2, 1));
});
test("lots", () => {
  assert.strictEqual(F.lots(null), null);
  assert.strictEqual(F.lots(12345), 12);
});
test("watchlist survives broken storage", () => {
  const mem = { d: {}, getItem(k) { return this.d[k] ?? null; }, setItem(k, v) { this.d[k] = v; } };
  assert.deepStrictEqual(F.loadWatchlist(mem), []);
  assert.strictEqual(F.toggleWatch(mem, "2330"), true);
  assert.deepStrictEqual(F.loadWatchlist(mem), ["2330"]);
  assert.strictEqual(F.toggleWatch(mem, "2330"), false);
  mem.d[F.WATCH_KEY] = "{bad";
  assert.deepStrictEqual(F.loadWatchlist(mem), []);
  assert.deepStrictEqual(F.loadWatchlist(null), []);
});

test("exKindInWindow", () => {
  const dates = ["01", "02", "03", "04", "05", "06"];
  const ex = k => [{ ex_date: "05", kind: k }];
  assert.strictEqual(F.exKindInWindow(ex("除息"), dates, 1), "除息");
  assert.strictEqual(F.exKindInWindow(ex("除息"), dates, 5), "除息");
  assert.strictEqual(F.exKindInWindow([{ ex_date: "02", kind: "除息" }], dates, 3), null);
  assert.strictEqual(F.exKindInWindow([{ ex_date: "03", kind: "除權" }], dates, 3), "除權");
  assert.strictEqual(F.exKindInWindow([{ ex_date: "03", kind: "除權" }], dates, 5), null); // 起點日本身不算
  assert.strictEqual(F.exKindInWindow(ex("除息"), dates, 6), null);
  assert.strictEqual(F.exKindInWindow([{ ex_date: "05", kind: "除息" }, { ex_date: "06", kind: "除權" }], dates, 5), "除權息");
});
