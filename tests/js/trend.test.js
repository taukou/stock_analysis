const test = require("node:test");
const assert = require("node:assert");
const T = require("../../static/js/trend.js");

test("series keys per mode and node cap", () => {
  assert.deepStrictEqual(T.seriesKeys("M02", "industry", []), ["market:TW", "major:M02"]);
  assert.strictEqual(T.seriesKeys("M02", "tiers", ["a", "b", "c", "d", "e", "f"]).length, 4 + 5);
});

test("first date note only when history is shorter than range", () => {
  assert.strictEqual(T.firstDateNote({ "major:M02": "2026-07-23" }, "2025-10-27"), "指數資料從 2026-07-23 起");
  assert.strictEqual(T.firstDateNote({ "major:M02": "2025-10-01" }, "2026-07-27"), null);
});

test("first date note takes the latest first date and ignores nulls", () => {
  assert.strictEqual(T.firstDateNote({ a: "2026-01-05", b: "2026-03-02", c: null }, "2025-10-27"), "指數資料從 2026-03-02 起");
  assert.strictEqual(T.firstDateNote({ a: null }, "2025-10-27"), null);
});

test("range start estimate and tier filtering", () => {
  assert.strictEqual(T.rangeStart("1M", new Date("2026-10-27T00:00:00Z")), "2026-09-28");
  const have = { "market:TW": [1], "tier:M02:Upstream": [1], "tier:M02:Midstream": [], "tier:M02:Downstream": [1] };
  assert.deepStrictEqual(T.visibleKeys(T.seriesKeys("M02", "tiers", []), have),
    ["market:TW", "tier:M02:Upstream", "tier:M02:Downstream"]);
});

test("fixed notes equal the python constants and stay out of the cleared node", () => {
  const fs = require("node:fs");
  const py = fs.readFileSync(require("node:path").join(__dirname, "../../industry_trends.py"), "utf8");
  const get = n => py.match(new RegExp(`^${n} = "(.*)"`, "m"))[1];
  assert.strictEqual(T.MARKET_NOTE, get("MARKET_NOTE"));
  assert.strictEqual(T.SURVIVOR_NOTE, get("SURVIVOR_NOTE"));
  // 固定註記在獨立節點；load() 只清動態節點 #trend-notes，成功、無資料、錯誤三種狀態都不影響它
  const js = fs.readFileSync(require("node:path").join(__dirname, "../../static/js/industry.js"), "utf8");
  assert.ok(/trend-notes-fixed/.test(js));
  assert.ok(!/trend-notes-fixed[^\n]*innerHTML\s*=/.test(js));
  const html = fs.readFileSync(require("node:path").join(__dirname, "../../templates/industry_d3.html"), "utf8");
  assert.ok(html.includes('id="trend-notes-fixed"'));
});

test("relative ranks: diff vs node average, lead/lag counts, nulls untouched", () => {
  const cs = [1, 2, 3, 4, 5, 6, 7].map((v, i) => ({ id: `c${i}`, change: v })).concat([{ id: "n", change: null }]);
  const r = T.relativeRanks(cs);
  assert.deepStrictEqual(r.get("c6"), { diff: 3, tag: "lead" });
  assert.strictEqual(r.get("c0").tag, "lag");
  assert.strictEqual([...r.values()].filter(v => v.tag === "lead").length, 3);
  assert.deepStrictEqual(r.get("n"), { diff: null, tag: null });
  assert.strictEqual(T.relativeRanks([{ id: "a", change: 1 }]).get("a").tag, null);
});
test("formatLots", () => {
  assert.strictEqual(T.formatLots(null), "—");
  assert.strictEqual(T.formatLots(1234), "+1,234 張");
  assert.strictEqual(T.formatLots(-5), "-5 張");
});

test("sortRows puts null last in both directions", () => {
  const rows = [{ k: 2 }, { k: null }, { k: 5 }, { k: -1 }];
  assert.deepStrictEqual(T.sortRows(rows, "k", true).map(r => r.k), [5, 2, -1, null]);
  assert.deepStrictEqual(T.sortRows(rows, "k", false).map(r => r.k), [-1, 2, 5, null]);
  assert.strictEqual(rows[0].k, 2);   // 不改動原陣列
});

test("alerts: threshold, signals, ex today; null change ignored", () => {
  const c = { latest_change: -6.2, signals: [{ label: "爆量" }], ex_today: "息" };
  assert.deepStrictEqual(T.alertsFor(c, 5), ["大跌 -6.20%", "爆量", "今日除權息"]);
  assert.deepStrictEqual(T.alertsFor({ latest_change: null, signals: [], ex_today: null }, 5), []);
  assert.deepStrictEqual(T.alertsFor({ latest_change: 4.99, signals: [], ex_today: null }, 5), []);
  assert.deepStrictEqual(T.alertsFor({ latest_change: 5, signals: [], ex_today: null }, 5), ["大漲 +5.00%"]);
});

test("contentWidth subtracts horizontal padding so charts never overflow their box", () => {
  const el = { clientWidth: 900 };
  const cs = () => ({ paddingLeft: "20px", paddingRight: "18px" });
  assert.strictEqual(T.contentWidth(el, cs), 862);
  assert.strictEqual(T.contentWidth({ clientWidth: 0 }, cs), 0);
  assert.strictEqual(T.contentWidth(el, () => ({})), 900);
  assert.strictEqual(T.contentWidth(el, undefined), 900);
});
