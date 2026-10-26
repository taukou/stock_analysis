// 兩頁共用：資料新鮮度、搜尋。瀏覽器掛在 window.Common，node 以 module.exports 匯出純函式供測試
(function (root) {
  const FRESH_CLASSES = ["fresh-ok", "fresh-stale", "fresh-failed"];
  const freshnessClass = level =>
    level === "ok" ? "fresh-ok" : level === "failed" ? "fresh-failed" : "fresh-stale";

  // 搜尋結果 → 產業頁網址；沒有節點／產業歸屬就回 null
  function searchUrl(hit) {
    if (!hit || !hit.major_id || !hit.node_id) return null;
    const e = encodeURIComponent;
    return `/industry/${e(hit.major_id)}?node=${e(hit.node_id)}&company=${e(hit.stock_id)}`;
  }

  // 新鮮度膠囊的滑鼠提示：每個資料集一行，用中文名稱（API 舊版沒有 label 時退回英文鍵）
  const STATUS_TEXT = { ok: "正常", failed: "失敗" };
  function freshnessTooltip(datasets) {
    return (datasets || []).map(d =>
      `${d.label || d.dataset}：${d.last_date || "—"}（${STATUS_TEXT[d.status] || d.status || "—"}）`).join("\n");
  }

  function mountFreshness(el) {
    const apply = (cls, text, title) => {
      el.classList.remove(...FRESH_CLASSES);
      el.classList.add(cls);
      el.textContent = text;
      el.title = title;
    };
    return fetch("/api/freshness")
      .then(res => { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json(); })
      .then(f => {
        apply(freshnessClass(f.level), f.message || "資料狀態未知", freshnessTooltip(f.datasets));
      })
      .catch(() => apply("fresh-stale", "資料狀態未知", ""));
  }

  function mountSearch(input, list) {
    let timer = null, seq = 0, hits = [];
    const hide = () => { list.style.display = "none"; list.replaceChildren(); hits = []; };
    // 下拉面板貼在輸入框正下方（fixed，避免被父層玻璃裁切或疊玻璃）
    const place = () => {
      const r = input.getBoundingClientRect();
      list.style.left = `${r.left}px`;
      list.style.top = `${r.bottom + 8}px`;
      list.style.minWidth = `${Math.max(r.width, 220)}px`;
    };
    const go = hit => { const u = searchUrl(hit); if (u) location.href = u; };

    function render() {
      list.replaceChildren();
      if (!hits.length) { hide(); return; }
      hits.forEach(hit => {
        const row = document.createElement("div");
        row.className = "search-row";
        const label = document.createElement("span");
        label.textContent = `${hit.stock_id} ${hit.company_name}`;
        row.appendChild(label);
        if (searchUrl(hit)) {
          row.addEventListener("mousedown", ev => { ev.preventDefault(); go(hit); });
        } else {
          row.classList.add("disabled");
          const note = document.createElement("small");
          note.textContent = "未歸類節點";
          row.appendChild(note);
        }
        list.appendChild(row);
      });
      place();
      list.style.display = "block";
    }

    // 查詢目前輸入；回傳的 promise 給出該次結果，被較新的查詢取代時給 null
    let latest = null;
    function search(q) {
      const mine = ++seq;
      latest = fetch(`/api/search?q=${encodeURIComponent(q)}`)
        .then(res => { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json(); })
        .then(rows => { if (mine !== seq) return null; hits = rows; render(); return rows; })
        .catch(() => { if (mine === seq) hide(); return null; });
      return latest;
    }

    input.addEventListener("input", () => {
      clearTimeout(timer); timer = null;
      hits = [];   // 舊查詢的結果不再適用（Enter 不可導向上一個查詢的結果）
      const q = input.value.trim();
      if (!q) { seq++; latest = null; hide(); return; }
      timer = setTimeout(() => { timer = null; search(q); }, 250);
    });
    input.addEventListener("keydown", ev => {
      if (ev.key === "Escape") { clearTimeout(timer); timer = null; seq++; latest = null; hide(); input.blur(); }
      else if (ev.key === "Enter") {
        // 還在 debounce：立刻查目前輸入；查詢進行中：等它回來
        let pending = latest;
        if (timer) {
          clearTimeout(timer); timer = null;
          const q = input.value.trim();
          pending = q ? search(q) : null;
        }
        Promise.resolve(pending ? pending : hits).then(rows => {
          const hit = (rows || []).find(h => searchUrl(h));
          if (hit) go(hit);
        });
      }
    });
    input.addEventListener("blur", () => setTimeout(hide, 150));
  }

  // 導覽列 scroll-spy：sectionTops 為各區塊頂端的文件座標（區塊隱藏時給 null）。
  // 頂端已越過視窗 40% 高度線的區塊中，取最後一個；都還沒到就取第一個可見區塊；全部隱藏回 -1
  function activeSection(sectionTops, scrollY, viewportH) {
    const line = scrollY + viewportH * 0.4;
    let active = -1, first = -1;
    (sectionTops || []).forEach((top, i) => {
      if (typeof top !== "number" || !isFinite(top)) return;
      if (first < 0) first = i;
      if (top <= line) active = i;
    });
    return active >= 0 ? active : first;
  }

  // 首頁頂部分頁：點擊平滑捲動並立即移動高亮，捲動時高亮跟著所在區塊
  // tabs: [{el, target}]（target 為區塊元素；首頁用 hero）；pill 為滑動高亮元素
  function mountNavTabs(tabs, pill) {
    let current = -1, clickLock = 0;
    const visible = t => !t.el.hidden && t.target && !t.target.hidden;
    const tops = () => tabs.map(t => visible(t)
      ? t.target.getBoundingClientRect().top + window.scrollY : null);

    function movePill(i) {
      const el = i >= 0 ? tabs[i].el : null;
      if (!el || el.hidden) { pill.style.opacity = "0"; return; }
      pill.style.opacity = "1";
      pill.style.width = `${el.offsetWidth}px`;
      pill.style.transform = `translateX(${el.offsetLeft}px)`;
    }
    function setActive(i) {
      current = i;
      tabs.forEach((t, k) => {
        if (k === i) t.el.setAttribute("aria-current", "page");
        else t.el.removeAttribute("aria-current");
      });
      movePill(i);
    }
    function update() {
      if (Date.now() < clickLock) return;   // 點擊後的平滑捲動途中不讓高亮跳回去
      const i = activeSection(tops(), window.scrollY, window.innerHeight);
      if (i !== current) setActive(i);
    }
    let ticking = false;
    window.addEventListener("scroll", () => {
      if (!ticking) { ticking = true; requestAnimationFrame(() => { ticking = false; update(); }); }
    }, { passive: true });
    window.addEventListener("resize", () => movePill(current));

    tabs.forEach((t, i) => t.el.addEventListener("click", ev => {
      ev.preventDefault();
      setActive(i);
      clickLock = Date.now() + 900;
      t.target.scrollIntoView({ behavior: "smooth", block: "start" });
      setTimeout(update, 950);
    }));
    // 初次定位不要動畫（pill 還沒有位置）
    pill.style.transition = "none";
    setActive(activeSection(tops(), window.scrollY, window.innerHeight));
    pill.offsetWidth;   // 強制重排
    pill.style.transition = "";
    return { refresh: () => { current = -2; update(); } };
  }

  const api = { freshnessClass, freshnessTooltip, searchUrl, mountFreshness, mountSearch, activeSection, mountNavTabs };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Common = api;
})(typeof window !== "undefined" ? window : globalThis);
