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
