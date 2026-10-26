// 側邊欄小圖表（只用 D3）：折線（收盤＋除權息標記）與長條（正紅負綠）
(function (root) {
  const H = 120;
  const M = { top: 8, right: 6, bottom: 18, left: 38 };
  const isNil = v => v === null || v === undefined;

  function prepare(container) {
    const el = typeof container === "string" ? document.querySelector(container) : container;
    el.innerHTML = "";
    const w = Math.max(el.clientWidth || 280, 120);
    const svg = d3.select(el).append("svg").attr("width", w).attr("height", H).style("display", "block");
    return { el, svg, w };
  }

  function emptyNote(svg, w) {
    svg.append("text").attr("x", w / 2).attr("y", H / 2).attr("text-anchor", "middle")
      .style("fill", "var(--text-2)").style("font-size", "12px").text("—");
  }

  // 底部軸：第一個標籤靠左對齊、最後一個靠右對齊，避免被裁切
  function anchorEnds(g) {
    const t = g.selectAll(".tick text").nodes();
    if (t.length > 1) { t[0].setAttribute("text-anchor", "start"); t[t.length - 1].setAttribute("text-anchor", "end"); }
  }

  function styleAxis(g) {
    g.selectAll("text").style("fill", "var(--text-2)").style("font-size", "10px");
    g.selectAll("path, line").style("stroke", "var(--text-3)");
  }

  function lineChart(container, points, markers) {
    const { svg, w } = prepare(container);
    const valid = (points || []).filter(p => !isNil(p.close));
    if (!valid.length) { emptyNote(svg, w); return; }
    const x = d3.scalePoint().domain(points.map(p => p.date)).range([M.left, w - M.right]);
    const [lo, hi] = d3.extent(valid, p => p.close);
    const pad = (hi - lo) * 0.1 || Math.abs(hi) * 0.01 || 1;
    const y = d3.scaleLinear().domain([lo - pad, hi + pad]).range([H - M.bottom, M.top]);
    const tickDates = [points[0].date, points[points.length - 1].date];
    styleAxis(svg.append("g").attr("transform", `translate(0,${H - M.bottom})`)
      .call(d3.axisBottom(x).tickValues(tickDates).tickFormat(d => d.slice(5)).tickSizeOuter(0)).call(anchorEnds));
    styleAxis(svg.append("g").attr("transform", `translate(${M.left},0)`)
      .call(d3.axisLeft(y).ticks(3).tickSizeOuter(0)));
    const line = d3.line().defined(p => !isNil(p.close)).x(p => x(p.date)).y(p => y(p.close));
    svg.append("path").datum(points).attr("d", line)
      .style("fill", "none").style("stroke", "var(--text-1)").style("stroke-width", 1.5);
    const byDate = new Map(points.map(p => [p.date, p]));
    (markers || []).forEach(m => {
      const p = byDate.get(m.date);
      if (!p || isNil(p.close)) return;
      svg.append("circle").attr("cx", x(p.date)).attr("cy", y(p.close)).attr("r", 4)
        .style("fill", "var(--ex)").style("stroke", "#fff").style("stroke-width", 1)
        .append("title").text(m.label);
    });
  }

  function barChart(container, bars, opts) {
    const { svg, w } = prepare(container);
    const unit = (opts && opts.unit) || "";
    const vals = (bars || []).filter(b => !isNil(b.value));
    if (!vals.length) { emptyNote(svg, w); return; }
    const x = d3.scaleBand().domain(bars.map(b => b.label)).range([M.left, w - M.right]).padding(0.2);
    const ext = d3.extent(vals, b => b.value);
    const y = d3.scaleLinear().domain([Math.min(0, ext[0]), Math.max(0, ext[1])]).nice().range([H - M.bottom, M.top]);
    const labels = bars.map(b => b.label);
    styleAxis(svg.append("g").attr("transform", `translate(0,${H - M.bottom})`)
      .call(d3.axisBottom(x).tickValues([labels[0], labels[labels.length - 1]]).tickSize(0)).call(anchorEnds));
    styleAxis(svg.append("g").attr("transform", `translate(${M.left},0)`)
      .call(d3.axisLeft(y).ticks(3).tickSizeOuter(0)));
    svg.append("line").attr("x1", M.left).attr("x2", w - M.right).attr("y1", y(0)).attr("y2", y(0))
      .style("stroke", "var(--text-3)");
    svg.selectAll("rect.bar").data(vals).enter().append("rect").attr("class", "bar")
      .attr("x", b => x(b.label)).attr("width", x.bandwidth())
      .attr("y", b => Math.min(y(0), y(b.value))).attr("height", b => Math.abs(y(b.value) - y(0)))
      .style("fill", b => b.value >= 0 ? "var(--up)" : "var(--down)")
      .append("title").text(b => `${b.label}：${b.value}${unit}`);
  }

  const api = { lineChart, barChart };
  root.Charts = api;
})(window);
