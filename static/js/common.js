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

    input.addEventListener("input", () => {
      clearTimeout(timer);
      const q = input.value.trim();
      if (!q) { seq++; hide(); return; }
      timer = setTimeout(() => {
        const mine = ++seq;
        fetch(`/api/search?q=${encodeURIComponent(q)}`)
          .then(res => { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json(); })
          .then(rows => { if (mine !== seq) return; hits = rows; render(); })
          .catch(() => { if (mine === seq) hide(); });
      }, 250);
    });
    input.addEventListener("keydown", ev => {
      if (ev.key === "Escape") { seq++; hide(); input.blur(); }
      else if (ev.key === "Enter") {
        const hit = hits.find(h => searchUrl(h));
        if (hit) go(hit);
      }
    });
    input.addEventListener("blur", () => setTimeout(hide, 150));
  }

  const api = { freshnessClass, freshnessTooltip, searchUrl, mountFreshness, mountSearch };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Common = api;
})(typeof window !== "undefined" ? window : globalThis);
