/**
 * MiniGauge Signal Plotter (prototype)
 * Canvas plotting of parsed CID signals: stacked lanes, overlay (one Y axis per unit), XY (+ density heatmap).
 */
(function () {
  'use strict';

  const PALETTE = ['#e8743b', '#4f9dde', '#5cc08a', '#d6b645', '#b585e0', '#e0607e', '#45c4cf', '#a3b35a'];
  // Perceptual sequential ramp (inferno-like) for the XY density heatmap
  const HEAT = [[40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66], [245, 125, 21], [250, 193, 39], [252, 255, 164]];
  const PAD = { l: 10, r: 18, t: 8, b: 34 };   // outer padding around the panel stack
  const GAP = 10;                              // vertical gap between lanes (also the resize grip)
  const AXIS_GAP = 8;                          // space between stacked overlay axes
  const FONT = '11px -apple-system, "Segoe UI", Roboto, sans-serif';

  const $ = (id) => document.getElementById(id);
  const canvas = $('plot');
  const ctx = canvas.getContext('2d');

  const store = {
    get(k, d) { try { const v = localStorage.getItem('sp.' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('sp.' + k, JSON.stringify(v)); } catch (e) { /* storage unavailable */ } },
  };

  const state = {
    data: null,
    byName: {},
    order: [],             // all signal names, in sidebar order (drag to reorder)
    selected: [],          // selected names, kept in sidebar order: drives lane order top to bottom
    colors: {},            // name -> palette index, stable while the signal stays selected
    mode: 'lanes',
    xName: null,
    view: null,            // {a, b} visible range of the x variable
    full: null,            // full range of the x variable
    weights: {},           // lane name -> relative height
    hover: null,
    drag: null,
    panels: [],
    points: false,
    step: false,
    autoY: true,
    colorByTime: true,
    heatmap: 'off',        // 'off' | 'cells' (per-cell counts) | 'full' (smoothed density over the whole XY space)
    heatCell: 8,
    heatSmooth: 0.04,      // full mode: kernel width as a fraction of the panel size
    lidsFallback: store.get('lidsFallback', true),
  };

  // ---------- helpers ----------
  const cssVar = (n) => getComputedStyle(document.body).getPropertyValue(n).trim();
  const colorOf = (name) => (state.colors[name] === undefined ? '#8a8f98' : PALETTE[state.colors[name] % PALETTE.length]);
  function assignColor(name) {
    if (state.colors[name] !== undefined) return;
    const used = new Set(state.selected.map((n) => state.colors[n]));
    let i = 0; while (used.has(i)) i++;
    state.colors[name] = i;
  }
  function setSelected(names) {
    const want = new Set(names);
    Object.keys(state.colors).forEach((n) => { if (!want.has(n)) delete state.colors[n]; });
    state.selected = [];
    state.order.forEach((n) => { if (want.has(n)) { assignColor(n); state.selected.push(n); } });
  }
  const unitOf = (n) => (state.byName[n] || {}).unit || '';
  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

  function lowerBound(arr, x) { // first idx with arr[idx] >= x
    let lo = 0, hi = arr.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m] < x) lo = m + 1; else hi = m; }
    return lo;
  }
  function atOrBefore(arr, x) { // last idx with arr[idx] <= x, or -1
    const i = lowerBound(arr, x);
    return (i < arr.length && arr[i] === x) ? i : i - 1;
  }
  function fmt(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return '–';
    const a = Math.abs(v);
    if (a >= 1000) return v.toFixed(0);
    if (a >= 100) return v.toFixed(1);
    if (a >= 1) return v.toFixed(2);
    return v.toFixed(3);
  }
  // Ticks strictly inside [a, b], with the decimals the step needs
  function niceTicks(a, b, n) {
    const span = b - a || 1;
    const raw = span / Math.max(n, 1);
    const p = Math.pow(10, Math.floor(Math.log10(raw)));
    const f = raw / p;
    const step = (f >= 5 ? 5 : f >= 2 ? 2 : 1) * p;
    const dec = Math.max(0, -Math.floor(Math.log10(step) + 1e-9));
    const ticks = [];
    for (let v = Math.ceil(a / step) * step; v <= b + step * 1e-6; v += step) ticks.push(+v.toFixed(dec + 2));
    return { ticks, step, dec };
  }
  // Time labels: seconds with step-derived decimals, or m:ss once the view spans minutes
  function timeFormatter(step, dec) {
    if (state.view.b - state.view.a >= 180 && step >= 1) {
      return (t) => { const s = Math.round(t); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
    }
    return (t) => t.toFixed(dec);
  }

  // A pause in the readout stream longer than this is a gap: the line breaks and the lane is shaded
  function gapThreshold(s) {
    if (s.gap === undefined) {
      const dt = [];
      for (let i = 1; i < s.t.length; i++) dt.push(s.t[i] - s.t[i - 1]);
      dt.sort((a, b) => a - b);
      s.gap = Math.max((dt[dt.length >> 1] || 0) * 10, 0.5);
    }
    return s.gap;
  }

  // ---------- XY data ----------
  const xyCache = new Map();
  function xySeries(yName) {
    const key = state.xName + '|' + yName;
    if (xyCache.has(key)) return xyCache.get(key);
    const X = state.byName[state.xName], Y = state.byName[yName];
    const xs = [], ys = [], ts = [];
    for (let i = 0; i < Y.t.length; i++) {
      const j = atOrBefore(X.t, Y.t[i]);   // X value held from its last sample
      if (j < 0) continue;
      xs.push(X.v[j]); ys.push(Y.v[i]); ts.push(Y.t[i]);
    }
    const s = { xs, ys, ts };
    xyCache.set(key, s);
    return s;
  }

  // ---------- ranges ----------
  function minMax(v) {
    let a = Infinity, b = -Infinity;
    for (const x of v) { if (x < a) a = x; if (x > b) b = x; }
    return [a, b];
  }
  function fullRange() {
    if (state.mode === 'xy' && state.xName) {
      const [a, b] = minMax(state.byName[state.xName].v);
      const pad = (b - a) * 0.04 || 1;
      return { a: a - pad, b: b + pad };
    }
    return { a: 0, b: state.data ? state.data.duration_s : 1 };
  }
  function resetView() { state.full = fullRange(); state.view = { ...state.full }; }

  // Y extent of (xs, ys) restricted to the visible x window (or whole series when auto-fit is off)
  function yExtent(xs, ys, sorted) {
    let lo = Infinity, hi = -Infinity;
    let i0 = 0, i1 = xs.length;
    // Time series: also count the samples just outside the window, since the drawn line (or held
    // value) reaches into it; otherwise a window between two samples gets an empty 0..1 axis.
    if (sorted && state.autoY) { i0 = Math.max(lowerBound(xs, state.view.a) - 1, 0); i1 = Math.min(lowerBound(xs, state.view.b) + 1, xs.length); }
    for (let i = i0; i < i1; i++) {
      if (!sorted && state.autoY && (xs[i] < state.view.a || xs[i] > state.view.b)) continue;
      const v = ys[i]; if (v < lo) lo = v; if (v > hi) hi = v;
    }
    return [lo, hi];
  }
  function padRange(lo, hi) {
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    if (lo === hi) { const d = Math.abs(lo) * 0.05 || 1; lo -= d; hi += d; }
    const pad = (hi - lo) * 0.08;
    return [lo - pad, hi + pad];
  }

  function seriesFor(name) {
    if (state.mode === 'xy') { const q = xySeries(name); return { xs: q.xs, ys: q.ys, ts: q.ts, sorted: false }; }
    const s = state.byName[name];
    return { xs: s.t, ys: s.v, ts: s.t, sorted: true };
  }

  // ---------- layout ----------
  function laneNames() {
    if (state.mode === 'overlay') return state.selected.length ? ['__overlay__'] : [];
    if (state.mode === 'xy') return state.selected.filter((n) => n !== state.xName);
    return state.selected.slice();
  }

  // One axis per lane; in overlay one axis per unit group, stacked left
  function buildAxes(laneName) {
    const groups = [];
    const members = laneName === '__overlay__' ? state.selected : [laneName];
    members.forEach((n) => {
      const key = laneName === '__overlay__' ? (unitOf(n) || n) : n;
      let g = groups.find((q) => q.key === key);
      if (!g) { g = { key, names: [], lo: Infinity, hi: -Infinity }; groups.push(g); }
      g.names.push(n);
      const s = seriesFor(n);
      const [lo, hi] = yExtent(s.xs, s.ys, s.sorted);
      g.lo = Math.min(g.lo, lo); g.hi = Math.max(g.hi, hi);
    });
    return groups.map((g) => {
      const [lo, hi] = padRange(g.lo, g.hi);
      return { ...g, lo, hi, color: colorOf(g.names[0]), unit: unitOf(g.names[0]) };
    });
  }

  function computeLayout(W, H) {
    const names = laneNames();
    ctx.font = FONT;
    const totalW = (W - PAD.l - PAD.r);
    const usableH = H - PAD.t - PAD.b - GAP * Math.max(names.length - 1, 0);
    const wsum = names.reduce((s, n) => s + (state.weights[n] || 1), 0) || 1;

    // First pass: heights, axes and ticks, so the left margin can fit the widest labels
    let y = PAD.t;
    const panels = names.map((name) => {
      const h = usableH * (state.weights[name] || 1) / wsum;
      const p = { name, y, h, axes: buildAxes(name) };
      y += h + GAP;
      p.axes.forEach((ax) => {
        ax.tk = niceTicks(ax.lo, ax.hi, Math.max(Math.floor(h / 36), 2));
        ax.labels = ax.tk.ticks.map((t) => t.toFixed(ax.tk.dec));
        ax.width = Math.max(ctx.measureText(ax.unit).width, ...ax.labels.map((l) => ctx.measureText(l).width)) + 10;
      });
      return p;
    });
    // Same left edge for every lane so the time axes line up
    const left = PAD.l + Math.max(30, ...panels.map((p) => p.axes.reduce((s, ax) => s + ax.width + AXIS_GAP, 0)));
    panels.forEach((p) => {
      p.x = left; p.w = Math.max(totalW - (left - PAD.l), 40);
      let off = 0;
      p.axes.forEach((ax) => { ax.x = p.x - 6 - off; off += ax.width + AXIS_GAP; });
    });
    return panels;
  }

  // ---------- drawing ----------
  function resize() {
    const r = canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(r.width * dpr);
    canvas.height = Math.round(r.height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }

  function updateReadouts() {
    const v = state.view;
    $('range-readout').textContent = !v || !state.data ? ''
      : state.mode === 'xy' ? `X: ${fmt(v.a)} … ${fmt(v.b)} ${unitOf(state.xName)}`
        : `${v.a.toFixed(2)} s … ${v.b.toFixed(2)} s  (${(v.b - v.a).toFixed(2)} s)`;
  }

  function draw() {
    const W = canvas.clientWidth, H = canvas.clientHeight;
    ctx.clearRect(0, 0, W, H);
    updateReadouts();
    const names = laneNames();
    $('empty-hint').hidden = names.length > 0;
    state.panels = [];
    if (!state.data || !state.view || !names.length) return;

    const muted = cssVar('--text-muted'), grid = cssVar('--divider'), border = cssVar('--panel-border');
    const panels = computeLayout(W, H);
    state.panels = panels;
    const xt = niceTicks(state.view.a, state.view.b, Math.max(Math.floor(panels[0].w / 90), 2));
    const xLabel = state.mode === 'xy' ? (t) => t.toFixed(xt.dec) : timeFormatter(xt.step, xt.dec);

    panels.forEach((p, idx) => {
      const px = (x) => p.x + ((x - state.view.a) / (state.view.b - state.view.a)) * p.w;
      const ax0 = p.axes[0];
      const py0 = (v) => p.y + p.h - ((v - ax0.lo) / (ax0.hi - ax0.lo)) * p.h;

      ctx.save();
      ctx.beginPath(); ctx.rect(p.x, p.y, p.w, p.h); ctx.clip();
      // grid: x ticks + first axis ticks
      ctx.strokeStyle = grid; ctx.lineWidth = 1; ctx.globalAlpha = 0.6; ctx.beginPath();
      xt.ticks.forEach((t) => { const x = Math.round(px(t)) + .5; ctx.moveTo(x, p.y); ctx.lineTo(x, p.y + p.h); });
      ax0.tk.ticks.forEach((t) => { const y = Math.round(py0(t)) + .5; ctx.moveTo(p.x, y); ctx.lineTo(p.x + p.w, y); });
      ctx.stroke(); ctx.globalAlpha = 1;

      if (state.mode === 'xy' && state.heatmap !== 'off') (state.heatmap === 'full' ? drawDensity(p, px) : drawHeatmap(p, px));
      if (state.mode === 'lanes') drawGaps(p, px, state.byName[p.name]);
      p.axes.forEach((ax) => {
        const py = (v) => p.y + p.h - ((v - ax.lo) / (ax.hi - ax.lo)) * p.h;
        ax.py = py;
        // with a heatmap on, the density replaces the points
        if (state.mode === 'xy') { if (state.heatmap === 'off') ax.names.forEach((n) => drawScatter(p, px, py, n)); }
        else ax.names.forEach((n) => drawLine(p, px, py, n));
      });
      ctx.restore();

      ctx.strokeStyle = border; ctx.strokeRect(p.x + .5, p.y + .5, p.w - 1, p.h - 1);
      drawYAxes(p, muted);
      drawLaneTitle(p);
      if (idx === panels.length - 1) drawXAxis(p, px, xt.ticks, xLabel, muted, W);
    });

    drawHover(panels);
  }

  function drawYAxes(p, muted) {
    ctx.font = FONT; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    const multi = p.axes.length > 1;
    p.axes.forEach((ax) => {
      ctx.fillStyle = multi ? ax.color : muted;
      ax.tk.ticks.forEach((t, i) => {
        // keep labels inside the lane so neighbouring lanes never overlap
        ctx.fillText(ax.labels[i], ax.x, clamp(ax.py(t), p.y + 6, p.y + p.h - 6));
      });
      if (multi) { // colored spine + unit header for each overlay axis
        ctx.strokeStyle = ax.color; ctx.globalAlpha = 0.6;
        ctx.beginPath(); ctx.moveTo(ax.x + 3.5, p.y); ctx.lineTo(ax.x + 3.5, p.y + p.h); ctx.stroke(); ctx.globalAlpha = 1;
      }
    });
  }

  function drawLaneTitle(p) {
    ctx.font = FONT; ctx.textBaseline = 'middle'; ctx.textAlign = 'left';
    const items = p.name === '__overlay__'
      ? state.selected.map((n) => ({ c: colorOf(n), t: `${n} [${unitOf(n)}]` }))
      : [{ c: colorOf(p.name), t: state.mode === 'xy' ? `${p.name} [${unitOf(p.name)}]  vs  ${state.xName}` : `${p.name} [${unitOf(p.name)}]` }];
    // chips wrap inside the lane width; a card-coloured backing keeps them readable over traces
    let x = p.x + 8, y = p.y + 12;
    const bg = cssVar('--card-bg');
    items.forEach((it) => {
      const w = ctx.measureText(it.t).width + 18;
      if (x + w > p.x + p.w - 8 && x > p.x + 8) { x = p.x + 8; y += 16; }
      if (y > p.y + p.h - 8) return;
      ctx.globalAlpha = 0.82; ctx.fillStyle = bg; ctx.fillRect(x - 4, y - 7, w, 14); ctx.globalAlpha = 1;
      ctx.fillStyle = it.c; ctx.beginPath(); ctx.arc(x + 3, y, 3.5, 0, 6.3); ctx.fill();
      ctx.fillText(it.t, x + 11, y);
      x += w + 4;
    });
  }

  function drawXAxis(p, px, ticks, label, muted, W) {
    ctx.font = FONT; ctx.fillStyle = muted; ctx.textBaseline = 'top';
    let lastRight = -Infinity;
    ticks.forEach((t) => {
      const s = label(t), w = ctx.measureText(s).width;
      // clamp to the canvas and drop labels that would collide with the previous one
      const cx = clamp(px(t), w / 2 + 2, W - w / 2 - 2);
      if (cx - w / 2 < lastRight + 6) return;
      ctx.textAlign = 'center'; ctx.fillText(s, cx, p.y + p.h + 5);
      lastRight = cx + w / 2;
    });
    const title = state.mode === 'xy' ? `${state.xName} [${unitOf(state.xName)}]`
      : (state.view.b - state.view.a >= 180 ? 'time [m:ss]' : 'time [s]');
    ctx.textAlign = 'right'; ctx.fillText(title, p.x + p.w, p.y + p.h + 19);
  }

  function drawGaps(p, px, s) {
    const g = gapThreshold(s), t = s.t;
    if (!t.length) return;
    ctx.fillStyle = cssVar('--hover-bg');
    const shade = (a, b) => { const x0 = Math.max(px(a), p.x), x1 = Math.min(px(b), p.x + p.w); if (x1 > x0) ctx.fillRect(x0, p.y, x1 - x0, p.h); };
    shade(state.full.a, t[0]);
    for (let i = 1; i < t.length; i++) if (t[i] - t[i - 1] > g) shade(t[i - 1], t[i]);
    shade(t[t.length - 1], state.full.b);
  }

  function drawLine(p, px, py, name) {
    const s = state.byName[name];
    const xs = s.t, ys = s.v, col = colorOf(name);
    const i0 = Math.max(lowerBound(xs, state.view.a) - 1, 0);
    const i1 = Math.min(lowerBound(xs, state.view.b) + 1, xs.length);
    ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.lineJoin = 'round';
    const gap = gapThreshold(s);
    const dense = (i1 - i0) > p.w * 2;
    ctx.beginPath();
    if (dense) { // per-pixel min/max decimation
      let curX = null, mn = 0, mx = 0, first = true;
      const flush = () => {
        if (curX === null) return;
        if (first) { ctx.moveTo(curX, py(mn)); first = false; } else ctx.lineTo(curX, py(mn));
        ctx.lineTo(curX, py(mx));
      };
      for (let i = i0; i < i1; i++) {
        if (i > i0 && xs[i] - xs[i - 1] > gap) { flush(); curX = null; first = true; }
        const x = Math.round(px(xs[i]));
        if (x !== curX) { flush(); curX = x; mn = mx = ys[i]; }
        else { if (ys[i] < mn) mn = ys[i]; if (ys[i] > mx) mx = ys[i]; }
      }
      flush();
    } else {
      for (let i = i0; i < i1; i++) {
        const x = px(xs[i]), y = py(ys[i]);
        if (i === i0 || xs[i] - xs[i - 1] > gap) ctx.moveTo(x, y);
        else if (state.step) { ctx.lineTo(x, py(ys[i - 1])); ctx.lineTo(x, y); }
        else ctx.lineTo(x, y);
      }
      // a lone sample between two gaps would otherwise be invisible
      if (!state.points) {
        ctx.fillStyle = col;
        for (let i = i0; i < i1; i++) {
          const before = i === 0 || xs[i] - xs[i - 1] > gap, after = i === xs.length - 1 || xs[i + 1] - xs[i] > gap;
          if (before && after) ctx.fillRect(px(xs[i]) - 1.5, py(ys[i]) - 1.5, 3, 3);
        }
      }
    }
    ctx.stroke();
    if (state.points && !dense) {
      ctx.fillStyle = col;
      for (let i = i0; i < i1; i++) { ctx.beginPath(); ctx.arc(px(xs[i]), py(ys[i]), 2.2, 0, 6.3); ctx.fill(); }
    }
  }

  function timeColor(f, base) { // fade from dim to full base color
    const c = parseInt(base.slice(1), 16);
    const mix = (ch) => Math.round(40 + (ch - 40) * (0.25 + 0.75 * f));
    return `rgb(${mix(c >> 16)},${mix((c >> 8) & 255)},${mix(c & 255)})`;
  }

  function drawScatter(p, px, py, name) {
    const { xs, ys, ts } = seriesFor(name);
    const col = colorOf(name);
    const t1 = state.data.duration_s || 1;
    ctx.globalAlpha = 0.85;
    const r = 1.5;
    for (let i = 0; i < xs.length; i++) {
      const x = px(xs[i]); if (x < p.x - 3 || x > p.x + p.w + 3) continue;
      ctx.fillStyle = (state.colorByTime ? timeColor(ts[i] / t1, col) : col);
      ctx.fillRect(x - r, py(ys[i]) - r, 2 * r, 2 * r);
    }
    ctx.globalAlpha = 1;
  }

  function heatRGB(f) {
    const x = clamp(f, 0, 1) * (HEAT.length - 1);
    const i = Math.min(Math.floor(x), HEAT.length - 2), k = x - i;
    return HEAT[i].map((a, j) => Math.round(a + (HEAT[i + 1][j] - a) * k));
  }
  function heatColor(f) { const c = heatRGB(f); return `rgb(${c[0]},${c[1]},${c[2]})`; }

  // Background density: samples per screen cell, log-scaled
  function drawHeatmap(p, px) {
    const cell = state.heatCell;
    const cols = Math.ceil(p.w / cell), rows = Math.ceil(p.h / cell);
    const counts = new Uint32Array(cols * rows);
    const { xs, ys } = seriesFor(p.name);
    const ax = p.axes[0];
    let max = 0;
    for (let i = 0; i < xs.length; i++) {
      const cx = Math.floor((px(xs[i]) - p.x) / cell);
      const cy = Math.floor((p.h - ((ys[i] - ax.lo) / (ax.hi - ax.lo)) * p.h) / cell);
      if (cx < 0 || cx >= cols || cy < 0 || cy >= rows) continue;
      const c = ++counts[cy * cols + cx];
      if (c > max) max = c;
    }
    p.heat = { counts, cols, rows, cell, max };
    if (!max) return;
    const lm = Math.log(max + 1);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const n = counts[r * cols + c]; if (!n) continue;
        ctx.fillStyle = heatColor(Math.log(n + 1) / lm);
        ctx.fillRect(p.x + c * cell, p.y + r * cell, cell, cell);
      }
    }
    drawColorBar(p, '1', `${max} /cell`);
  }

  function drawColorBar(p, loLabel, hiLabel) {
    if (p.h < 60) return;
    // colour bar, top-right inside the lane
    const bw = 90, bx = p.x + p.w - bw - 10, by = p.y + 8;
    ctx.globalAlpha = 0.82; ctx.fillStyle = cssVar('--card-bg'); ctx.fillRect(bx - 6, by - 4, bw + 12, 26); ctx.globalAlpha = 1;
    for (let i = 0; i < bw; i++) { ctx.fillStyle = heatColor(i / (bw - 1)); ctx.fillRect(bx + i, by, 1, 7); }
    ctx.font = FONT; ctx.fillStyle = cssVar('--text-muted'); ctx.textBaseline = 'top';
    ctx.textAlign = 'left'; ctx.fillText(loLabel, bx, by + 9);
    ctx.textAlign = 'right'; ctx.fillText(hiLabel, bx + bw, by + 9);
  }

  // One pass of a running-sum box blur along rows (step 1) or columns (step = cols), zero outside
  function boxBlur(src, dst, cols, rows, r, horizontal) {
    const n = horizontal ? cols : rows, lines = horizontal ? rows : cols;
    const at = horizontal ? (l, i) => l * cols + i : (l, i) => i * cols + l;
    const w = 2 * r + 1;
    for (let l = 0; l < lines; l++) {
      let acc = 0;
      for (let i = -r; i <= r; i++) if (i >= 0 && i < n) acc += src[at(l, i)];
      for (let i = 0; i < n; i++) {
        dst[at(l, i)] = acc / w;
        const add = i + r + 1, sub = i - r;
        if (add < n) acc += src[at(l, add)];
        if (sub >= 0) acc -= src[at(l, sub)];
      }
    }
  }

  // Full mode: smoothed density estimate painted over the whole XY space of the lane
  function drawDensity(p, px) {
    const cell = 3;
    const cols = Math.ceil(p.w / cell), rows = Math.ceil(p.h / cell);
    let a = new Float32Array(cols * rows), b = new Float32Array(cols * rows);
    const { xs, ys } = seriesFor(p.name);
    const ax = p.axes[0];
    let total = 0;
    for (let i = 0; i < xs.length; i++) {
      const cx = Math.floor((px(xs[i]) - p.x) / cell);
      const cy = Math.floor((p.h - ((ys[i] - ax.lo) / (ax.hi - ax.lo)) * p.h) / cell);
      if (cx < 0 || cx >= cols || cy < 0 || cy >= rows) continue;
      a[cy * cols + cx] += 1; total++;
    }
    // three box blurs approximate a Gaussian kernel of the chosen width
    const sigma = Math.max(state.heatSmooth * Math.min(p.w, p.h) / cell, 1);
    const r = Math.max(Math.round(sigma), 1);
    for (let k = 0; k < 3; k++) { boxBlur(a, b, cols, rows, r, true); boxBlur(b, a, cols, rows, r, false); }
    let max = 0;
    for (let i = 0; i < a.length; i++) if (a[i] > max) max = a[i];
    p.heat = { full: true, dens: a, cols, rows, cell, max };
    // log-ish scale so the sparse tails still read against the empty background
    // painted through an offscreen bitmap: per-cell fillRect leaves anti-aliasing seams
    const K = 200, lk = Math.log(K + 1);
    const off = document.createElement('canvas'); off.width = cols; off.height = rows;
    const octx = off.getContext('2d'), img = octx.createImageData(cols, rows);
    for (let i = 0; i < a.length; i++) {
      const c = heatRGB(Math.log(1 + K * (max ? a[i] / max : 0)) / lk);
      img.data[i * 4] = c[0]; img.data[i * 4 + 1] = c[1]; img.data[i * 4 + 2] = c[2]; img.data[i * 4 + 3] = 255;
    }
    octx.putImageData(img, 0, 0);
    ctx.imageSmoothingEnabled = true;
    ctx.drawImage(off, p.x, p.y, cols * cell, rows * cell);
    drawColorBar(p, '0', total ? 'max density' : 'no samples');
  }

  function drawHover(panels) {
    const h = state.hover; const tip = $('tooltip');
    tip.hidden = true;
    if (!h || state.drag) return;
    const p = panels.find((q) => h.py >= q.y && h.py <= q.y + q.h && h.px >= q.x && h.px <= q.x + q.w);
    if (!p) return;
    const xv = state.view.a + ((h.px - p.x) / p.w) * (state.view.b - state.view.a);

    const last = panels[panels.length - 1];
    ctx.strokeStyle = cssVar('--text-muted'); ctx.setLineDash([3, 3]); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(h.px + .5, panels[0].y); ctx.lineTo(h.px + .5, last.y + last.h); ctx.stroke();
    ctx.setLineDash([]);

    let rows = [], head = '';
    if (state.mode === 'xy') {
      const s = xySeries(p.name); const ax = p.axes[0];
      let best = -1, bd = 1e18;
      for (let i = 0; i < s.xs.length; i++) {
        const sx = p.x + ((s.xs[i] - state.view.a) / (state.view.b - state.view.a)) * p.w;
        const d = (sx - h.px) ** 2 + (ax.py(s.ys[i]) - h.py) ** 2;
        if (d < bd) { bd = d; best = i; }
      }
      if (p.heat) {
        const c = Math.floor((h.px - p.x) / p.heat.cell), r = Math.floor((h.py - p.y) / p.heat.cell);
        if (p.heat.full) {
          const d = p.heat.max ? (p.heat.dens[r * p.heat.cols + c] || 0) / p.heat.max : 0;
          rows.push({ c: 'transparent', t: `density: ${(d * 100).toFixed(d < 0.1 ? 1 : 0)} % of peak` });
        } else {
          const n = p.heat.counts[r * p.heat.cols + c] || 0;
          if (n) rows.push({ c: 'transparent', t: `density: ${n} samples in cell` });
        }
      }
      if (p.heat) { // no points to snap to: read out the cursor position instead
        const yv = ax.lo + ((p.y + p.h - h.py) / p.h) * (ax.hi - ax.lo);
        rows.unshift(
          { c: colorOf(state.xName), t: `${state.xName}: ${fmt(xv)} ${unitOf(state.xName)}` },
          { c: colorOf(p.name), t: `${p.name}: ${fmt(yv)} ${unitOf(p.name)}` },
        );
      } else if (best >= 0 && bd <= 30 * 30) {
        head = `t = ${s.ts[best].toFixed(3)} s`;
        rows.unshift(
          { c: colorOf(state.xName), t: `${state.xName}: ${fmt(s.xs[best])} ${unitOf(state.xName)}` },
          { c: colorOf(p.name), t: `${p.name}: ${fmt(s.ys[best])} ${unitOf(p.name)}` },
        );
      } else if (!rows.length) return;
    } else {
      head = `t = ${xv.toFixed(3)} s`;
      // stacked lanes share the time cursor, so list every selected signal
      rows = state.selected.map((n) => {
        const s = state.byName[n]; const i = atOrBefore(s.t, xv);
        const stale = i < 0 || xv - s.t[i] > gapThreshold(s);
        return { c: colorOf(n), t: stale ? `${n}: no data` : `${n}: ${fmt(s.v[i])} ${s.unit}` };
      });
    }
    tip.innerHTML = (head ? `<div class="text-muted">${head}</div>` : '') +
      rows.map((r) => `<div class="row"><span class="dot" style="background:${r.c}"></span>${r.t}</div>`).join('');
    tip.hidden = false;
    const W = canvas.clientWidth, H = canvas.clientHeight;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    tip.style.left = clamp(h.px + 14 + tw > W ? h.px - tw - 14 : h.px + 14, 4, Math.max(W - tw - 4, 4)) + 'px';
    tip.style.top = clamp(h.py - 10, 4, Math.max(H - th - 4, 4)) + 'px';
  }

  // ---------- interaction ----------
  function pos(e) { const r = canvas.getBoundingClientRect(); return { px: e.clientX - r.left, py: e.clientY - r.top }; }
  function xAt(px) { const p = state.panels[0]; if (!p) return 0; return state.view.a + ((px - p.x) / p.w) * (state.view.b - state.view.a); }
  // index i of the grip between panel i and i+1 under the cursor, or -1
  function gripAt(py, px) {
    const ps = state.panels;
    if (!ps.length || px < ps[0].x) return -1;
    for (let i = 0; i < ps.length - 1; i++) {
      const top = ps[i].y + ps[i].h, bot = ps[i + 1].y;
      if (py >= top - 2 && py <= bot + 2) return i;
    }
    return -1;
  }

  canvas.addEventListener('wheel', (e) => {
    if (!state.view) return; e.preventDefault();
    const x = xAt(pos(e).px);
    const k = e.deltaY > 0 ? 1.2 : 1 / 1.2;
    let a = x - (x - state.view.a) * k, b = x + (state.view.b - x) * k;
    const span = state.full.b - state.full.a;
    if (b - a > span) { a = state.full.a; b = state.full.b; }
    if (b - a < span * 1e-5) return;
    state.view = { a, b }; draw();
  }, { passive: false });

  canvas.addEventListener('mousedown', (e) => {
    if (!state.view) return;
    const { px, py } = pos(e);
    const g = gripAt(py, px);
    if (g >= 0) {
      const a = state.panels[g], b = state.panels[g + 1];
      state.drag = { grip: g, py, ha: a.h, hb: b.h, wa: state.weights[a.name] || 1, wb: state.weights[b.name] || 1 };
      return;
    }
    state.drag = { px, py, a: state.view.a, b: state.view.b, box: e.shiftKey, cur: px };
  });
  window.addEventListener('mousemove', (e) => {
    const m = pos(e);
    const d = state.drag;
    if (d && d.grip !== undefined) { // resize two adjacent lanes, keeping their combined weight
      const a = state.panels[d.grip], b = state.panels[d.grip + 1];
      const tot = d.ha + d.hb, ha = clamp(d.ha + (m.py - d.py), 40, tot - 40);
      const wt = d.wa + d.wb;
      state.weights[a.name] = wt * ha / tot; state.weights[b.name] = wt * (tot - ha) / tot;
      draw(); return;
    }
    if (d) {
      d.cur = m.px;
      if (!d.box) {
        const p = state.panels[0]; const dx = (m.px - d.px) / p.w * (d.b - d.a);
        state.view = { a: d.a - dx, b: d.b - dx };
      }
      draw();
      if (d.box) {
        const p = state.panels[0], last = state.panels[state.panels.length - 1];
        ctx.fillStyle = cssVar('--badge-bg');
        ctx.fillRect(clamp(Math.min(d.px, d.cur), p.x, p.x + p.w), p.y, Math.abs(clamp(d.cur, p.x, p.x + p.w) - clamp(d.px, p.x, p.x + p.w)), last.y + last.h - p.y);
      }
      return;
    }
    if (e.target === canvas) {
      canvas.style.cursor = gripAt(m.py, m.px) >= 0 ? 'row-resize' : 'crosshair';
      state.hover = m; draw();
    }
  });
  window.addEventListener('mouseup', () => {
    const d = state.drag; if (!d) return;
    if (d.box && Math.abs(d.cur - d.px) > 4) state.view = { a: xAt(Math.min(d.px, d.cur)), b: xAt(Math.max(d.px, d.cur)) };
    state.drag = null; draw();
  });
  canvas.addEventListener('mouseleave', () => { state.hover = null; draw(); });
  canvas.addEventListener('dblclick', (e) => {
    const { px, py } = pos(e);
    if (gripAt(py, px) >= 0) { state.weights = {}; draw(); return; }  // double-click a grip: equal lane heights
    resetView(); draw();
  });
  $('btn-reset-zoom').addEventListener('click', () => { resetView(); draw(); });
  new ResizeObserver(resize).observe(canvas.parentElement);
  new MutationObserver(draw).observe(document.documentElement, { attributes: true });
  new MutationObserver(draw).observe(document.body, { attributes: true });

  // Sidebar splitter
  (function () {
    const side = document.querySelector('.sp-sidebar'), grip = $('sidebar-grip');
    side.style.width = clamp(store.get('sidebarW', 280), 180, 520) + 'px';
    grip.addEventListener('mousedown', (e) => {
      e.preventDefault();
      const x0 = e.clientX, w0 = side.getBoundingClientRect().width;
      document.body.classList.add('sp-resizing');
      const move = (ev) => { side.style.width = clamp(w0 + ev.clientX - x0, 180, 520) + 'px'; };
      const up = () => {
        window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up);
        document.body.classList.remove('sp-resizing');
        store.set('sidebarW', side.getBoundingClientRect().width);
      };
      window.addEventListener('mousemove', move); window.addEventListener('mouseup', up);
    });
    grip.addEventListener('dblclick', () => { side.style.width = '280px'; store.set('sidebarW', 280); });
  })();

  // ---------- sidebar & toolbar ----------
  function renderList() {
    const q = $('signal-filter').value.trim().toLowerCase();
    const ul = $('signal-list'); ul.innerHTML = '';
    const sigs = state.data ? state.order.map((n) => state.byName[n]) : [];
    sigs.filter((s) => !q || s.name.toLowerCase().includes(q)).forEach((s) => {
      const li = document.createElement('li');
      li.draggable = true;
      li.dataset.name = s.name;
      const sel = state.selected.includes(s.name);
      li.className = sel ? 'selected' : '';
      const isX = state.mode === 'xy' && state.xName === s.name;
      li.innerHTML = `<span class="grip" aria-hidden="true">⠿</span><span class="swatch" style="background:${sel ? colorOf(s.name) : 'transparent'}"></span>` +
        `<span class="name">${s.name}</span>${isX ? '<span class="xmark">X</span>' : ''}` +
        `<span class="meta">${s.unit || ''} · ${s.t.length}</span>`;
      li.title = `${s.cid || ''} · LID ${s.lid || '?'} · ${s.t.length} samples`;
      li.addEventListener('click', () => toggle(s.name));
      li.addEventListener('dragstart', (e) => {
        dragName = s.name; li.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', s.name);
      });
      li.addEventListener('dragend', () => { dragName = null; li.classList.remove('dragging'); clearDropMarks(); });
      li.addEventListener('dragover', (e) => {
        if (!dragName || dragName === s.name) return;
        e.preventDefault();
        const r = li.getBoundingClientRect(), below = e.clientY > r.top + r.height / 2;
        clearDropMarks(); li.classList.add(below ? 'drop-below' : 'drop-above');
      });
      li.addEventListener('drop', (e) => {
        e.preventDefault();
        if (!dragName || dragName === s.name) return;
        const below = li.classList.contains('drop-below');
        moveSignal(dragName, s.name, below);
      });
      ul.appendChild(li);
    });
    $('signal-count').textContent = `${state.selected.length} / ${sigs.length} selected`;
  }

  let dragName = null;
  function clearDropMarks() {
    document.querySelectorAll('.drop-above, .drop-below').forEach((el) => el.classList.remove('drop-above', 'drop-below'));
  }
  // Move `name` next to `target` in the sidebar order; lanes follow because selection is kept in that order
  function moveSignal(name, target, below) {
    const o = state.order.filter((n) => n !== name);
    o.splice(o.indexOf(target) + (below ? 1 : 0), 0, name);
    state.order = o;
    setSelected(state.selected);
    renderList(); draw();
  }

  function renderXSelect() {
    const sel = $('select-x'); const prev = state.xName;
    sel.innerHTML = state.data.signals.map((s) => `<option value="${s.name}">${s.name} [${s.unit}]</option>`).join('');
    if (prev && state.byName[prev]) sel.value = prev;
    state.xName = sel.options.length ? sel.value : null;
  }

  function toggle(name) {
    setSelected(state.selected.includes(name) ? state.selected.filter((n) => n !== name) : [...state.selected, name]);
    renderList(); draw();
  }

  function setMode(mode) {
    state.mode = mode;
    document.querySelectorAll('.seg-btn').forEach((b) => b.classList.toggle('active', b.dataset.mode === mode));
    $('xy-controls').hidden = mode !== 'xy';
    $('time-controls').hidden = mode === 'xy';
    resetView(); renderList(); draw();
  }
  document.querySelectorAll('.seg-btn').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.mode)));
  $('select-x').addEventListener('change', (e) => { state.xName = e.target.value; xyCache.clear(); resetView(); renderList(); draw(); });
  $('chk-points').addEventListener('change', (e) => { state.points = e.target.checked; draw(); });
  $('chk-step').addEventListener('change', (e) => { state.step = e.target.checked; draw(); });
  $('chk-autoy').addEventListener('change', (e) => { state.autoY = e.target.checked; draw(); });
  $('chk-xy-time').addEventListener('change', (e) => { state.colorByTime = e.target.checked; draw(); });
  // The size select means cell size in 'cells' mode and kernel width in 'full' mode
  function renderHeatSize() {
    const sel = $('select-cell');
    if (state.heatmap === 'full') {
      sel.title = 'Smoothing (kernel width, % of chart)';
      sel.innerHTML = [0.02, 0.04, 0.08, 0.15].map((v) => `<option value="${v}">smooth ${v * 100}%</option>`).join('');
      sel.value = String(state.heatSmooth);
    } else {
      sel.title = 'Heatmap cell size';
      sel.innerHTML = [4, 8, 16, 32].map((v) => `<option value="${v}">${v} px</option>`).join('');
      sel.value = String(state.heatCell);
    }
    sel.disabled = state.heatmap === 'off';
    $('chk-xy-time').disabled = state.heatmap !== 'off';   // only affects points, which a heatmap hides
  }
  $('select-heatmap').addEventListener('change', (e) => { state.heatmap = e.target.value; renderHeatSize(); draw(); });
  $('select-cell').addEventListener('change', (e) => {
    if (state.heatmap === 'full') state.heatSmooth = +e.target.value; else state.heatCell = +e.target.value;
    draw();
  });
  renderHeatSize();
  $('signal-filter').addEventListener('input', renderList);
  $('btn-clear').addEventListener('click', () => { setSelected([]); renderList(); draw(); });
  $('chk-lids-fallback').checked = state.lidsFallback;
  $('chk-lids-fallback').addEventListener('change', (e) => {
    state.lidsFallback = e.target.checked; store.set('lidsFallback', state.lidsFallback);
    loadFile($('select-log-file').value, true);
  });

  // ---------- data ----------
  async function loadFile(name, keepSelection) {
    if (!name) return;
    try {
      const r = await fetch(`/api/signals?file=${encodeURIComponent(name)}&lids_fallback=${state.lidsFallback}`);
      const d = await r.json();
      if (d.error) throw new Error(d.error);
      const prevSel = state.selected, prevView = state.view, prevOrder = state.order;
      state.data = d; state.byName = {}; xyCache.clear();
      d.signals.forEach((s) => { state.byName[s.name] = s; });
      // keep a custom order across reloads of the same log; new names go to the end
      const names = d.signals.map((s) => s.name);
      state.order = keepSelection ? [...prevOrder.filter((n) => state.byName[n]), ...names.filter((n) => !prevOrder.includes(n))] : names;
      if (!keepSelection) state.colors = {};
      let sel = keepSelection ? prevSel.filter((n) => state.byName[n]) : [];
      if (!sel.length) sel = names.slice(0, 3);
      setSelected(sel);
      renderXSelect();
      resetView();
      if (keepSelection && prevView && state.mode !== 'xy') state.view = prevView;
      renderList(); draw();
      if (!d.signals.length) window.Toast.info('No decoded signals in this log (no LID definition or readout found).');
    } catch (err) {
      window.Toast.error('Load failed: ' + err.message);
    }
  }

  async function init() {
    const files = await (await fetch('/api/files')).json();
    const sel = $('select-log-file');
    sel.innerHTML = files.map((f) => `<option value="${f.filename}">${f.filename}</option>`).join('');
    sel.addEventListener('change', () => loadFile(sel.value));
    // prefer a log that actually contains readouts
    const pick = files.find((f) => /candump-2024-08-11/.test(f.filename)) || files[0];
    if (pick) { sel.value = pick.filename; loadFile(pick.filename); }
    resize();
  }
  init();
})();
