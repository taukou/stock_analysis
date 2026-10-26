// 格式與顏色純函式：瀏覽器掛在 window.Fmt，node 以 module.exports 匯出供測試
(function (root) {
  // ---- 缺值（null）一律顯示「—」並用中性色，不當成 0 ----
  const isNil = v => v === null || v === undefined;
  const fmtNum = (v, suffix = "") => isNil(v) ? "—" : `${v}${suffix}`;
  const fmtSigned = (v, suffix = "") => isNil(v) ? "—" : `${v > 0 ? '+' : ''}${v}${suffix}`;
  const upDownClass = (v, prefix) => isNil(v) || v === 0 ? `${prefix}-stable` : (v > 0 ? `${prefix}-up` : `${prefix}-down`);

  // 區間 → 該區間 ±此值 % 即最深色
  const HEAT_SCALE = {1: 3, 5: 8, 20: 15};
  const NEUTRAL = [100, 116, 139];   // #64748b
  const UP_RGB = [255, 77, 109];     // #ff4d6d
  const DOWN_RGB = [34, 197, 94];    // #22c55e

  function heatColor(v, period) {
    if (isNil(v)) return "#64748b";
    if (v === 0) return "rgb(100, 116, 139)";
    const t = Math.min(Math.abs(v) / HEAT_SCALE[period], 1);
    const target = v > 0 ? UP_RGB : DOWN_RGB;
    const c = NEUTRAL.map((n, i) => Math.round(n + (target[i] - n) * t));
    return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
  }

  const lots = shares => isNil(shares) ? null : Math.round(shares / 1000);

  const WATCH_KEY = "stockchain.watchlist";
  function loadWatchlist(storage) {
    try {
      const list = JSON.parse(storage.getItem(WATCH_KEY));
      return Array.isArray(list) ? list : [];
    } catch (e) {
      return [];
    }
  }
  function toggleWatch(storage, id) {
    try {
      const list = loadWatchlist(storage);
      const i = list.indexOf(id);
      if (i >= 0) list.splice(i, 1); else list.push(id);
      storage.setItem(WATCH_KEY, JSON.stringify(list));
      return i < 0;
    } catch (e) {
      return false;
    }
  }

  const api = { isNil, fmtNum, fmtSigned, upDownClass, HEAT_SCALE, heatColor, lots, WATCH_KEY, loadWatchlist, toggleWatch };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.Fmt = api;
})(typeof window !== "undefined" ? window : globalThis);
