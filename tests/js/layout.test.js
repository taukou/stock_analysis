const test = require("node:test");
const assert = require("node:assert");
const L = require("../../static/js/layout.js");

test("overview: crowded column staggers, labels of neighbours don't overlap", () => {
  const nodes = [
    ...["a", "b"].map(id => ({ id, group: "Upstream" })),
    ...Array.from({ length: 7 }, (_, i) => ({ id: `d${i}`, group: "Downstream" })),
  ];
  const pos = L.overviewPositions(nodes, 1440, 900);
  assert.strictEqual(pos.get("a")[0], 1440 * 0.15);          // 只有 2 個：不交錯
  const down = Array.from({ length: 7 }, (_, i) => pos.get(`d${i}`));
  assert.notStrictEqual(down[0][0], down[1][0]);              // 7 個：左右交錯
  for (let i = 0; i + 2 < 7; i++) {                           // 同一側上下相鄰：六角形＋兩行文字（約 140px）不重疊
    assert.strictEqual(down[i][0], down[i + 2][0]);
    assert.ok(down[i + 2][1] - down[i][1] >= 140);
  }
  down.forEach(([, y]) => assert.ok(y - 50 >= 100 && y + 90 <= 900 - 50 + 1));
});

test("byChangeDesc puts strongest first and missing last", () => {
  const cs = [{ id: "c", change: null }, { id: "a", change: -1 }, { id: "b", change: 2 }, { id: "d", change: 0 }];
  assert.deepStrictEqual(cs.sort(L.byChangeDesc).map(c => c.id), ["b", "d", "a", "c"]);
});

function overlap(a, b) { return a.x0 < b.x1 && b.x0 < a.x1 && a.y0 < b.y1 && b.y0 < a.y1; }

test("focus grid fits 94 companies without overlap and avoids the centre hex", () => {
  for (const area of [{ x: 170, y: 120, w: 1100, h: 700 }, { x: 170, y: 120, w: 724, h: 700 }]) {
    const cs = Array.from({ length: 94 }, (_, i) => ({ id: `c${i}`, change: (i % 13) - 6 }));
    const p = L.focusPlan(cs, area);
    assert.strictEqual(p.positions.length, 94);
    assert.notStrictEqual(p.label, "none");
    const r = L.FULL_RADIUS * p.scale;
    const boxes = p.positions.map(([x, y]) => ({ x0: x - p.cellW / 2 + 0.5, x1: x + p.cellW / 2 - 0.5, y0: y - r, y1: y + r }));
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) assert.ok(!overlap(boxes[i], boxes[j]), `cells ${i} ${j} overlap`);
    }
    const cx = area.x + area.w / 2, cy = area.y + area.h / 2;
    const hex = { x0: cx - 45, x1: cx + 45, y0: cy - 45, y1: cy + 45 };
    boxes.forEach((b, i) => assert.ok(!overlap(b, hex), `cell ${i} covers the hex`));
    p.positions.forEach(([x, y]) => assert.ok(x >= area.x && x <= area.x + area.w && y >= area.y && y <= area.y + area.h));
    // 排行：第一格是最強的
    assert.strictEqual(p.sorted[0].change, 6);
  }
});

test("focus ring for few companies", () => {
  const p = L.focusPlan([{ id: "a", change: 1 }, { id: "b", change: 3 }], { x: 0, y: 0, w: 1000, h: 700 });
  assert.deepStrictEqual(p.sorted.map(c => c.id), ["b", "a"]);
  assert.strictEqual(p.scale, 1);
  assert.strictEqual(p.label, "full");
  assert.ok(p.positions[0][1] < 350);   // 最強的在 12 點鐘方向
});

test("overview: very crowded tier shrinks and spreads into several sub-columns without overlap", () => {
  const nodes = [
    ...Array.from({ length: 25 }, (_, i) => ({ id: `u${i}`, group: "Upstream" })),
    ...Array.from({ length: 8 }, (_, i) => ({ id: `d${i}`, group: "Downstream" })),
  ];
  const { positions, scale } = L.overviewPlan(nodes, 1440, 900);
  assert.ok(scale < 1 && scale >= 0.55);
  const up = Array.from({ length: 25 }, (_, i) => positions.get(`u${i}`));
  const xs = new Set(up.map(([x]) => x));
  assert.ok(xs.size >= 3);
  xs.forEach(x => assert.ok(Math.abs(x - 1440 * 0.15) <= 1440 * 0.15));   // 不跑出上游那一區
  const nodeH = 140 * scale;
  for (let i = 0; i < 25; i++) for (let j = i + 1; j < 25; j++) {
    const [ax, ay] = up[i], [bx, by] = up[j];
    if (ax === bx) assert.ok(Math.abs(ay - by) >= nodeH - 0.01, `${i} ${j} too close`);
  }
  up.forEach(([, y]) => assert.ok(y - 50 * scale >= 100 - 0.01 && y + 90 * scale <= 900 - 50 + 0.01));
});

test("overview: normal industries keep full size", () => {
  const nodes = Array.from({ length: 6 }, (_, i) => ({ id: `n${i}`, group: "Downstream" }));
  assert.strictEqual(L.overviewPlan(nodes, 1440, 900).scale, 1);
});
