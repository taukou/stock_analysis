// 產業頁的版面計算純函式（不碰 DOM）：瀏覽器掛在 window.Layout，node 以 module.exports 匯出供測試
(function (root) {
  const isNil = v => v === null || v === undefined;

  // ---- 總覽：上中下游三欄，每欄節點依序排列；太擠時分成幾個左右錯開的小欄，讓名稱與平均值不被鄰居蓋住 ----
  // 節點多到一欄放不下（如電腦週邊上游 25 個）時，整張圖等比例縮小（scale）再排
  // 每一層可用的水平範圍（佔畫面寬）；沒有中游的產業，上下游各分一半
  const BANDS = { Upstream: [0, 0.3], Midstream: [0.35, 0.65], Downstream: [0.7, 1] };
  const BANDS_NO_MID = { Upstream: [0, 0.48], Downstream: [0.52, 1] };
  const HEX_ABOVE = 50, HEX_BELOW = 90;          // 六角形（半徑 45）上緣與下方兩行文字的範圍
  const SUB_DX = 160;                            // 相鄰小欄的水平距離（縮放前）
  const MIN_SCALE = 0.55;

  function groupByTier(nodes) {
    const groups = new Map();
    nodes.forEach(n => {
      const key = n.group in BANDS ? n.group : "Midstream";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(n);
    });
    return groups;
  }

  // 一層 k 個節點在縮放 s 下需要幾個小欄：同一小欄上下相鄰需隔開一整個節點高
  function subColumns(k, s, height, top, bottom) {
    if (k <= 1) return 1;
    const nodeH = (HEX_ABOVE + HEX_BELOW) * s;
    const span = height - top - bottom - nodeH;
    return span > 0 ? Math.max(1, Math.ceil((k - 1) * nodeH / span)) : Infinity;
  }

  function overviewPlan(nodes, width, height, top = 100, bottom = 50) {
    const groups = groupByTier(nodes);
    const bands = groups.has("Midstream") ? BANDS : BANDS_NO_MID;
    const centers = {};
    groups.forEach((_, key) => { centers[key] = width * (bands[key][0] + bands[key][1]) / 2; });
    const fits = s => [...groups.entries()].every(([key, list]) => {
      const c = subColumns(list.length, s, height, top, bottom);
      return c === 1 || c * SUB_DX * s <= width * (bands[key][1] - bands[key][0]);
    });
    let scale = 1;
    while (scale > MIN_SCALE && !fits(scale)) scale = Math.round((scale - 0.05) * 100) / 100;

    const nodeH = (HEX_ABOVE + HEX_BELOW) * scale;
    const span = Math.max(height - top - bottom - nodeH, 0);   // 第一個與最後一個節點中心的可用距離
    const positions = new Map();
    groups.forEach((list, key) => {
      const k = list.length;
      const c = Math.min(subColumns(k, scale, height, top, bottom), k);
      const step = k > 1 ? Math.min(span / (k - 1), 200 * scale) : 0;
      const y0 = top + HEX_ABOVE * scale + (span - step * (k - 1)) / 2;   // 整欄垂直置中
      list.forEach((n, i) => {
        const dx = c > 1 ? ((i % c) - (c - 1) / 2) * SUB_DX * scale : 0;
        positions.set(n.id, [centers[key] + dx, y0 + step * i]);
      });
    });
    return { positions, scale, centers };
  }

  function overviewPositions(nodes, width, height, top = 100, bottom = 50) {
    return overviewPlan(nodes, width, height, top, bottom).positions;
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

  const api = { overviewPlan, overviewPositions, byChangeDesc, RING_MAX, ringPositions, gridPositions, focusPlan, FULL_RADIUS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Layout = api;
})(typeof window !== "undefined" ? window : globalThis);
