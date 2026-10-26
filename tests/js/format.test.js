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
