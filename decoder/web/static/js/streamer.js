/**
 * MiniGauge CAN Log Replayer & UDP Streamer Frontend Controller
 */

(function () {
  'use strict';

  // DOM Elements
  const elLogSelect = document.getElementById('log-select');
  const btnReloadLogs = document.getElementById('btn-reload-logs');
  const elTargetHost = document.getElementById('target-host');
  const elTargetPort = document.getElementById('target-port');
  const btnApplyTarget = document.getElementById('btn-apply-target');

  const elStatusIndicator = document.getElementById('status-indicator');
  const txtStatusState = document.getElementById('txt-status-state');
  const txtSendRate = document.getElementById('txt-send-rate');

  const btnPlay = document.getElementById('btn-play');
  const playIcon = document.getElementById('play-icon');
  const btnStop = document.getElementById('btn-stop');
  const btnStepBack = document.getElementById('btn-step-back');
  const btnStepFwd = document.getElementById('btn-step-fwd');

  const scrubSlider = document.getElementById('scrub-slider');
  const scrubTooltip = document.getElementById('scrub-tooltip');
  const txtCurrentTime = document.getElementById('txt-current-time');
  const txtTotalDuration = document.getElementById('txt-total-duration');

  const speedButtons = document.querySelectorAll('.speed-btn');
  const chkLoop = document.getElementById('chk-loop');
  const chkFreeze = document.getElementById('chk-freeze');

  // Gauge Elements
  const speedGaugeBar = document.getElementById('speed-gauge-bar');
  const rpmGaugeBar = document.getElementById('rpm-gauge-bar');
  const valSpeedKph = document.getElementById('val-speed-kph');
  const valSpeedMph = document.getElementById('val-speed-mph');
  const valRpm = document.getElementById('val-rpm');
  const valGear = document.getElementById('val-gear');
  const badgeSpeedFreq = document.getElementById('badge-speed-freq');
  const badgeRpmFreq = document.getElementById('badge-rpm-freq');

  const valCoolantTemp = document.getElementById('val-coolant-temp');
  const valCoolantDuty = document.getElementById('val-coolant-duty');
  const coolantFillBar = document.getElementById('coolant-fill-bar');

  const valFuelPct = document.getElementById('val-fuel-pct');
  const valFuelOhm = document.getElementById('val-fuel-ohm');
  const valFuelStep = document.getElementById('val-fuel-step');
  const fuelFillBar = document.getElementById('fuel-fill-bar');

  const valMaskHex = document.getElementById('val-mask-hex');
  const telltalePills = document.querySelectorAll('.telltale-pill');

  // Inspector Elements
  const toggleInspector = document.getElementById('toggle-inspector');
  const inspectorContent = document.getElementById('inspector-content');
  const inspectorChevron = document.getElementById('inspector-chevron');
  const txtPacketsSent = document.getElementById('txt-packets-sent');
  const valPacketHex = document.getElementById('val-packet-hex');
  const fMagic = document.getElementById('f-magic');
  const fMask = document.getElementById('f-mask');
  const fSpeed = document.getElementById('f-speed');
  const fRpm = document.getElementById('f-rpm');
  const fCool = document.getElementById('f-cool');
  const fFuel = document.getElementById('f-fuel');
  const fChk = document.getElementById('f-chk');

  // Traces & Graph Cursor Elements
  const plotTraces = document.getElementById('plot-traces');
  const graphCursor = document.getElementById('graph-cursor');

  // SVG Circumference for radius 90: 2 * PI * 90 = 565.4866776
  const CIRCUMFERENCE = 2 * Math.PI * 90;

  const GEAR_MAP = {
    0: 'N', 1: '1', 2: '2', 3: '3', 4: '4', 5: '5', 6: '6', 14: '?', 15: 'R'
  };

  // State
  let isUserScrubbing = false;
  let pollTimer = null;
  let currentDuration = 0.0;
  let currentState = 'STOPPED';

  function formatTime(seconds) {
    if (isNaN(seconds) || seconds < 0) seconds = 0;
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const tenths = Math.floor((seconds % 1) * 10);
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${tenths}`;
  }

  async function postControl(action, payload = {}) {
    try {
      const resp = await fetch('/api/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, ...payload })
      });
      const data = await resp.json();
      if (!resp.ok) {
        if (window.toast) window.toast.error(data.error || 'Control failed');
      } else {
        updateUI(data);
      }
    } catch (err) {
      console.error('Control error:', err);
    }
  }

  async function fetchLogs() {
    try {
      const resp = await fetch('/api/logs');
      const logs = await resp.json();
      elLogSelect.innerHTML = '';

      if (!logs || logs.length === 0) {
        const opt = document.createElement('option');
        opt.textContent = 'No .bin logs found';
        elLogSelect.appendChild(opt);
        return;
      }

      logs.forEach(log => {
        const opt = document.createElement('option');
        opt.value = log.filename;
        const sizeMb = (log.size / (1024 * 1024)).toFixed(1);
        opt.textContent = `${log.filename} (${sizeMb} MB)`;
        if (log.is_initial) opt.selected = true;
        elLogSelect.appendChild(opt);
      });
    } catch (err) {
      console.error('Fetch logs error:', err);
    }
  }

  async function fetchStatus() {
    if (isUserScrubbing) return;
    try {
      const resp = await fetch('/api/status');
      if (resp.ok) {
        const data = await resp.json();
        updateUI(data);
      }
    } catch (err) {
      console.error('Fetch status error:', err);
    }
  }

  function updateUI(status) {
    if (!status) return;

    currentState = status.state;
    currentDuration = status.duration_s || 0.0;

    // Update play/pause button state
    if (status.state === 'PLAYING') {
      btnPlay.classList.add('is-playing');
      playIcon.textContent = '❚❚';
      elStatusIndicator.className = 'status-dot dot-playing';
    } else if (status.state === 'PAUSED') {
      btnPlay.classList.remove('is-playing');
      playIcon.textContent = '▶';
      elStatusIndicator.className = 'status-dot dot-paused';
    } else {
      btnPlay.classList.remove('is-playing');
      playIcon.textContent = '▶';
      elStatusIndicator.className = 'status-dot dot-stopped';
    }

    txtStatusState.textContent = status.state;
    txtSendRate.textContent = (status.send_rate_hz || 0).toFixed(1);

    // Scrub slider & timings
    if (!isUserScrubbing) {
      scrubSlider.max = currentDuration > 0 ? currentDuration : 100;
      scrubSlider.value = status.current_time_s || 0;
      txtCurrentTime.textContent = formatTime(status.current_time_s || 0);
      txtTotalDuration.textContent = formatTime(currentDuration);
    }

    // Speed buttons active state
    speedButtons.forEach(btn => {
      const spd = parseFloat(btn.dataset.speed);
      if (Math.abs(spd - status.playback_speed) < 0.01) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    chkLoop.checked = Boolean(status.loop_enabled);
    chkFreeze.checked = Boolean(status.freeze_on_pause);

    // Telemetry & Gauges
    const tel = status.telemetry || {};

    // 1. Speedometer
    const kph = tel.disp_kph || 0;
    const mph = tel.disp_mph || 0;
    valSpeedKph.textContent = Math.round(kph);
    valSpeedMph.textContent = Math.round(mph);
    badgeSpeedFreq.textContent = `${(tel.speed_freq || 0).toFixed(1)} Hz`;

    // Fraction of 270 km/h
    const speedFrac = Math.min(1.0, Math.max(0.0, kph / 270.0));
    speedGaugeBar.style.strokeDashoffset = CIRCUMFERENCE * (1.0 - speedFrac);

    // 2. Tachometer
    const rpm = tel.disp_rpm || 0;
    valRpm.textContent = Math.round(rpm);
    valGear.textContent = GEAR_MAP[tel.gear] || 'N';
    badgeRpmFreq.textContent = `${(tel.rpm_freq || 0).toFixed(1)} Hz`;

    // Fraction of 8000 RPM
    const rpmFrac = Math.min(1.0, Math.max(0.0, rpm / 8000.0));
    rpmGaugeBar.style.strokeDashoffset = CIRCUMFERENCE * (1.0 - rpmFrac);

    // 3. Secondary: Coolant
    const coolDegC = tel.disp_cool_degc || 70;
    valCoolantTemp.textContent = coolDegC.toFixed(0);
    valCoolantDuty.textContent = (tel.coolant_duty || 0).toFixed(1);
    // 70°C -> 0%, 130°C -> 100%
    const coolPct = Math.min(100, Math.max(0, ((coolDegC - 70) / (130 - 70)) * 100));
    coolantFillBar.style.width = `${coolPct}%`;

    // 4. Secondary: Fuel
    const fuelPct = tel.disp_fuel_pct || 100;
    valFuelPct.textContent = fuelPct.toFixed(0);
    valFuelOhm.textContent = (tel.fuel_ohm || 270.0).toFixed(1);
    valFuelStep.textContent = tel.fuel_step || 19;
    fuelFillBar.style.width = `${fuelPct}%`;

    // 5. Telltale Indicators
    const mask = tel.telltales_mask !== undefined ? tel.telltales_mask : 0xD940;
    valMaskHex.textContent = `MASK: 0x${mask.toString(16).toUpperCase().padStart(4, '0')}`;

    telltalePills.forEach(pill => {
      const bit = parseInt(pill.dataset.bit, 10);
      const isInv = pill.dataset.inv === 'true';
      const bitSet = (mask & (1 << bit)) !== 0;
      // Inverted pins (bits 8, 11, 12, 14): active when pin is LOW (bitSet === false)
      // Non-inverted pins: active when pin is HIGH (bitSet === true)
      const isActive = isInv ? !bitSet : bitSet;
      pill.classList.toggle('active', isActive);
    });

    // 6. Packet Inspector
    txtPacketsSent.textContent = (status.packets_sent || 0).toLocaleString();
    valPacketHex.textContent = status.last_packet_hex || '-- -- -- -- -- -- -- -- -- -- -- -- -- --';

    if (status.last_packet_fields) {
      const f = status.last_packet_fields;
      fMagic.textContent = f.magic || '0xAA 0x55';
      fMask.textContent = f.telltales_mask || '0xD940';
      fSpeed.textContent = f.speed_freq_x10 !== undefined ? f.speed_freq_x10 : 0;
      fRpm.textContent = f.rpm_freq_x10 !== undefined ? f.rpm_freq_x10 : 0;
      fCool.textContent = f.coolant_duty_x100 !== undefined ? f.coolant_duty_x100 : 0;
      fFuel.textContent = f.fuel_ohm_x10 !== undefined ? f.fuel_ohm_x10 : 2700;
      fChk.textContent = f.checksum || '0x0000';
    }

    // 7. Graph cursor update
    updateGraphCursor(status.current_time_s || 0);
  }

  /**
   * Loads time-series traces (Speed & RPM) from /api/traces and renders them via Plotly
   */
  async function loadTraces() {
    if (!plotTraces || typeof Plotly === 'undefined') return;
    try {
      const resp = await fetch('/api/traces');
      if (!resp.ok) return;
      const data = await resp.json();

      if (!data.times || data.times.length === 0) {
        Plotly.purge(plotTraces);
        return;
      }

      const isLight = document.documentElement.getAttribute('data-theme') === 'light';
      const theme = window.PlotlyTheme ? window.PlotlyTheme.getPlotlyTheme(isLight) : {};

      const traceSpeed = {
        x: data.times,
        y: data.speeds,
        name: 'Speed',
        type: 'scatter',
        mode: 'lines',
        line: { color: '#00f0ff', width: 1.8 },
        yaxis: 'y1',
        hovertemplate: '%{y:.1f} km/h<extra></extra>',
      };

      const traceRpm = {
        x: data.times,
        y: data.rpms,
        name: 'RPM',
        type: 'scatter',
        mode: 'lines',
        line: { color: '#00ff66', width: 1.5 },
        yaxis: 'y2',
        hovertemplate: '%{y:.0f} RPM<extra></extra>',
      };

      const layout = {
        ...theme,
        margin: { l: 45, r: 45, t: 10, b: 24 },
        showlegend: false,
        hovermode: 'x unified',
        dragmode: false,
        xaxis: {
          ...theme.xaxis,
          title: { text: '' },
          showspikes: false,
          range: [0, data.duration_s || 1],
          tickformat: '.1f',
          ticksuffix: 's',
        },
        yaxis: {
          ...theme.yaxis,
          title: { text: 'km/h', font: { color: '#00f0ff', size: 10 } },
          tickfont: { color: '#00f0ff', size: 10 },
          rangemode: 'tozero',
        },
        yaxis2: {
          title: { text: 'RPM', font: { color: '#00ff66', size: 10 } },
          tickfont: { color: '#00ff66', size: 10 },
          overlaying: 'y',
          side: 'right',
          gridcolor: 'transparent',
          zerolinecolor: 'transparent',
          rangemode: 'tozero',
        },
      };

      const config = {
        responsive: true,
        displayModeBar: false,
        scrollZoom: false,
      };

      await Plotly.react(plotTraces, [traceSpeed, traceRpm], layout, config);
    } catch (err) {
      console.error('Failed to load telemetry traces:', err);
    }
  }

  /**
   * Updates horizontal position of the vertical tracking cursor on the Plotly graph
   */
  function updateGraphCursor(currentTime) {
    if (!plotTraces || !graphCursor || !plotTraces._fullLayout || !plotTraces._fullLayout.xaxis) {
      if (graphCursor) graphCursor.style.display = 'none';
      return;
    }
    const xaxis = plotTraces._fullLayout.xaxis;
    if (!xaxis._length || isNaN(currentTime)) {
      graphCursor.style.display = 'none';
      return;
    }
    const p = xaxis.d2p(currentTime);
    if (isNaN(p) || p < 0 || p > xaxis._length) {
      graphCursor.style.display = 'none';
      return;
    }
    const leftPx = xaxis._offset + p;
    const topPx = plotTraces._fullLayout.margin.t;
    const heightPx = plotTraces._fullLayout._size.h;

    graphCursor.style.display = 'block';
    graphCursor.style.left = `${leftPx}px`;
    graphCursor.style.top = `${topPx}px`;
    graphCursor.style.height = `${heightPx}px`;
  }


  // Setup Event Handlers
  function initEvents() {
    // Play/Pause
    btnPlay.addEventListener('click', () => {
      if (currentState === 'PLAYING') {
        postControl('pause');
      } else {
        postControl('play');
      }
    });

    // Stop
    btnStop.addEventListener('click', () => {
      postControl('stop');
    });

    // Step +/- 1s
    btnStepBack.addEventListener('click', () => {
      const target = Math.max(0, scrubSlider.value - 1.0);
      postControl('seek', { target_s: target });
    });

    btnStepFwd.addEventListener('click', () => {
      const target = Math.min(currentDuration, parseFloat(scrubSlider.value) + 1.0);
      postControl('seek', { target_s: target });
    });

    // Scrub slider dragging
    scrubSlider.addEventListener('mousedown', () => { isUserScrubbing = true; });
    scrubSlider.addEventListener('touchstart', () => { isUserScrubbing = true; }, { passive: true });

    scrubSlider.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value);
      txtCurrentTime.textContent = formatTime(val);
    });

    scrubSlider.addEventListener('change', (e) => {
      isUserScrubbing = false;
      const target = parseFloat(e.target.value);
      postControl('seek', { target_s: target });
    });

    // Scrub tooltip
    scrubSlider.addEventListener('mousemove', (e) => {
      const rect = scrubSlider.getBoundingClientRect();
      const pos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      const previewTime = pos * currentDuration;
      scrubTooltip.style.left = `${pos * 100}%`;
      scrubTooltip.textContent = formatTime(previewTime);
      scrubTooltip.style.display = 'block';
    });

    scrubSlider.addEventListener('mouseleave', () => {
      scrubTooltip.style.display = 'none';
    });

    // Speed buttons
    speedButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const speed = parseFloat(btn.dataset.speed);
        postControl('set_speed', { speed });
      });
    });

    // Loop & Freeze toggles
    chkLoop.addEventListener('change', () => {
      postControl('set_loop', { loop: chkLoop.checked });
    });

    chkFreeze.addEventListener('change', () => {
      postControl('set_freeze', { freeze: chkFreeze.checked });
    });

    // Target endpoint apply
    btnApplyTarget.addEventListener('click', () => {
      const host = elTargetHost.value.trim();
      const port = parseInt(elTargetPort.value, 10);
      if (!host || isNaN(port)) {
        if (window.toast) window.toast.error('Invalid host or port');
        return;
      }
      postControl('set_target', { host, port });
      if (window.toast) window.toast.success(`Target updated: ${host}:${port}`);
    });

    // Log selection
    elLogSelect.addEventListener('change', async () => {
      const filename = elLogSelect.value;
      if (filename) {
        await postControl('load', { filename });
        await loadTraces();
      }
    });

    btnReloadLogs.addEventListener('click', async () => {
      await fetchLogs();
      await loadTraces();
    });

    // Plot click to seek
    if (plotTraces) {
      plotTraces.addEventListener('click', (e) => {
        if (!plotTraces._fullLayout || !plotTraces._fullLayout.xaxis) return;
        const xaxis = plotTraces._fullLayout.xaxis;
        const rect = plotTraces.getBoundingClientRect();
        const relX = e.clientX - rect.left;
        if (relX >= xaxis._offset && relX <= xaxis._offset + xaxis._length) {
          const t = xaxis.p2d(relX - xaxis._offset);
          if (!isNaN(t) && t >= 0 && t <= currentDuration) {
            postControl('seek', { target_s: Math.max(0, Math.min(currentDuration, t)) });
          }
        }
      });
    }

    // Collapsible Inspector
    toggleInspector.addEventListener('click', () => {
      const isHidden = inspectorContent.style.display === 'none';
      inspectorContent.style.display = isHidden ? 'flex' : 'none';
      inspectorChevron.textContent = isHidden ? '▼' : '►';
    });

    // Keyboard shortcuts
    window.addEventListener('keydown', (e) => {
      // Don't intercept when typing in inputs
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

      if (e.code === 'Space') {
        e.preventDefault();
        btnPlay.click();
      } else if (e.code === 'Escape') {
        e.preventDefault();
        btnStop.click();
      } else if (e.code === 'ArrowLeft') {
        e.preventDefault();
        const step = e.shiftKey ? 5.0 : 1.0;
        const target = Math.max(0, parseFloat(scrubSlider.value) - step);
        postControl('seek', { target_s: target });
      } else if (e.code === 'ArrowRight') {
        e.preventDefault();
        const step = e.shiftKey ? 5.0 : 1.0;
        const target = Math.min(currentDuration, parseFloat(scrubSlider.value) + step);
        postControl('seek', { target_s: target });
      } else if (e.key === 'l' || e.key === 'L') {
        chkLoop.checked = !chkLoop.checked;
        chkLoop.dispatchEvent(new Event('change'));
      }
    });
  }

  // Initialize
  async function init() {
    // Initial SVG stroke-dasharray
    if (speedGaugeBar) speedGaugeBar.style.strokeDasharray = CIRCUMFERENCE;
    if (rpmGaugeBar) rpmGaugeBar.style.strokeDasharray = CIRCUMFERENCE;

    if (window.PlotlyTheme) {
      window.PlotlyTheme.setupAutoResize('plot-traces');
    }

    await fetchLogs();
    await fetchStatus();
    await loadTraces();
    initEvents();

    // Start 100ms status polling loop
    pollTimer = setInterval(fetchStatus, 100);
  }

  window.addEventListener('DOMContentLoaded', init);
})();
