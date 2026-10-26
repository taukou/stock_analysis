// 產業頁的版面計算純函式（不碰 DOM）：瀏覽器掛在 window.Layout，node 以 module.exports 匯出供測試
(function (root) {
  const isNil = v => v === null || v === undefined;

  // ---- 總覽：上中下游三欄，每欄節點依序等距排列；太擠時左右交錯，讓名稱與平均值不被鄰居蓋住 ----
  const COLUMN_X = { Upstream: 0.15, Midstream: 0.5, Downstream: 0.85 };
  const HEX_ABOVE = 50, HEX_BELOW = 90;          // 六角形（半徑 45）上緣與下方兩行文字的範圍
  const STAGGER_DX = 80;
  function overviewPositions(nodes, width, height, top = 100, bottom = 50) {
    const groups = new Map();
    nodes.forEach(n => {
      const key = n.group in COLUMN_X ? n.group : "Midstream";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(n);
    });
    const NODE_H = HEX_ABOVE + HEX_BELOW;
    const span = Math.max(height - top - bottom - NODE_H, 0);   // 第一個與最後一個節點中心的可用距離
    const out = new Map();
    groups.forEach((list, key) => {
      const k = list.length;
      const step = k > 1 ? Math.min(span / (k - 1), 200) : 0;
      const stagger = k > 1 && step < NODE_H ? STAGGER_DX : 0;
      const y0 = top + HEX_ABOVE + (span - step * (k - 1)) / 2;   // 整欄垂直置中
      list.forEach((n, i) => {
        const dx = stagger ? (i % 2 ? stagger : -stagger) : 0;
        out.set(n.id, [width * COLUMN_X[key] + dx, y0 + step * i]);
      });
    });
    return out;
  }

  // ---- 聚焦：公司依目前區間漲跌由強到弱排序（缺值排最後） ----
  function byChangeDesc(a, b) {
    const na = isNil(a.change), nb = isNil(b.change);
    if (na !== nb) return na ? 1 : -1;
    if (!na && a.change !== b.change) return b.change - a.change;
    return String(a.id).localeCompare(String(b.id));
  }

  // 公司少：繞中心六角形一圈（12 點鐘方向起順時針，由強到弱）
  const RING_MAX = 10;
  function ringPositions(n, area) {
    const cx = area.x + area.w / 2, cy = area.y + area.h / 2;
    const R = Math.max(120, Math.min(200, area.h / 2 - 80, area.w / 2 - 60));
    return Array.from({ length: n }, (_, i) => {
      const a = -Math.PI / 2 + 2 * Math.PI * i / n;
      return [cx + R * Math.cos(a), cy + R * Math.sin(a) - 10];
    });
  }

  // 公司多：排行網格（由左到右、由上到下），避開中心六角形；格子越小球越小、標籤越精簡
  const LABEL_MODES = [
    { label: "full", minW: 100, minH: 80, labelH: 34 },     // 名稱＋股價（漲跌）
    { label: "compact", minW: 72, minH: 52, labelH: 26 },   // 名稱＋漲跌
    { label: "none", minW: 0, minH: 0, labelH: 0 },         // 只有球（滑鼠移上去看名稱）
  ];
  const MAX_CELL_W = 160, MAX_CELL_H = 140, FULL_RADIUS = 40;
  const HOLE_W = 170, HOLE_ABOVE = 55, HOLE_BELOW = 95;

  function gridPositions(n, area) {
    const cx = area.x + area.w / 2, cy = area.y + area.h / 2;
    const hole = { x0: cx - HOLE_W / 2, x1: cx + HOLE_W / 2, y0: cy - HOLE_ABOVE, y1: cy + HOLE_BELOW };
    let best = null;
    for (let cols = 1; cols <= n + 4; cols++) {
      const cellW = Math.min(area.w / cols, MAX_CELL_W);
      for (let rows = 1; rows <= n + 4; rows++) {
        const cellH = Math.min(area.h / rows, MAX_CELL_H);
        const x0 = area.x + (area.w - cols * cellW) / 2, y0 = area.y + (area.h - rows * cellH) / 2;
        const free = [];
        for (let r = 0; r < rows; r++) {
          for (let c = 0; c < cols; c++) {
            const left = x0 + c * cellW, top = y0 + r * cellH;
            const hit = left < hole.x1 && left + cellW > hole.x0 && top < hole.y1 && top + cellH > hole.y0;
            if (!hit) free.push([left, top]);
          }
        }
        if (free.length < n) continue;
        const mode = LABEL_MODES.find(m => cellW >= m.minW && cellH >= m.minH);
        const maxR = Math.min(cellW / 2 - 6, (cellH - mode.labelH) / 2 - 3);
        const scale = Math.max(0.15, Math.min(1, maxR / FULL_RADIUS));
        const score = (LABEL_MODES.length - LABEL_MODES.indexOf(mode)) * 10 + scale;
        if (!best || score > best.score) {
          const ballDy = (cellH - mode.labelH) / 2;
          best = {
            score, scale, label: mode.label, cellW, cellH,
            cells: free.slice(0, n).map(([l, t]) => [l + cellW / 2, t + ballDy]),
          };
        }
        break;   // 這個欄數下最少的列數已找到
      }
    }
    return best;
  }

  // 回傳 { positions: [[x, y]...]（對應 sorted 順序）, scale, label, sorted }
  function focusPlan(companies, area) {
    const sorted = companies.slice().sort(byChangeDesc);
    if (sorted.length <= RING_MAX) {
      return { sorted, positions: ringPositions(sorted.length, area), scale: 1, label: "full" };
    }
    const g = gridPositions(sorted.length, area);
    return { sorted, positions: g.cells, scale: g.scale, label: g.label, cellW: g.cellW, cellH: g.cellH };
  }

  const api = { overviewPositions, byChangeDesc, RING_MAX, ringPositions, gridPositions, focusPlan, FULL_RADIUS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Layout = api;
})(typeof window !== "undefined" ? window : globalThis);
