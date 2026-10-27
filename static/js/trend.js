// 產業頁走勢面板的純函式與多線圖：瀏覽器掛在 window.Trend，node 以 module.exports 匯出供測試
(function (root) {
  const RANGES = { "1M": 21, "3M": 63, "6M": 126, "1Y": 250 };   // 交易日數（同 industry_trends.RANGES）
  const TIERS = ["Upstream", "Midstream", "Downstream"];
  const MAX_NODES = 5;
  // 固定註記：與 industry_trends.MARKET_NOTE / SURVIVOR_NOTE 逐字相同（tests 會比對）；不依賴 API 回應
  const MARKET_NOTE = "此為自行計算的等權大盤（上市＋上櫃，排除 ETF，已還原除權息），與證交所公布的加權指數不同";
  const SURVIVOR_NOTE = "成分股以目前名單往回計算，不含已下市公司";

  // 要向 /api/index_series 要的 key：大盤＋產業（或三層）＋最多 5 個節點
  function seriesKeys(majorId, mode, nodeIds) {
    const base = mode === "tiers"
      ? ["market:TW", ...TIERS.map(t => `tier:${majorId}:${t}`)]
      : ["market:TW", `major:${majorId}`];
    return base.concat((nodeIds || []).slice(0, MAX_NODES).map(id => `node:${id}`));
  }

  // 區間起點估算：今天往前 交易日數 × 7/5 個日曆日（只用來決定是否顯示提示）
  function rangeStart(range, today) {
    const d = new Date(today || Date.now());
    d.setUTCDate(d.getUTCDate() - Math.round(RANGES[range] * 7 / 5));
    return d.toISOString().slice(0, 10);
  }

  // 任一序列最早日期晚於區間起點 → 取最晚的那個提示；否則 null
  function firstDateNote(firstDates, rangeStartDate) {
    const late = Object.values(firstDates || {}).filter(d => d && d > rangeStartDate).sort();
    return late.length ? `指數資料從 ${late[late.length - 1]} 起` : null;
  }

  // 只留有資料的序列（產業沒有的層不顯示）
  function visibleKeys(keys, series) {
    return keys.filter(k => (series[k] || []).length > 0);
  }

  const COLORS = ["#5ac8fa", "#ff9f43", "#a78bfa", "#3ddc97", "#ff6b81", "#fbbf24", "#94a3b8"];

  // 多線圖：series = [{key,label,points:[{date,value}],dashed?}]；滑鼠移上顯示當日各線值
  function lineChart(container, series, opts) {
    opts = opts || {};
    const el = typeof container === "string" ? document.querySelector(container) : container;
    el.innerHTML = "";
    const lines = (series || []).filter(s => s.points && s.points.length);
    if (!lines.length) return;
    const w = Math.max(el.clientWidth || 340, 200), h = opts.height || 190;
    const M = { top: 8, right: 8, bottom: 18, left: 38 };
    const dates = Array.from(new Set(lines.flatMap(s => s.points.map(p => p.date)))).sort();
    const x = d3.scalePoint().domain(dates).range([M.left, w - M.right]);
    const vals = lines.flatMap(s => s.points.map(p => p.value));
    const [lo, hi] = d3.extent(vals);
    const pad = (hi - lo) * 0.1 || 1;
    const y = d3.scaleLinear().domain([lo - pad, hi + pad]).range([h - M.bottom, M.top]);
    const color = (s, i) => s.color || COLORS[i % COLORS.length];

    const wrap = d3.select(el).style("position", "relative");
    const svg = wrap.append("svg").attr("width", w).attr("height", h).style("display", "block");
    const style = g => {
      g.selectAll("text").style("fill", "var(--text-2)").style("font-size", "10px");
      g.selectAll("path, line").style("stroke", "var(--text-3)");
    };
    style(svg.append("g").attr("transform", `translate(${M.left},0)`).call(d3.axisLeft(y).ticks(4).tickSize(-4)));
    const ax = svg.append("g").attr("transform", `translate(0,${h - M.bottom})`)
      .call(d3.axisBottom(x).tickValues([dates[0], dates[dates.length - 1]]).tickSize(3));
    style(ax);
    const t = ax.selectAll(".tick text").nodes();
    if (t.length > 1) { t[0].setAttribute("text-anchor", "start"); t[t.length - 1].setAttribute("text-anchor", "end"); }
    // 基準線 100
    svg.append("line").attr("x1", M.left).attr("x2", w - M.right).attr("y1", y(100)).attr("y2", y(100))
      .style("stroke", "var(--text-3)").style("stroke-dasharray", "2 3").style("opacity", 0.5);

    lines.forEach((s, i) => {
      svg.append("path").datum(s.points)
        .attr("fill", "none").attr("stroke", color(s, i)).attr("stroke-width", s.dashed ? 1.5 : 2)
        .attr("stroke-dasharray", s.dashed ? "5 4" : null)
        .attr("d", d3.line().x(p => x(p.date)).y(p => y(p.value)));
    });

    // 互動：游標最近的日期 → 垂直線與提示框
    const cursor = svg.append("line").attr("y1", M.top).attr("y2", h - M.bottom)
      .style("stroke", "var(--text-2)").style("opacity", 0);
    const tip = wrap.append("div").style("position", "absolute").style("pointer-events", "none")
      .style("display", "none").style("padding", "6px 9px").style("font-size", "11px").style("line-height", "1.5")
      .style("border-radius", "10px").style("background", "rgba(7,10,18,0.88)")
      .style("border", "1px solid var(--glass-edge)").style("white-space", "nowrap").style("z-index", 5);
    const maps = lines.map(s => new Map(s.points.map(p => [p.date, p.value])));
    svg.append("rect").attr("x", M.left).attr("y", 0).attr("width", w - M.left - M.right).attr("height", h)
      .attr("fill", "transparent")
      .on("mousemove", ev => {
        const mx = d3.pointer(ev)[0];
        const step = dates.length > 1 ? (w - M.left - M.right) / (dates.length - 1) : 1;
        const d = dates[Math.max(0, Math.min(dates.length - 1, Math.round((mx - M.left) / step)))];
        cursor.attr("x1", x(d)).attr("x2", x(d)).style("opacity", 0.5);
        tip.html("").style("display", "block");
        tip.append("div").text(d).style("color", "var(--text-2)");
        lines.forEach((s, i) => {
          const v = maps[i].get(d);
          const row = tip.append("div");
          row.append("span").text("● ").style("color", color(s, i));
          row.append("span").text(`${s.label} ${v == null ? "—" : v.toFixed(1)}`);
        });
        const left = x(d) > w / 2 ? x(d) - tip.node().offsetWidth - 10 : x(d) + 10;
        tip.style("left", `${left}px`).style("top", "6px");
      })
      .on("mouseleave", () => { cursor.style("opacity", 0); tip.style("display", "none"); });

    // 圖例：大盤項目附 title=MARKET_NOTE
    const legend = wrap.append("div").style("display", "flex").style("flex-wrap", "wrap")
      .style("gap", "4px 12px").style("margin-top", "6px").style("font-size", "11px");
    lines.forEach((s, i) => {
      const item = legend.append("span").style("color", "var(--text-2)");
      if (s.dashed && (opts.marketNote || MARKET_NOTE)) item.attr("title", (opts.marketNote || MARKET_NOTE)).style("cursor", "help");
      item.append("span").text(s.dashed ? "┅ " : "━ ").style("color", color(s, i));
      item.append("span").text(s.label);
    });
  }

  // 節點內相對強弱：diff = 漲跌 − 節點平均（只算非 null）；前 m 名 lead、後 m 名 lag，m = min(3, floor(k/2))
  function relativeRanks(companies) {
    const vals = (companies || []).filter(c => c.change != null);
    const out = new Map((companies || []).map(c => [c.id, { diff: null, tag: null }]));
    if (!vals.length) return out;
    const avg = vals.reduce((a, c) => a + c.change, 0) / vals.length;
    const m = Math.min(3, Math.floor(vals.length / 2));
    const sorted = vals.slice().sort((a, b) => b.change - a.change);
    sorted.forEach((c, i) => {
      const diff = Math.round((c.change - avg) * 100) / 100 || 0;
      const tag = i < m ? "lead" : (i >= sorted.length - m ? "lag" : null);
      out.set(c.id, { diff, tag });
    });
    return out;
  }

  // 張數顯示：null →「—」，其餘帶正負號與千分位
  function formatLots(v) {
    if (v == null) return "—";
    const sign = v > 0 ? "+" : (v < 0 ? "-" : "");
    return `${sign}${Math.abs(Math.round(v)).toLocaleString("en-US")} 張`;
  }

  // 排行表排序：null 一律排最後（不論升降冪）；回傳新陣列
  function sortRows(rows, key, desc) {
    const dir = desc ? -1 : 1;
    return (rows || []).slice().sort((a, b) => {
      const x = a[key], y = b[key];
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return x < y ? -dir : (x > y ? dir : 0);
    });
  }

  const QUAD_LABELS = [["領先", 1, 1], ["轉弱", 1, 0], ["落後", 0, 0], ["轉強", 0, 1]];   // [名稱, 右側?, 上方?]

  // 輪動圖（RRG）：points = [{major_id,name,x,y,quadrant,trail:[{date,x,y}]}]；中心 (100,100)，軌跡由舊到新
  function rotationChart(container, points, notes) {
    const el = typeof container === "string" ? document.querySelector(container) : container;
    el.innerHTML = "";
    const note = (notes && notes.market) || MARKET_NOTE;
    if (!points || !points.length) {
      el.textContent = "指數資料不足 60 個交易日，暫無輪動圖";
      return;
    }
    const w = Math.max(el.clientWidth || 600, 280), h = Math.min(Math.max(w * 0.7, 320), 520);
    const M = { top: 14, right: 16, bottom: 40, left: 46 };
    const all = points.flatMap(p => [{ x: p.x, y: p.y }].concat(p.trail || []));
    const span = (get) => Math.max(1, ...all.map(a => Math.abs(get(a) - 100))) * 1.15;
    const dx = span(a => a.x), dy = span(a => a.y);
    const x = d3.scaleLinear().domain([100 - dx, 100 + dx]).range([M.left, w - M.right]);
    const y = d3.scaleLinear().domain([100 - dy, 100 + dy]).range([h - M.bottom, M.top]);
    const svg = d3.select(el).append("svg").attr("width", w).attr("height", h).style("display", "block");
    const axisStyle = g => {
      g.selectAll("text").style("fill", "var(--text-2)").style("font-size", "10px");
      g.selectAll("path, line").style("stroke", "var(--text-3)");
    };
    axisStyle(svg.append("g").attr("transform", `translate(0,${h - M.bottom})`).call(d3.axisBottom(x).ticks(5).tickSize(3)));
    axisStyle(svg.append("g").attr("transform", `translate(${M.left},0)`).call(d3.axisLeft(y).ticks(5).tickSize(3)));
    // 十字中線
    svg.append("line").attr("x1", x(100)).attr("x2", x(100)).attr("y1", M.top).attr("y2", h - M.bottom)
      .style("stroke", "var(--text-3)").style("stroke-dasharray", "3 3");
    svg.append("line").attr("y1", y(100)).attr("y2", y(100)).attr("x1", M.left).attr("x2", w - M.right)
      .style("stroke", "var(--text-3)").style("stroke-dasharray", "3 3");
    // 四象限標字
    QUAD_LABELS.forEach(([name, right, top]) => {
      svg.append("text").text(name)
        .attr("x", right ? w - M.right - 6 : M.left + 6).attr("y", top ? M.top + 14 : h - M.bottom - 8)
        .attr("text-anchor", right ? "end" : "start")
        .style("fill", "var(--text-3)").style("font-size", "13px").style("font-weight", "600");
    });
    // 軸標題（附 MARKET_NOTE）
    const xt = svg.append("text").text("相對大盤強弱").attr("x", (M.left + w - M.right) / 2).attr("y", h - 8)
      .attr("text-anchor", "middle").style("fill", "var(--text-2)").style("font-size", "12px").style("cursor", "help");
    xt.append("title").text(note);
    const yt = svg.append("text").text("強弱變化速度").attr("transform", `translate(12,${(M.top + h - M.bottom) / 2}) rotate(-90)`)
      .attr("text-anchor", "middle").style("fill", "var(--text-2)").style("font-size", "12px").style("cursor", "help");
    yt.append("title").text(note);

    points.forEach((p, i) => {
      const c = COLORS[i % COLORS.length];
      const g = svg.append("g");
      const trail = (p.trail || []).concat([{ date: null, x: p.x, y: p.y }]);
      g.append("path").datum(trail).attr("fill", "none").attr("stroke", c).attr("stroke-width", 1.5).attr("opacity", 0.55)
        .attr("d", d3.line().x(t => x(t.x)).y(t => y(t.y)));
      g.append("circle").attr("cx", x(p.x)).attr("cy", y(p.y)).attr("r", 5).attr("fill", c)
        .append("title").text(`${p.name}（${p.quadrant}）x=${p.x} y=${p.y}`);
      g.append("text").text(p.name).attr("x", x(p.x) + 8).attr("y", y(p.y) + 4)
        .style("fill", "var(--text-1)").style("font-size", "11px");
    });
    const small = document.createElement("p");
    small.className = "chart-note";
    small.textContent = note;
    el.appendChild(small);
  }

  // 自選股提醒：漲跌幅達門檻、每個訊號、今日除權息；latest_change 為 null 不觸發漲跌
  const THRESHOLD_KEY = "stockchain.alertThreshold";
  function alertsFor(c, threshold) {
    const out = [];
    const ch = c.latest_change;
    if (ch != null && Math.abs(ch) >= threshold) {
      out.push(ch > 0 ? `大漲 +${ch.toFixed(2)}%` : `大跌 -${Math.abs(ch).toFixed(2)}%`);
    }
    (c.signals || []).forEach(s => out.push(s.label));
    if (c.ex_today) out.push("今日除權息");
    return out;
  }

  const api = { alertsFor, THRESHOLD_KEY, sortRows, rotationChart, MARKET_NOTE, SURVIVOR_NOTE, RANGES, MAX_NODES, seriesKeys, rangeStart, firstDateNote, visibleKeys, lineChart, relativeRanks, formatLots };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.Trend = api;
})(typeof window !== "undefined" ? window : globalThis);
