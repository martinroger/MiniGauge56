/**
 * MiniGauge Signal Plotter (prototype)
 * Canvas plotting of parsed CID signals: stacked lanes, overlay (normalized), XY.
 */
(function () {
  'use strict';

  const PALETTE = ['#e8743b', '#4f9dde', '#5cc08a', '#d6b645', '#b585e0', '#e0607e', '#45c4cf', '#a3b35a'];
  const M = { l: 64, r: 16, t: 10, b: 28 };

  const $ = (id) => document.getElementById(id);
  const canvas = $('plot');
  const ctx = canvas.getContext('2d');

  const state = {
    data: null,
    byName: {},
    selected: [],          // ordered signal names
    mode: 'lanes',
    xName: null,
    view: null,            // {a, b} visible range of the x variable
    full: null,            // full range of the x variable
    hover: null,           // {px, py}
    drag: null,
    points: false,
    step: false,
    colorByTime: true,
  };

  // ---------- helpers ----------
  const cssVar = (n) => getComputedStyle(document.body).getPropertyValue(n).trim();
  const colorOf = (name) => PALETTE[state.selected.indexOf(name) % PALETTE.length];

  function lowerBound(arr, x) { // first idx with arr[idx] >= x
    let lo = 0, hi = arr.length;
    while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m] < x) lo = m + 1; else hi = m; }
    return lo;
  }
  function atOrBefore(arr, x) { // last idx with arr[idx] <= x, or -1
    let i = lowerBound(arr, x);
    if (i < arr.length && arr[i] === x) return i;
    return i - 1;
  }
  function fmt(v) {
    if (v === null || v === undefined || Number.isNaN(v)) return '–';
    const a = Math.abs(v);
    if (a >= 1000) return v.toFixed(0);
    if (a >= 100) return v.toFixed(1);
    if (a >= 1) return v.toFixed(2);
    return v.toFixed(3);
  }
  function niceTicks(a, b, n) {
    const span = b - a || 1;
    const raw = span / n;
    const p = Math.pow(10, Math.floor(Math.log10(raw)));
    const f = raw / p;
    const step = (f >= 5 ? 5 : f >= 2 ? 2 : 1) * p;
    const out = [];
    for (let v = Math.ceil(a / step) * step; v <= b + 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }

  // ---------- XY data ----------
  const xyCache = new Map();
  function xySeries(yName) {
    const key = state.xName + '|' + yName;
    if (xyCache.has(key)) return xyCache.get(key);
    const X = state.byName[state.xName], Y = state.byName[yName];
    const xs = [], ys = [], ts = [];
    for (let i = 0; i < Y.t.length; i++) {
      const j = atOrBefore(X.t, Y.t[i]);
      if (j < 0) continue;
      xs.push(X.v[j]); ys.push(Y.v[i]); ts.push(Y.t[i]);
    }
    const s = { xs, ys, ts };
    xyCache.set(key, s);
    return s;
  }

  // ---------- ranges ----------
  function fullRange() {
    if (state.mode === 'xy' && state.xName) {
      const v = state.byName[state.xName].v;
      let a = Infinity, b = -Infinity;
      for (const x of v) { if (x < a) a = x; if (x > b) b = x; }
      const pad = (b - a) * 0.04 || 1;
      return { a: a - pad, b: b + pad };
    }
    return { a: 0, b: state.data ? state.data.duration_s : 1 };
  }
  function resetView() { state.full = fullRange(); state.view = { ...state.full }; }

  // ---------- drawing ----------
  function resize() {
    const r = canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(r.width * dpr);
    canvas.height = Math.round(r.height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }

  function lanesList() {
    if (state.mode === 'xy') return state.selected.filter((n) => n !== state.xName);
    return state.selected;
  }

  // Returns [{name, rect, yA, yB}] describing each drawn panel
  function layout(W, H) {
    const names = state.mode === 'overlay' ? [null] : lanesList();
    const n = Math.max(names.length, 1);
    const gap = 6;
    const ph = (H - M.t - M.b - gap * (n - 1)) / n;
    return names.map((name, i) => ({
      name,
      x: M.l, w: W - M.l - M.r,
      y: M.t + i * (ph + gap), h: ph,
    }));
  }

  function visibleRange(xs, a, b) {
    return [Math.max(lowerBound(xs, a) - 1, 0), Math.min(lowerBound(xs, b) + 1, xs.length)];
  }

  function yRange(name, xsOf, ysOf) {
    const [i0, i1] = visibleRange(xsOf, state.view.a, state.view.b);
    let lo = Infinity, hi = -Infinity;
    for (let i = i0; i < i1; i++) {
      if (xsOf[i] < state.view.a || xsOf[i] > state.view.b) continue;
      const v = ysOf[i]; if (v < lo) lo = v; if (v > hi) hi = v;
    }
    if (!isFinite(lo)) { lo = 0; hi = 1; }
    if (lo === hi) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.08;
    return [lo - pad, hi + pad];
  }

  function drawPlot() {
    const W = canvas.clientWidth, H = canvas.clientHeight;
    ctx.clearRect(0, 0, W, H);
    $('empty-hint').hidden = lanesList().length > 0 || (state.mode === 'overlay' && state.selected.length > 0);
    $('range-readout').textContent = state.view && state.data
      ? (state.mode === 'xy' ? `X: ${fmt(state.view.a)} … ${fmt(state.view.b)} ${unitOf(state.xName)}`
        : `${state.view.a.toFixed(2)} s … ${state.view.b.toFixed(2)} s`) : '';
    if (!state.data || !state.view || !state.selected.length) return;

    const text = cssVar('--text-muted'), grid = cssVar('--divider'), border = cssVar('--panel-border');
    ctx.font = '11px -apple-system, "Segoe UI", sans-serif';
    const panels = layout(W, H);
    state.panels = panels;

    panels.forEach((p, idx) => {
      const isLast = idx === panels.length - 1;
      ctx.save();
      ctx.beginPath(); ctx.rect(p.x, p.y, p.w, p.h); ctx.clip();

      // x grid
      const xt = niceTicks(state.view.a, state.view.b, Math.max(Math.floor(p.w / 90), 2));
      const px = (x) => p.x + ((x - state.view.a) / (state.view.b - state.view.a)) * p.w;
      ctx.strokeStyle = grid; ctx.lineWidth = 1; ctx.globalAlpha = 0.5;
      ctx.beginPath(); xt.forEach((t) => { ctx.moveTo(Math.round(px(t)) + .5, p.y); ctx.lineTo(Math.round(px(t)) + .5, p.y + p.h); }); ctx.stroke();
      ctx.globalAlpha = 1;

      if (state.mode === 'overlay') drawOverlay(p, px);
      else drawLane(p, px);
      ctx.restore();

      ctx.strokeStyle = border; ctx.strokeRect(p.x + .5, p.y + .5, p.w, p.h);
      if (isLast) { // x tick labels
        ctx.fillStyle = text; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
        xt.forEach((t) => ctx.fillText(state.mode === 'xy' ? fmt(t) : t.toFixed(t % 1 ? 1 : 0) + ' s', px(t), p.y + p.h + 6));
      }
    });

    drawHover(panels);
  }

  function unitOf(n) { return (state.byName[n] || {}).unit || ''; }

  function drawLane(p, px) {
    const s = state.byName[p.name];
    const col = colorOf(p.name);
    let xs, ys, ts = null;
    if (state.mode === 'xy') { const q = xySeries(p.name); xs = q.xs; ys = q.ys; ts = q.ts; }
    else { xs = s.t; ys = s.v; }
    // In XY mode x is not sorted, so range scans are linear
    const sorted = state.mode !== 'xy';
    const [lo, hi] = yRange(p.name, xs, ys);
    p.yA = lo; p.yB = hi;
    const py = (v) => p.y + p.h - ((v - lo) / (hi - lo)) * p.h;

    // y axis
    const yt = niceTicks(lo, hi, Math.max(Math.floor(p.h / 40), 2));
    ctx.fillStyle = cssVar('--text-muted'); ctx.strokeStyle = cssVar('--divider');
    ctx.globalAlpha = 0.5; ctx.beginPath();
    yt.forEach((t) => { ctx.moveTo(p.x, Math.round(py(t)) + .5); ctx.lineTo(p.x + p.w, Math.round(py(t)) + .5); });
    ctx.stroke(); ctx.globalAlpha = 1;
    p._yt = yt; p._py = py;

    if (state.mode === 'xy') {
      const [t0, t1] = [state.data.signals.reduce((m, q) => q.t.length ? Math.min(m, q.t[0]) : m, Infinity), state.data.duration_s];
      for (let i = 0; i < xs.length; i++) {
        const x = px(xs[i]); if (x < p.x - 3 || x > p.x + p.w + 3) continue;
        ctx.fillStyle = state.colorByTime ? timeColor((ts[i] - t0) / (t1 - t0 || 1), col) : col;
        ctx.globalAlpha = 0.85;
        ctx.fillRect(x - 1.5, py(ys[i]) - 1.5, 3, 3);
      }
      ctx.globalAlpha = 1;
    } else {
      plotLine(p, px, py, xs, ys, col, sorted);
    }
  }

  function timeColor(f, base) { // fade from dim to full base color
    const c = parseInt(base.slice(1), 16);
    const mix = (ch) => Math.round(40 + (ch - 40) * (0.25 + 0.75 * f));
    return `rgb(${mix(c >> 16)},${mix((c >> 8) & 255)},${mix(c & 255)})`;
  }

  function plotLine(p, px, py, xs, ys, col, sorted) {
    const [i0, i1] = visibleRange(xs, state.view.a, state.view.b);
    ctx.strokeStyle = col; ctx.lineWidth = 1.5; ctx.lineJoin = 'round';
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
        const x = Math.round(px(xs[i]));
        if (x !== curX) { flush(); curX = x; mn = mx = ys[i]; }
        else { if (ys[i] < mn) mn = ys[i]; if (ys[i] > mx) mx = ys[i]; }
      }
      flush();
    } else {
      for (let i = i0; i < i1; i++) {
        const x = px(xs[i]), y = py(ys[i]);
        if (i === i0) ctx.moveTo(x, y);
        else if (state.step) { ctx.lineTo(x, py(ys[i - 1])); ctx.lineTo(x, y); }
        else ctx.lineTo(x, y);
      }
    }
    ctx.stroke();
    if (state.points && !dense) {
      ctx.fillStyle = col;
      for (let i = i0; i < i1; i++) { ctx.beginPath(); ctx.arc(px(xs[i]), py(ys[i]), 2.2, 0, 6.3); ctx.fill(); }
    }
  }

  function drawOverlay(p, px) {
    state.selected.forEach((name) => {
      const s = state.byName[name];
      const [lo, hi] = yRange(name, s.t, s.v);
      const py = (v) => p.y + p.h - ((v - lo) / (hi - lo)) * p.h;
      plotLine(p, px, py, s.t, s.v, colorOf(name), true);
    });
  }

  function drawHover(panels) {
    const h = state.hover; const tip = $('tooltip');
    tip.hidden = true;
    if (!h || state.drag) return;
    const p = panels.find((q) => h.py >= q.y && h.py <= q.y + q.h && h.px >= q.x && h.px <= q.x + q.w);
    if (!p) return;
    const xv = state.view.a + ((h.px - p.x) / p.w) * (state.view.b - state.view.a);

    ctx.strokeStyle = cssVar('--text-muted'); ctx.setLineDash([3, 3]); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(h.px + .5, M.t); ctx.lineTo(h.px + .5, panels[panels.length - 1].y + panels[panels.length - 1].h); ctx.stroke();
    ctx.setLineDash([]);

    let rows = [], head = '';
    if (state.mode === 'xy') {
      const s = xySeries(p.name);
      let best = -1, bd = 1e18;
      for (let i = 0; i < s.xs.length; i++) {
        const sx = p.x + ((s.xs[i] - state.view.a) / (state.view.b - state.view.a)) * p.w;
        const sy = p._py(s.ys[i]);
        const d = (sx - h.px) ** 2 + (sy - h.py) ** 2;
        if (d < bd) { bd = d; best = i; }
      }
      if (best < 0 || bd > 30 * 30) return;
      head = `t = ${s.ts[best].toFixed(3)} s`;
      rows = [
        { c: colorOf(state.xName), t: `${state.xName}: ${fmt(s.xs[best])} ${unitOf(state.xName)}` },
        { c: colorOf(p.name), t: `${p.name}: ${fmt(s.ys[best])} ${unitOf(p.name)}` },
      ];
    } else {
      head = `t = ${xv.toFixed(3)} s`;
      const names = state.mode === 'overlay' ? state.selected : [p.name];
      rows = names.map((n) => {
        const s = state.byName[n]; const i = atOrBefore(s.t, xv);
        return { c: colorOf(n), t: `${n}: ${i < 0 ? '–' : fmt(s.v[i])} ${s.unit}` };
      });
    }
    tip.innerHTML = `<div class="text-muted">${head}</div>` +
      rows.map((r) => `<div class="row"><span class="dot" style="background:${r.c}"></span>${r.t}</div>`).join('');
    tip.hidden = false;
    const wrap = canvas.parentElement.getBoundingClientRect();
    const tw = tip.offsetWidth;
    tip.style.left = (h.px + 14 + tw > wrap.width ? h.px - tw - 14 : h.px + 14) + 'px';
    tip.style.top = Math.max(h.py - 10, 4) + 'px';
  }

  // draw y labels after lanes (outside clip)
  function draw() {
    drawPlot();
    if (!state.panels || !state.data || !state.selected.length) return;
    ctx.fillStyle = cssVar('--text-muted'); ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    state.panels.forEach((p) => {
      if (state.mode === 'overlay') {
        ctx.save(); ctx.fillStyle = cssVar('--text-muted'); ctx.textAlign = 'right';
        ctx.fillText('norm.', p.x - 8, p.y + 8); ctx.restore();
        let y = p.y + 26;
        state.selected.forEach((n) => { ctx.fillStyle = colorOf(n); ctx.fillText('● ' + n.slice(0, 9), p.x - 8, y); y += 14; });
        return;
      }
      ctx.fillStyle = cssVar('--text-muted');
      (p._yt || []).forEach((t) => ctx.fillText(fmt(t), p.x - 8, p._py(t)));
      ctx.fillStyle = colorOf(p.name); ctx.textAlign = 'left';
      ctx.fillText(`${p.name} [${unitOf(p.name)}]`, p.x + 8, p.y + 11);
      ctx.textAlign = 'right';
    });
  }

  // ---------- interaction ----------
  function plotX(e) { const r = canvas.getBoundingClientRect(); return { px: e.clientX - r.left, py: e.clientY - r.top }; }
  function xAt(px) { const p = state.panels && state.panels[0]; if (!p) return 0; return state.view.a + ((px - p.x) / p.w) * (state.view.b - state.view.a); }

  canvas.addEventListener('wheel', (e) => {
    if (!state.view) return; e.preventDefault();
    const { px } = plotX(e); const x = xAt(px);
    const k = e.deltaY > 0 ? 1.2 : 1 / 1.2;
    let a = x - (x - state.view.a) * k, b = x + (state.view.b - x) * k;
    const span = state.full.b - state.full.a;
    if (b - a > span) { a = state.full.a; b = state.full.b; }
    if (b - a < span * 1e-4) return;
    state.view = { a, b }; draw();
  }, { passive: false });

  canvas.addEventListener('mousedown', (e) => {
    const { px, py } = plotX(e);
    state.drag = { px, py, a: state.view.a, b: state.view.b, box: e.shiftKey, cur: px };
  });
  window.addEventListener('mousemove', (e) => {
    const pos = plotX(e);
    if (state.drag) {
      const d = state.drag; d.cur = pos.px;
      if (!d.box) {
        const p = state.panels[0]; const dx = (pos.px - d.px) / p.w * (d.b - d.a);
        state.view = { a: d.a - dx, b: d.b - dx };
      }
      draw();
      if (d.box) {
        const p = state.panels[0]; ctx.fillStyle = 'rgba(221,107,61,0.18)';
        ctx.fillRect(Math.min(d.px, d.cur), M.t, Math.abs(d.cur - d.px), canvas.clientHeight - M.t - M.b);
      }
    } else if (e.target === canvas) { state.hover = pos; draw(); }
  });
  window.addEventListener('mouseup', () => {
    const d = state.drag; if (!d) return;
    if (d.box && Math.abs(d.cur - d.px) > 4) {
      const a = xAt(Math.min(d.px, d.cur)), b = xAt(Math.max(d.px, d.cur));
      state.view = { a, b };
    }
    state.drag = null; draw();
  });
  canvas.addEventListener('mouseleave', () => { state.hover = null; draw(); });
  canvas.addEventListener('dblclick', () => { resetView(); draw(); });
  $('btn-reset-zoom').addEventListener('click', () => { resetView(); draw(); });
  window.addEventListener('resize', resize);
  new MutationObserver(draw).observe(document.documentElement, { attributes: true });
  new MutationObserver(draw).observe(document.body, { attributes: true });

  // ---------- sidebar & toolbar ----------
  function renderList() {
    const q = $('signal-filter').value.trim().toLowerCase();
    const ul = $('signal-list'); ul.innerHTML = '';
    const sigs = state.data ? state.data.signals : [];
    sigs.filter((s) => !q || s.name.toLowerCase().includes(q)).forEach((s) => {
      const li = document.createElement('li');
      const sel = state.selected.includes(s.name);
      li.className = sel ? 'selected' : '';
      const isX = state.mode === 'xy' && state.xName === s.name;
      li.innerHTML = `<span class="swatch" style="background:${sel ? colorOf(s.name) : 'transparent'}"></span>` +
        `<span class="name">${s.name}</span>${isX ? '<span class="xmark">X</span>' : ''}` +
        `<span class="meta">${s.unit || ''} · ${s.t.length}</span>`;
      li.title = `${s.cid || ''} · LID ${s.lid || '?'}`;
      li.addEventListener('click', () => toggle(s.name));
      ul.appendChild(li);
    });
    $('signal-count').textContent = `${state.selected.length} / ${sigs.length} selected`;
  }

  function renderXSelect() {
    const sel = $('select-x'); const prev = state.xName;
    sel.innerHTML = state.data.signals.map((s) => `<option value="${s.name}">${s.name} [${s.unit}]</option>`).join('');
    if (prev && state.byName[prev]) sel.value = prev; else if (sel.options.length) state.xName = sel.value;
  }

  function toggle(name) {
    const i = state.selected.indexOf(name);
    if (i >= 0) state.selected.splice(i, 1); else state.selected.push(name);
    renderList(); draw();
  }

  function setMode(mode) {
    state.mode = mode;
    document.querySelectorAll('.seg-btn').forEach((b) => b.classList.toggle('active', b.dataset.mode === mode));
    $('xy-controls').hidden = mode !== 'xy';
    resetView(); renderList(); draw();
  }
  document.querySelectorAll('.seg-btn').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.mode)));
  $('select-x').addEventListener('change', (e) => { state.xName = e.target.value; xyCache.clear(); resetView(); renderList(); draw(); });
  $('chk-points').addEventListener('change', (e) => { state.points = e.target.checked; draw(); });
  $('chk-step').addEventListener('change', (e) => { state.step = e.target.checked; draw(); });
  $('chk-xy-time').addEventListener('change', (e) => { state.colorByTime = e.target.checked; draw(); });
  $('signal-filter').addEventListener('input', renderList);
  $('btn-clear').addEventListener('click', () => { state.selected = []; renderList(); draw(); });

  // ---------- data ----------
  async function loadFile(name) {
    if (!name) return;
    try {
      const r = await fetch('/api/signals?file=' + encodeURIComponent(name));
      const d = await r.json();
      if (d.error) throw new Error(d.error);
      state.data = d; state.byName = {}; xyCache.clear();
      d.signals.forEach((s) => { state.byName[s.name] = s; });
      state.selected = d.signals.slice(0, 3).map((s) => s.name);
      state.xName = null; renderXSelect();
      resetView(); renderList(); resize();
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
