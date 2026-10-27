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

  const api = { MARKET_NOTE, SURVIVOR_NOTE, RANGES, MAX_NODES, seriesKeys, rangeStart, firstDateNote, visibleKeys, lineChart };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else root.Trend = api;
})(typeof window !== "undefined" ? window : globalThis);
