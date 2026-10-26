let width = window.innerWidth, height = window.innerHeight;
let nodes = [], links = [], allIndustryData = []; 
let currentFocusedIndustry = null; 

const svg = d3.select("#canvas");
const container = svg.append("g");
const linkLayer = container.append("g");
const nodeLayer = container.append("g");

// 💡 底部層級標籤
const labelLayer = svg.append("g").attr("class", "label-layer");
labelLayer.append("text").attr("x", "15%").attr("y", window.innerHeight - 20).attr("text-anchor", "middle").style("fill", "#64748b").style("font-size", "14px").style("font-weight", "bold").text("上游");
labelLayer.append("text").attr("x", "50%").attr("y", window.innerHeight - 20).attr("text-anchor", "middle").style("fill", "#64748b").style("font-size", "14px").style("font-weight", "bold").text("中游");
labelLayer.append("text").attr("x", "85%").attr("y", window.innerHeight - 20).attr("text-anchor", "middle").style("fill", "#64748b").style("font-size", "14px").style("font-weight", "bold").text("下游");

const simulation = d3.forceSimulation()
    .force("link", d3.forceLink().id(d => d.id).distance(160))
    .force("charge", d3.forceManyBody().strength(-400))
    .force("collision", d3.forceCollide().radius(d => getRadius(d) + 35));

function handleResize() {
    width = window.innerWidth; height = window.innerHeight;
    svg.attr("width", width).attr("height", height);
    simulation.force("x", d3.forceX(d => {
        if (currentFocusedIndustry) return width / 2;
        if (d.group === 'Upstream') return width * 0.15;
        if (d.group === 'Midstream') return width * 0.5;
        if (d.group === 'Downstream') return width * 0.85;
        return width * 0.5;
    }).strength(3.0));
    simulation.force("y", d3.forceY(height / 2).strength(0.8));
    // 💡 更新底部標籤位置
    labelLayer.selectAll("text").attr("y", height - 20).attr("x", (d, i) => {
        if (i === 0) return width * 0.15;
        if (i === 1) return width * 0.5;
        return width * 0.85;
    });
    simulation.alpha(0.3).restart();
}
window.addEventListener("resize", handleResize);

function getRadius(d) { return d.type === "industry" ? 45 : 25 + Math.min(Math.abs(d.change || 0) * 1.5, 15); }

function getHexPath(r) {
    const points = [];
    for (let i = 0; i < 6; i++) {
        const angle = (Math.PI / 3) * i - Math.PI / 2;
        points.push([r * Math.cos(angle), r * Math.sin(angle)]);
    }
    return d3.line()(points) + "Z";
}

// ---- 載入中／錯誤提示 ----
let pendingRequests = 0, lastError = null;
function renderBanner() {
    const el = document.getElementById("status-banner");
    if (lastError) { el.className = "error"; el.textContent = lastError; }
    else if (pendingRequests > 0) { el.className = "loading"; el.textContent = "載入中…"; }
    else { el.className = ""; el.textContent = ""; }
}
// 包住一個請求：進行中顯示「載入中…」，失敗（非 2xx 或網路錯誤）顯示紅色錯誤
function track(promise, what) {
    pendingRequests++; lastError = null; renderBanner();
    return promise.catch(err => {
        lastError = `${what}失敗：${err && err.message ? err.message : err}`;
        throw err;
    }).finally(() => { pendingRequests--; renderBanner(); });
}
// 請求成功但後續渲染丟出例外：記到 console 並顯示在錯誤橫幅（請求失敗已由 track 設定訊息）
function showRenderError(err) {
    console.error(err);
    if (!lastError) { lastError = `顯示資料失敗：${err && err.message ? err.message : err}`; renderBanner(); }
}
function fetchJSON(url) {
    return fetch(url).then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    });
}

track(d3.json(`/api/industry_nodes/${majorId}`), "載入產業節點").then(data => {
    allIndustryData = data; nodes = data.map(d => ({...d})); handleResize(); update();
}).catch(showRenderError);

// ---- 側邊欄趨勢區塊 ----
function renderReturns(returns) {
    [1, 5, 20].forEach(p => {
        const v = returns ? returns[String(p)] : null;
        const el = document.getElementById(`sb-ret-${p}`);
        el.innerText = Fmt.fmtSigned(Fmt.isNil(v) ? null : v, "%");
        el.className = `ret-val ${Fmt.upDownClass(v, 'badge')}`;
    });
}

// 區間（近 60 日報價範圍）內的除權息種類 → 除息／除權／除權息
function exBadgeText(quotes, exRights) {
    if (!quotes.length) return "";
    const first = quotes[0].date, last = quotes[quotes.length - 1].date;
    const kinds = new Set(exRights.filter(r => r.ex_date >= first && r.ex_date <= last).map(r => r.kind));
    if (!kinds.size) return "";
    if (kinds.has("除權息") || (kinds.has("除息") && kinds.has("除權"))) return "除權息";
    return kinds.has("除權") ? "除權" : "除息";
}

function appendText(parent, cls, text) {
    const d = document.createElement("div");
    if (cls) d.className = cls;
    d.textContent = text;
    parent.appendChild(d);
    return d;
}

function renderTrends(stockId, t) {
    renderReturns(t.returns);

    const badge = document.getElementById("sb-ex-badge");
    const badgeText = exBadgeText(t.quotes, t.ex_rights);
    badge.textContent = badgeText;
    badge.style.display = badgeText ? "inline-block" : "none";

    const markers = t.ex_rights.map(r => ({
        date: r.ex_date,
        label: `${r.ex_date} ${r.kind} 權息值 ${Fmt.isNil(r.total_value) ? "—" : r.total_value.toFixed(2)} 元`
    }));
    Charts.lineChart("#sb-chart-price", t.quotes.map(q => ({ date: q.date, close: q.close })), markers);
    Charts.barChart("#sb-chart-yoy", t.revenue.map(r => ({ label: r.month, value: r.yoy_pct })), { unit: "%" });
    Charts.barChart("#sb-chart-flow", t.flows.map(f => ({ label: f.date, value: f.trust_lots })), { unit: " 張" });
    Charts.barChart("#sb-chart-flow-foreign", t.flows.map(f => ({ label: f.date, value: f.foreign_lots })), { unit: " 張" });

    const sig = document.getElementById("sb-signals");
    sig.innerHTML = "";
    if (!t.signals.length) appendText(sig, "empty-note", "目前沒有觸發的訊號");
    t.signals.forEach(s => {
        const item = document.createElement("div");
        item.className = "signal-item";
        appendText(item, "", s.label);
        appendText(item, "signal-detail", s.detail);
        sig.appendChild(item);
    });

    const exl = document.getElementById("sb-ex-list");
    exl.innerHTML = "";
    if (!t.ex_rights.length) appendText(exl, "empty-note", "近一年沒有除權息");
    t.ex_rights.forEach(r => {
        const v = Fmt.isNil(r.total_value) ? "—" : r.total_value.toFixed(2);
        appendText(exl, "data-row", `${r.ex_date}　${r.kind}　權息值 ${v} 元`);
    });
}

function renderStar(stockId) {
    const star = document.getElementById("sb-star");
    const on = Fmt.loadWatchlist(localStorage).includes(stockId);
    star.textContent = on ? "★" : "☆";
    star.classList.toggle("on", on);
    star.setAttribute("aria-label", on ? "移出自選" : "加入自選");
    star.onclick = () => { Fmt.toggleWatch(localStorage, stockId); renderStar(stockId); };
}

// 💡 側邊欄異步獲取跨表資料（公司分析＋趨勢同時請求，任一失敗即走 track 錯誤提示）
let sidebarSeq = 0;
function openSidebar(companyId) {
    const stockId = companyId.replace(/^c_/, "");
    const seq = ++sidebarSeq;
    track(Promise.all([
        fetchJSON(`/api/company_analysis/${companyId}`),
        fetchJSON(`/api/company_trends/${stockId}`)
    ]), "載入公司資料")
        .then(([res, trends]) => {
            if (seq !== sidebarSeq || !res.success) return;
            
            document.getElementById("sb-company-name").innerText = res.basic.company_name;
            document.getElementById("sb-stock-id").innerText = `${res.basic.stock_id} • ${res.basic.market_type || '上市'}`;
            document.getElementById("sb-price").innerText = Fmt.fmtNum(res.basic.latest_price, " 元");
            
            const changeEl = document.getElementById("sb-change");
            const chg = res.basic.latest_change;
            changeEl.innerText = Fmt.fmtSigned(chg, "%");
            changeEl.className = `data-value ${Fmt.upDownClass(chg, 'badge')}`;

            if (res.growth) {
                document.getElementById("sb-month").innerText = res.growth.data_month;
                document.getElementById("sb-yoy").innerText = Fmt.fmtNum(res.growth.yoy_pct, "%");
                document.getElementById("sb-mom").innerText = Fmt.fmtNum(res.growth.mom_pct, "%");
                document.getElementById("sb-acc-yoy").innerText = Fmt.fmtNum(res.growth.acc_yoy_pct, "%");
            } else {
                ['sb-month', 'sb-yoy', 'sb-mom', 'sb-acc-yoy'].forEach(id => document.getElementById(id).innerText = '--');
            }

            if (res.smart_money) {
                document.getElementById("sb-trade-date").innerText = res.smart_money.trade_date;
                const t_jhang = Fmt.lots(res.smart_money.trust_net);
                const f_jhang = Fmt.lots(res.smart_money.foreign_net);
                
                const t_el = document.getElementById("sb-trust");
                t_el.innerText = Fmt.fmtSigned(t_jhang, " 張");
                t_el.className = `data-value ${Fmt.upDownClass(t_jhang, 'badge')}`;
                
                const f_el = document.getElementById("sb-foreign");
                f_el.innerText = Fmt.fmtSigned(f_jhang, " 張");
                f_el.className = `data-value ${Fmt.upDownClass(f_jhang, 'badge')}`;
            } else {
                ['sb-trade-date', 'sb-trust', 'sb-foreign'].forEach(id => document.getElementById(id).innerText = '--');
            }

            renderStar(stockId);
            // 先開面板再畫圖，圖表才量得到容器寬度
            document.getElementById("analysis-sidebar").classList.add("open");
            renderTrends(stockId, trends);
        }).catch(showRenderError);
}

function closeSidebar() { document.getElementById("analysis-sidebar").classList.remove("open"); }

function enterFocusMode(d, direction = 'center') {
    currentFocusedIndustry = d; closeSidebar();
    track(d3.json(`/api/node_companies/${d.id}`), "載入公司清單").then(cs => {
        let startX = width / 2, startY = height / 2;
        if(direction === 'up') startY = height + 200;
        if(direction === 'down') startY = -200;
        if(direction === 'left') startX = width + 200;
        if(direction === 'right') startX = -200;

        nodes = [
            { ...d, x: width / 2, y: height / 2, fx: width / 2, fy: height / 2 }, 
            ...cs.map(c => ({ ...c, x: startX, y: startY, parentId: d.id }))
        ];
        links = cs.map(c => ({ source: d.id, target: c.id }));
        d3.select("#btn-back").style("display", "block");
        updateNavButtons(); handleResize(); update();
    }).catch(err => { currentFocusedIndustry = null; showRenderError(err); });
}

function exitFocusMode() {
    if(nodes[0]) { nodes[0].fx = null; nodes[0].fy = null; }
    currentFocusedIndustry = null; links = []; closeSidebar();
    nodes = allIndustryData.map(d => ({...d}));
    d3.selectAll(".nav-btn").style("display", "none");
    handleResize(); update();
}

function updateNavButtons() {
    d3.selectAll(".nav-btn:not(#btn-back)").style("display", "none");
    if (!currentFocusedIndustry) return;
    const groups = ["Upstream", "Midstream", "Downstream"];
    const currG = groups.indexOf(currentFocusedIndustry.group);
    const sameG = allIndustryData.filter(n => n.group === currentFocusedIndustry.group);
    const currIdx = sameG.findIndex(n => n.id === currentFocusedIndustry.id);
    if (currG > 0) d3.select("#btn-left").style("display", "block").text(`◀ ${groups[currG-1]}`);
    if (currG < 2) d3.select("#btn-right").style("display", "block").text(`${groups[currG+1]} ▶`);
    if (currIdx > 0) d3.select("#btn-up").style("display", "block").text(`▲ ${sameG[currIdx-1].name}`);
    if (currIdx < sameG.length - 1) d3.select("#btn-down").style("display", "block").text(`▼ ${sameG[currIdx+1].name}`);
}

function navigate(dir) {
    const groups = ["Upstream", "Midstream", "Downstream"];
    const currG = groups.indexOf(currentFocusedIndustry.group);
    const sameG = allIndustryData.filter(n => n.group === currentFocusedIndustry.group);
    const currIdx = sameG.findIndex(n => n.id === currentFocusedIndustry.id);
    let target = null;
    if (dir === 'up') target = sameG[currIdx-1];
    if (dir === 'down') target = sameG[currIdx+1];
    if (dir === 'left') target = allIndustryData.find(n => n.group === groups[currG-1]);
    if (dir === 'right') target = allIndustryData.find(n => n.group === groups[currG+1]);
    if (target) enterFocusMode(target, dir);
}

function update() {
    const link = linkLayer.selectAll(".link").data(links, d => `${d.source.id || d.source}-${d.target.id || d.target}`);
    link.exit().remove();
    const linkEnter = link.enter().append("line").attr("class", "link");

    const node = nodeLayer.selectAll(".node-group").data(nodes, d => d.id);
    node.exit().remove();

    const nodeEnter = node.enter().append("g").attr("class", "node-group")
        .style("opacity", 0)
        .call(d3.drag().on("start", dragstarted).on("drag", dragged).on("end", dragended))
        .on("click", (e, d) => {
            if (d.type === "industry" && !currentFocusedIndustry) {
                enterFocusMode(d);
            } else if (d.type === "company") {
                e.stopPropagation(); 
                openSidebar(d.id);   
            }
        });

    nodeEnter.transition().duration(800).style("opacity", 1);

    nodeEnter.each(function(d) {
        const el = d3.select(this); const r = getRadius(d);
        if (d.type === "industry") {
            if (currentFocusedIndustry) { el.append("circle").attr("r", r).attr("class", "core-pulse"); }
            el.append("path").attr("d", getHexPath(r)).attr("class", "node industry-node");
            el.append("circle").attr("r", 5).attr("fill", "#fff").style("opacity", 0.8);
        } else {
            el.append("circle").attr("r", r).attr("class", d => {
                const c = d.change; return Fmt.isNil(c) || c === 0 ? "node stable-node" : (c > 0 ? "node up-node" : "node down-node");
            });
        }
    });

    const text = nodeEnter.append("text").attr("text-anchor", "middle").attr("dy", d => getRadius(d) + 25);
    text.append("tspan").attr("x", 0).attr("class", "label-name").text(d => d.name);
    text.append("tspan").attr("x", 0).attr("dy", "1.2em")
        .attr("class", d => `label-price ${Fmt.upDownClass(d.change, 'text')}`)
        .text(d => d.type === "company" ? `${Fmt.fmtNum(d.price)} (${Fmt.fmtSigned(d.change, "%")})` : "");

    simulation.nodes(nodes); simulation.force("link").links(links); simulation.alpha(1).restart();

    simulation.on("tick", () => {
        const currW = window.innerWidth; const currH = window.innerHeight; const cX = currW / 2, cY = currH / 2;
        linkEnter.merge(link).attr("x1", d => d.source.x).attr("y1", d => d.source.y).attr("x2", d => d.target.x).attr("y2", d => d.target.y);
        
        nodeEnter.merge(node).each(function(d) {
            const group = d3.select(this); const r = getRadius(d); const pad = 40; 
            d.x = Math.max(r + pad, Math.min(currW - r - pad, d.x)); d.y = Math.max(r + pad, Math.min(currH - r - pad, d.y));
            
            // 💡 取消邊緣縮小效果
            const scale = 1;
            const opacity = 1;

            // 💡 總覽與聚焦模式下的發光分流判定
            if (currentFocusedIndustry) {
                const dx = d.x - cX, dy = d.y - cY; const dist = Math.sqrt(dx * dx + dy * dy); const maxD = Math.min(currW, currH) / 1.5;
                const brightness = Math.max(0.4, 1.3 - (dist / maxD) * 0.9); const glowIntensity = Math.max(0, 25 - (dist / maxD) * 30);
                group.selectAll("path, circle").attr("transform", `scale(${scale})`).style("opacity", Math.min(1, brightness + 0.2))
                     .style("filter", d.type === "industry" ? `drop-shadow(0 0 ${glowIntensity}px #0ea5e9) brightness(${brightness})` : "none");
            } else {
                group.selectAll("path, circle").attr("transform", `scale(${scale})`).style("opacity", opacity).style("filter", "none");
            }
            group.select("text").style("opacity", opacity).attr("transform", `scale(${scale})`);
            group.attr("transform", `translate(${d.x},${d.y})`);
        });
    });
}

function dragstarted(e, d) { if (!e.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }
function dragged(e, d) { d.fx = e.x; d.fy = e.y; }
function dragended(e, d) { if (!e.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }
svg.call(d3.zoom().on("zoom", (e) => container.attr("transform", e.transform)));
