/**
 * MiniGauge Leaflet Map Utilities & Tile Layer Synchronizer
 */

(function () {
  const TILES_DARK = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
  const TILES_LIGHT = 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png';
  const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>';

  function getTileUrl(isLight) {
    return isLight ? TILES_LIGHT : TILES_DARK;
  }

  function createTileLayer(isLight) {
    if (typeof L === 'undefined') return null;
    return L.tileLayer(getTileUrl(isLight), {
      attribution: ATTRIBUTION,
      maxZoom: 19,
      subdomains: 'abcd',
    });
  }

  function setupMapThemeSync(map, tileLayerRef) {
    window.addEventListener('minigauge-theme-changed', (e) => {
      if (!map || !tileLayerRef.current) return;
      const isLight = e.detail.isLight;
      tileLayerRef.current.setUrl(getTileUrl(isLight));
    });
  }

  function createVehicleIcon(headingDeg = 0, color = '#dd6b3d') {
    if (typeof L === 'undefined') return null;
    return L.divIcon({
      className: 'vehicle-marker-icon',
      html: `<div style="transform: rotate(${headingDeg}deg); width:28px; height:28px; display:flex; align-items:center; justify-content:center;">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="${color}">
          <path d="M12 2L4 20L12 16L20 20L12 2Z" stroke="#ffffff" stroke-width="1.5" stroke-linejoin="round"/>
        </svg>
      </div>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
  }

  function binarySearchTimestamp(points, targetS) {
    if (!points || points.length === 0) return null;
    let low = 0;
    let high = points.length - 1;

    while (low <= high) {
      const mid = Math.floor((low + high) / 2);
      const pt = points[mid];
      const t = pt.time_s !== undefined ? pt.time_s : pt[0];

      if (Math.abs(t - targetS) < 0.05) {
        return pt;
      }
      if (t < targetS) {
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }
    const idx = Math.min(Math.max(low, 0), points.length - 1);
    return points[idx];
  }

  window.MapUtils = {
    TILES_DARK,
    TILES_LIGHT,
    ATTRIBUTION,
    getTileUrl,
    createTileLayer,
    setupMapThemeSync,
    createVehicleIcon,
    binarySearchTimestamp,
  };
})();

