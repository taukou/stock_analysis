let width = window.innerWidth, height = window.innerHeight;
let nodes = [], links = [], allIndustryData = []; 
let currentFocusedIndustry = null; 

const svg = d3.select("#canvas");
const container = svg.append("g");
const supplyLayer = container.append("g");   // 供應關係線（只在總覽畫，在節點下層）
const linkLayer = container.append("g");
const nodeLayer = container.append("g");

// 底部層級標籤：位置跟著總覽各層的中心（沒有的層隱藏）
const TIER_LABELS = [["Upstream", "上游", 0.15], ["Midstream", "中游", 0.5], ["Downstream", "下游", 0.85]];
const labelLayer = svg.append("g").attr("class", "label-layer");
labelLayer.selectAll("text").data(TIER_LABELS).enter().append("text")
    .attr("x", d => width * d[2]).attr("y", height - 20).attr("text-anchor", "middle")
    .style("fill", "#64748b").style("font-size", "14px").style("font-weight", "bold").text(d => d[1]);
function placeTierLabels(centers) {
    labelLayer.selectAll("text").attr("y", height - 20)
        .attr("x", d => centers ? centers[d[0]] ?? 0 : width * d[2])
        .style("display", d => !centers || d[0] in centers ? null : "none");
}

// 供應關係線箭頭
svg.append("defs").append("marker").attr("id", "supply-arrow").attr("viewBox", "0 0 10 10")
    .attr("refX", 9).attr("refY", 5).attr("markerWidth", 7).attr("markerHeight", 7).attr("orient", "auto")
    .append("path").attr("d", "M0,0 L10,5 L0,10 z").attr("fill", "#94a3b8");

// 版面由 Layout 決定（總覽：三欄固定位置；聚焦：依漲跌排序的圓環或排行網格），
// 模擬只負責把節點平滑地移到目標位置 (tx, ty)：不用互斥力、連線拉力與碰撞
// （格子大小已保證球與標籤不重疊；碰撞反而會讓換位的球互相卡住）
const simulation = d3.forceSimulation()
    .force("link", d3.forceLink().id(d => d.id).strength(0))
    .force("x", d3.forceX(d => d.tx ?? width / 2).strength(0.3))
    .force("y", d3.forceY(d => d.ty ?? height / 2).strength(0.3));

// 聚焦模式的版面狀態：公司球縮放比例與標籤樣式（full／compact／none）
let focusLayout = { scale: 1, label: "full" };

// 聚焦版面可用區域：避開上方切換鈕／▲、下方 ▼、左右導覽鈕，側邊欄開啟時再扣掉面板
function focusArea() {
    const sidebar = document.body.classList.contains("sidebar-open");
    const left = 170, right = width - (sidebar ? 396 + 150 : 170), top = 120, bottom = height - 80;
    return { x: left, y: top, w: Math.max(240, right - left), h: Math.max(240, bottom - top) };
}

// 依目前模式計算每個節點的目標位置；聚焦模式依目前區間漲跌重新排序
function layoutNodes() {
    if (!currentFocusedIndustry) {
        focusLayout = { scale: 1, label: "full" };
        // 下緣多留 30px，最下面的節點名稱才不會被左下角「資料更新至」蓋住
        const plan = Layout.overviewPlan(nodes, width, height, 100, 80);
        overviewScale = plan.scale;
        placeTierLabels(plan.centers);
        nodes.forEach(n => {
            const p = plan.positions.get(n.id);
            if (!p) return;
            [n.tx, n.ty] = p;
            if (!n.dragged) { n.fx = n.tx; n.fy = n.ty; }
        });
        return;
    }
    placeTierLabels(null);
    const [center, ...companies] = nodes;
    const area = focusArea();
    center.tx = center.fx = area.x + area.w / 2;
    center.ty = center.fy = area.y + area.h / 2;
    const plan = Layout.focusPlan(companies, area);
    focusLayout = { scale: plan.scale, label: plan.label };
    plan.sorted.forEach((c, i) => { [c.tx, c.ty] = plan.positions[i]; });
}

// 版面或球大小改變後（切區間、側邊欄開關、視窗大小）：重算目標位置、重畫球與標籤並讓模擬動起來
function relayout(alpha = 0.5) {
    layoutNodes();
    simulation.force("x").x(d => d.tx ?? width / 2);   // forceX 會快取目標，需重新指定
    simulation.force("y").y(d => d.ty ?? height / 2);
    repaintAll();
    simulation.alpha(alpha).restart();
}

function handleResize() {
    width = window.innerWidth; height = window.innerHeight;
    svg.attr("width", width).attr("height", height);
    relayout(0.3);   // 底部層級標籤在 layoutNodes 裡跟著重排
}
window.addEventListener("resize", handleResize);

// 總覽節點的縮放（節點很多的產業會整張圖縮小）；聚焦模式一律 1
let overviewScale = 1;
function nodeScale(d) { return d.type === "industry" && !currentFocusedIndustry ? overviewScale : 1; }

// 球大小依漲跌幅（25～40），聚焦公司很多時依版面等比例縮小
function getRadius(d) {
    if (d.type === "industry") return 45;
    return (25 + Math.min(Math.abs(d.change || 0) * 1.5, 15)) * focusLayout.scale;
}

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
    loadHeat();
    return openDeepLink();
}).catch(showRenderError);
track(fetchJSON(`/api/industry_links/${majorId}`), "載入供應關係").then(ls => {
    supplyLinks = ls; update();
}).catch(showRenderError);

// ---- 側邊欄趨勢區塊 ----
let currentPeriod = 1;   // 目前選的區間（交易日數），由 #period-switch 切換
let heatMap = {};        // node_id -> {avg_change, count}（目前區間）
let supplyLinks = [];    // [{from, to}] 節點供應關係

// 滑過節點或箭頭：只亮相關的供應線，圖例改寫成文字說明供應方向
const SUPPLY_LEGEND_DEFAULT = "箭頭方向 ＝ 供應給（上游 → 下游）";
function highlightSupply(nodeId, toId) {
    const legend = document.getElementById("supply-legend");
    const groups = supplyLayer.selectAll("g.supply");
    if (!nodeId || currentFocusedIndustry) {
        groups.classed("hot", false).classed("dim", false);
        if (legend) legend.textContent = SUPPLY_LEGEND_DEFAULT;
        return;
    }
    const related = toId ? (l => l.from === nodeId && l.to === toId)
                         : (l => l.from === nodeId || l.to === nodeId);
    groups.classed("hot", related).classed("dim", l => !related(l));
    if (!legend) return;
    const name = id => (allIndustryData.find(n => n.id === id) || { name: id }).name;
    if (toId) { legend.textContent = `${name(nodeId)} 供應給 ${name(toId)}`; return; }
    const out = supplyLinks.filter(l => l.from === nodeId).map(l => name(l.to));
    const inn = supplyLinks.filter(l => l.to === nodeId).map(l => name(l.from));
    legend.textContent = `${name(nodeId)}｜供應給：${out.join("、") || "—"}｜來自：${inn.join("、") || "—"}`;
}
let lastTrends = null;   // 目前開啟側邊欄的趨勢資料，切區間時重算除權息標籤用
function renderReturns(returns) {
    [1, 5, 20].forEach(p => {
        const v = returns ? returns[String(p)] : null;
        const el = document.getElementById(`sb-ret-${p}`);
        el.innerText = Fmt.fmtSigned(Fmt.isNil(v) ? null : v, "%");
        el.className = `ret-val ${Fmt.upDownClass(v, 'badge')}`;
    });
}

function appendText(parent, cls, text) {
    const d = document.createElement("div");
    if (cls) d.className = cls;
    d.textContent = text;
    parent.appendChild(d);
    return d;
}

function renderExBadge() {
    const badge = document.getElementById("sb-ex-badge");
    const t = lastTrends;
    const badgeText = t ? (Fmt.exKindInWindow(t.ex_rights, t.quotes.map(q => q.date), currentPeriod) || "") : "";
    badge.textContent = badgeText;
    badge.style.display = badgeText ? "inline-block" : "none";
}

function renderTrends(stockId, t) {
    renderReturns(t.returns);

    lastTrends = t;
    renderExBadge();

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
    const on = Fmt.loadWatchlist(Fmt.safeStorage()).includes(stockId);
    star.textContent = on ? "★" : "☆";
    star.classList.toggle("on", on);
    star.setAttribute("aria-label", on ? "移出自選" : "加入自選");
    star.onclick = () => {
        if (Fmt.toggleWatch(Fmt.safeStorage(), stockId) === null) {
            lastError = "自選股無法儲存：瀏覽器封鎖了本機儲存空間"; renderBanner();
        }
        renderStar(stockId);
    };
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
            const wasOpen = document.body.classList.contains("sidebar-open");
            document.body.classList.add("sidebar-open");
            if (!wasOpen && currentFocusedIndustry) relayout(0.4);   // 公司排到面板左邊
            renderTrends(stockId, trends);
        }).catch(showRenderError);
}

// relayoutFocus=false：呼叫端自己會重排（切換節點、回總覽）
function closeSidebar(relayoutFocus = true) {
    sidebarSeq++;   // 尚未回來的 openSidebar 回應作廢，避免面板在使用者離開後又打開
    lastTrends = null;
    document.getElementById("analysis-sidebar").classList.remove("open");
    const wasOpen = document.body.classList.contains("sidebar-open");
    document.body.classList.remove("sidebar-open");
    if (wasOpen && relayoutFocus && currentFocusedIndustry) relayout(0.4);
}

// 聚焦請求序號：較晚發出的聚焦才算數，舊回應（例如連按兩次 ▼）直接丟掉
let focusSeq = 0;
// 回傳 promise：true = 這次聚焦已畫上畫面；false = 被較新的操作取代或失敗
function enterFocusMode(d, direction = 'center') {
    const seq = ++focusSeq, period = currentPeriod;
    currentFocusedIndustry = d; closeSidebar(false);
    document.body.classList.add("focus-mode"); highlightSupply(null);
    return track(fetchJSON(`/api/node_companies/${encodeURIComponent(d.id)}?period=${period}`), "載入公司清單").then(cs => {
        if (seq !== focusSeq) return false;
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
        // 等待期間切換了區間：這批是舊區間的數字，改抓目前區間
        if (period !== currentPeriod) refreshFocusPeriod();
        return true;
    }).catch(err => {
        if (seq === focusSeq) { currentFocusedIndustry = null; document.body.classList.remove("focus-mode"); }
        showRenderError(err);
        return false;
    });
}

// 搜尋／自選股深連結：?node=N201&company=2330 → 進入該節點，公司清單載完後再開側邊欄
function openDeepLink() {
    const q = new URLSearchParams(location.search);
    const nodeId = q.get("node"), company = q.get("company");
    const d = nodeId && allIndustryData.find(n => n.id === nodeId);
    if (!d) return;
    const stockId = company && /^[0-9A-Z]{4,6}$/.test(company) ? company : null;
    return enterFocusMode(d).then(ok => {
        if (ok && stockId && currentFocusedIndustry === d) openSidebar("c_" + stockId);
    });
}

function exitFocusMode() {
    focusSeq++;   // 進行中的聚焦請求作廢
    currentFocusedIndustry = null; links = []; closeSidebar(false);
    document.body.classList.remove("focus-mode");
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

// ---- 依目前區間與資料更新單一節點的填色與文字（不動位置） ----
const EX_SHORT = {"除息": "息", "除權": "權", "除權息": "權息"};
function paintNode(d, g) {
    if (d.type === "industry") {
        const h = heatMap[d.id];
        const avg = h ? h.avg_change : null;
        g.select("path.industry-node").style("fill", Fmt.heatColor(avg, currentPeriod));
        g.select("tspan.label-price").attr("class", `label-price ${Fmt.upDownClass(avg, 'text')}`)
            .text(Fmt.isNil(avg) ? "平均 —" : `平均 ${Fmt.fmtSigned(avg, "%")}（${h.count} 家）`);
        return;
    }
    const c = d.change, r = getRadius(d);
    g.select("circle.node").attr("r", r)
        .attr("class", Fmt.isNil(c) || c === 0 ? "node stable-node" : (c > 0 ? "node up-node" : "node down-node"));
    g.select("circle.node title").text(`${d.name} ${Fmt.fmtNum(d.price)} (${Fmt.fmtSigned(c, "%")})`);
    // 標籤依格子大小：完整（名稱＋股價（漲跌））／精簡（名稱＋漲跌，字小一號）／不顯示
    const mode = focusLayout.label, compact = mode === "compact";
    const label = g.select("text.label").style("display", mode === "none" ? "none" : null)
        .attr("dy", r + (compact ? 12 : 16));
    label.select("tspan.label-name").style("font-size", compact ? "11px" : null);
    label.select("tspan.label-price").attr("class", `label-price ${Fmt.upDownClass(c, 'text')}`)
        .attr("dy", compact ? "1.15em" : "1.2em").style("font-size", compact ? "10px" : null)
        .text(compact ? Fmt.fmtSigned(c, "%") : `${Fmt.fmtNum(d.price)} (${Fmt.fmtSigned(c, "%")})`);
    g.select("text.ex-tag").attr("x", r * 0.7).attr("y", -r * 0.7)
        .text(d.ex ? (EX_SHORT[d.ex] || d.ex) : "").style("display", d.ex ? null : "none");
    const sigs = d.signals || [];
    const star = g.select("text.sig-star").attr("x", -r * 0.7).attr("y", -r * 0.7 + 4)
        .style("display", sigs.length ? null : "none");
    star.select("title").text(sigs.map(s => s.label).join("、"));
}
function repaintAll() { nodeLayer.selectAll(".node-group").each(function (d) { paintNode(d, d3.select(this)); }); }

function loadHeat() {
    const period = currentPeriod;
    return track(fetchJSON(`/api/industry_heat/${majorId}?period=${period}`), "載入產業熱度").then(rows => {
        if (period !== currentPeriod) return;
        heatMap = {};
        rows.forEach(r => { heatMap[r.node_id] = r; });
        repaintAll();
    }).catch(showRenderError);
}

function setPeriod(p) {
    if (p === currentPeriod) return;
    currentPeriod = p;
    document.querySelectorAll("#period-switch button").forEach(b => {
        const on = Number(b.dataset.period) === p;
        b.classList.toggle("active", on);
        b.setAttribute("aria-pressed", on);
    });
    renderExBadge();
    loadHeat();
    if (currentFocusedIndustry) refreshFocusPeriod();
}

// 聚焦中：抓目前區間的公司數字，就地更新（不重建節點），再依新漲跌重新排序、調整球大小
function refreshFocusPeriod() {
    const p = currentPeriod, focusId = currentFocusedIndustry.id;
    track(fetchJSON(`/api/node_companies/${encodeURIComponent(focusId)}?period=${p}`), "載入公司清單").then(cs => {
        if (p !== currentPeriod || !currentFocusedIndustry || currentFocusedIndustry.id !== focusId) return;
        const byId = new Map(cs.map(c => [c.id, c]));
        nodes.forEach(n => {
            const c = byId.get(n.id);
            if (c) { n.price = c.price; n.change = c.change; n.ex = c.ex; n.signals = c.signals; }
        });
        relayout(0.4);
    }).catch(showRenderError);
}
document.querySelectorAll("#period-switch button").forEach(b => b.addEventListener("click", () => setPeriod(Number(b.dataset.period))));

function update() {
    const nodeById = new Map(nodes.map(n => [n.id, n]));
    const supplyData = currentFocusedIndustry ? [] : supplyLinks.filter(l => nodeById.has(l.from) && nodeById.has(l.to));
    // 每條供應關係 = 可見細線＋透明粗線（方便滑鼠指到，顯示「A 供應給 B」）
    const supply = supplyLayer.selectAll("g.supply").data(supplyData, d => `${d.from}-${d.to}`);
    supply.exit().remove();
    const supplyEnter = supply.enter().append("g").attr("class", "supply");
    supplyEnter.append("path").attr("class", "supply-link").attr("marker-end", "url(#supply-arrow)");
    supplyEnter.append("path").attr("class", "supply-hit")
        .on("mouseenter", (e, l) => highlightSupply(l.from, l.to))
        .on("mouseleave", () => highlightSupply(null))
        .append("title");
    const supplyAll = supplyEnter.merge(supply);
    supplyAll.select("title").text(l => `${nodeById.get(l.from).name} 供應給 ${nodeById.get(l.to).name}`);
    const placeSupply = () => supplyAll.each(function (l) {
        const a = nodeById.get(l.from), b = nodeById.get(l.to);
        if (!a || !b || a.x == null || b.x == null) return;
        const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
        // 微彎的弧線：同一欄上下相連時，直線會穿過中間的節點，看起來像從別的節點出發
        const bend = Math.min(len * 0.18, 90), mx = (a.x + b.x) / 2 - dy / len * bend, my = (a.y + b.y) / 2 + dx / len * bend;
        const ra = getRadius(a) * nodeScale(a) + 2, rb = getRadius(b) * nodeScale(b) + 6;   // 線止於六角形外緣，箭頭才看得到
        const ua = Math.hypot(mx - a.x, my - a.y) || 1, ub = Math.hypot(b.x - mx, b.y - my) || 1;
        const x1 = a.x + (mx - a.x) / ua * ra, y1 = a.y + (my - a.y) / ua * ra;
        const x2 = b.x - (b.x - mx) / ub * rb, y2 = b.y - (b.y - my) / ub * rb;
        d3.select(this).selectAll("path").attr("d", `M${x1},${y1} Q${mx},${my} ${x2},${y2}`);
    });

    const link = linkLayer.selectAll(".link").data(links, d => `${d.source.id || d.source}-${d.target.id || d.target}`);
    link.exit().remove();
    const linkEnter = link.enter().append("line").attr("class", "link");

    const node = nodeLayer.selectAll(".node-group").data(nodes, d => d.id);
    node.exit().remove();

    const nodeEnter = node.enter().append("g").attr("class", "node-group")
        .style("opacity", 0)
        .call(d3.drag().on("start", dragstarted).on("drag", dragged).on("end", dragended))
        .on("mouseenter", (e, d) => { if (d.type === "industry") highlightSupply(d.id); })
        .on("mouseleave", (e, d) => { if (d.type === "industry") highlightSupply(null); })
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
            el.append("circle").attr("r", r).attr("class", "node stable-node").append("title");
        }
    });

    const text = nodeEnter.append("text").attr("class", "label").attr("text-anchor", "middle").attr("dy", d => getRadius(d) + 25);
    // 產業節點名稱太長（如「印表機、傳真機、…投影機」）會壓到鄰居：超過 12 字截短，完整名稱在右上角說明
    text.append("tspan").attr("x", 0).attr("class", "label-name")
        .text(d => d.type === "industry" && d.name.length > 12 ? d.name.slice(0, 11) + "…" : d.name);
    text.append("tspan").attr("x", 0).attr("dy", "1.2em").attr("class", "label-price");
    // 公司球右上角除權息標籤、左上角訊號星點（加在名稱文字之後，tick 的 select("text") 仍取到名稱）
    nodeEnter.filter(d => d.type === "company").each(function () {
        const g = d3.select(this);
        g.append("text").attr("class", "ex-tag").attr("text-anchor", "middle").style("display", "none");
        g.append("text").attr("class", "sig-star").attr("text-anchor", "middle").text("★").style("display", "none")
            .append("title");
    });
    nodeEnter.each(function (d) { paintNode(d, d3.select(this)); });

    simulation.nodes(nodes); simulation.force("link").links(links); simulation.alpha(1).restart();

    simulation.on("tick", () => {
        const currW = window.innerWidth; const currH = window.innerHeight; const cX = currW / 2, cY = currH / 2;
        placeSupply();
        linkEnter.merge(link).attr("x1", d => d.source.x).attr("y1", d => d.source.y).attr("x2", d => d.target.x).attr("y2", d => d.target.y);
        
        nodeEnter.merge(node).each(function(d) {
            const group = d3.select(this); const r = getRadius(d); const pad = 40; 
            d.x = Math.max(r + pad, Math.min(currW - r - pad, d.x)); d.y = Math.max(r + pad, Math.min(currH - r - pad, d.y));
            
            const scale = nodeScale(d);
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
// 放開後：總覽節點留在放下的位置；聚焦中心固定回原位；公司球回到排序後的格子
function dragended(e, d) {
    if (!e.active) simulation.alphaTarget(0);
    if (!currentFocusedIndustry) { d.dragged = true; return; }
    if (d === nodes[0]) { d.fx = d.tx; d.fy = d.ty; return; }
    d.fx = null; d.fy = null;
}
svg.call(d3.zoom().on("zoom", (e) => container.attr("transform", e.transform)));

Common.mountFreshness(document.getElementById("freshness"));
Common.mountSearch(document.getElementById("search-input"), document.getElementById("search-list"));
