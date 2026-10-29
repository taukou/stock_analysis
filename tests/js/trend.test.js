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

test("rotation guide: plain-language quadrant text and per-quadrant counts", () => {
  assert.deepStrictEqual(Object.keys(T.QUAD_INFO), ["領先", "轉弱", "落後", "轉強"]);
  assert.strictEqual(T.describePoint({ name: "半導體", quadrant: "轉弱", x: 101.2, y: 98.5 }),
    "半導體在「轉弱」：仍比大盤強，但優勢在縮小");
  // 缺 quadrant 時依 x、y 判斷（100 本身算偏強／加速）
  assert.strictEqual(T.describePoint({ name: "PCB", x: 100, y: 100 }), "PCB在「領先」：比大盤強，而且越來越強");
  const pts = [{ quadrant: "領先" }, { quadrant: "領先" }, { x: 99, y: 101 }];
  assert.deepStrictEqual(T.quadrantCounts(pts), { 領先: 2, 轉弱: 0, 落後: 0, 轉強: 1 });
});

test("spreadLabels pushes overlapping labels apart and leaves free ones alone", () => {
  const items = [{ x: 100, y: 200, w: 60 }, { x: 110, y: 204, w: 60 }, { x: 400, y: 200, w: 60 }];
  const ys = T.spreadLabels(items, 13);
  assert.strictEqual(ys[2], 200);
  assert.ok(Math.abs(ys[0] - ys[1]) >= 13);
  assert.ok(ys.slice(0, 2).includes(200));
});

test("spreadLabels terminates when float rounding makes the gap 12.999… (real 2026-10-29 data)", () => {
  const items = [{ x: 481.0681031165834, y: 251.18864869241364, w: 81 },
                 { x: 481.48557137360496, y: 266.84649016273994, w: 48 },
                 { x: 443.91342824163144, y: 263.6394623917092, w: 48 }];
  const ys = T.spreadLabels(items, 13);           // 修正前這裡會無窮迴圈
  assert.ok(ys.every(Number.isFinite));
  assert.ok(Math.abs(ys[2] - ys[0]) >= 12.99 && Math.abs(ys[1] - ys[0]) >= 12.99);
});
