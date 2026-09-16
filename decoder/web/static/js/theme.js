/**
 * MiniGauge Unified Theme & UI Controls Manager
 * Conforms to REQ-SYS-004:
 *   - Unified 3-state system: Auto (follows OS) -> Light -> Dark -> Auto
 *   - Auto-detects OS color scheme (prefers-color-scheme: light)
 *   - Live reactive updates when OS switches in Auto mode
 *   - Manual override persisted in localStorage ('minigauge_theme_pref')
 *   - Sets data-theme attribute on <html> and theme-light/theme-dark classes on <body>
 *   - Synchronizes #btnThemeToggle, #btn-theme-toggle, and #btn-theme controls
 *   - Automatically updates and binds input[type="range"] dual-color slider tracks
 *   - Dispatches 'minigauge-theme-changed' custom event
 */

(function () {
  const PREF_KEY = 'minigauge_theme_pref';

  function getSystemPreference() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches
      ? 'light'
      : 'dark';
  }

  function getSavedPreference() {
    return (
      localStorage.getItem(PREF_KEY) ||
      localStorage.getItem('minigauge-theme') ||
      localStorage.getItem('minigauge_theme') ||
      'auto'
    );
  }

  function getEffectiveTheme(pref) {
    const p = pref || getSavedPreference();
    if (p === 'light') return 'light';
    if (p === 'dark') return 'dark';
    return getSystemPreference();
  }

  function updateSliderTrack(slider) {
    if (!slider || slider.type !== 'range') return;
    const min = parseFloat(slider.min) !== undefined && !isNaN(parseFloat(slider.min)) ? parseFloat(slider.min) : 0;
    const max = parseFloat(slider.max) !== undefined && !isNaN(parseFloat(slider.max)) ? parseFloat(slider.max) : 100;
    const val = parseFloat(slider.value) !== undefined && !isNaN(parseFloat(slider.value)) ? parseFloat(slider.value) : 0;
    const range = max - min;
    const ratio = range === 0 ? 0 : Math.max(0, Math.min(1, (val - min) / range));
    const pct = ratio * 100;
    // Standard 18px thumb inside 1px borders has center travel from 10px to (width - 10px).
    // The exact sub-pixel center offset is: (10px - 20px * ratio)
    const offsetPx = (10 - 20 * ratio).toFixed(2);
    const fillVal = `calc(${pct.toFixed(2)}% + ${offsetPx}px)`;
    slider.style.setProperty('--slider-fill', fillVal);
    slider.style.setProperty('--slider-ratio', ratio.toFixed(4));
    slider.style.setProperty('--slider-pct', `${pct.toFixed(2)}%`);
  }

  function initAllSliders() {
    document.querySelectorAll('input[type="range"]').forEach((slider) => {
      updateSliderTrack(slider);
      if (!slider._hasSliderTrackBound) {
        slider.addEventListener('input', () => updateSliderTrack(slider));
        slider.addEventListener('change', () => updateSliderTrack(slider));
        slider._hasSliderTrackBound = true;
      }
    });
  }

  function applyTheme(pref) {
    const preference = pref || getSavedPreference();
    localStorage.setItem(PREF_KEY, preference);

    const effective = getEffectiveTheme(preference);
    const isLight = effective === 'light';

    document.documentElement.setAttribute('data-theme', effective);
    if (document.body) {
      document.body.classList.toggle('theme-light', isLight);
      document.body.classList.toggle('theme-dark', !isLight);
    }

    // Update all theme toggle buttons across tools
    const buttons = document.querySelectorAll('#btnThemeToggle, #btn-theme-toggle, #btn-theme, [data-role="theme-toggle"]');
    buttons.forEach((btn) => {
      let icon = btn.querySelector('#themeIcon, .theme-icon');
      let label = btn.querySelector('#themeLabel, .theme-label');

      if (!icon && !label) {
        btn.innerHTML = '<span class="theme-icon"></span><span class="theme-label"></span>';
        icon = btn.querySelector('.theme-icon');
        label = btn.querySelector('.theme-label');
      }

      if (preference === 'auto') {
        if (icon) icon.textContent = '🌓';
        if (label) label.textContent = 'Auto';
        btn.title = `Theme: Auto (${effective} active). Click to toggle Light / Dark / Auto.`;
      } else if (preference === 'light') {
        if (icon) icon.textContent = '☀️';
        if (label) label.textContent = 'Light';
        btn.title = 'Theme: Light. Click to toggle Light / Dark / Auto.';
      } else {
        if (icon) icon.textContent = '🌙';
        if (label) label.textContent = 'Dark';
        btn.title = 'Theme: Dark. Click to toggle Light / Dark / Auto.';
      }
    });

    // Refresh dynamic slider track colors
    initAllSliders();

    // Dispatch global custom event for Plotly, Leaflet, and custom charts
    window.dispatchEvent(
      new CustomEvent('minigauge-theme-changed', {
        detail: {
          theme: effective,
          preference,
          isLight,
          isDark: !isLight,
        },
      })
    );
  }

  function cycleTheme() {
    const current = getSavedPreference();
    let next = 'auto';
    if (current === 'auto') next = 'light';
    else if (current === 'light') next = 'dark';
    else next = 'auto';

    applyTheme(next);
    return next;
  }

  // OS color scheme listener (reactive when in auto mode)
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
      if (getSavedPreference() === 'auto') {
        applyTheme('auto');
      }
    });
  }

  // Initial theme application
  const initialPref = getSavedPreference();
  const initialEffective = getEffectiveTheme(initialPref);
  document.documentElement.setAttribute('data-theme', initialEffective);

  function setup() {
    applyTheme(initialPref);

    // Auto-attach click listeners to theme buttons
    const buttons = document.querySelectorAll('#btnThemeToggle, #btn-theme-toggle, #btn-theme, [data-role="theme-toggle"]');
    buttons.forEach((btn) => {
      if (!btn._hasThemeClickListener) {
        btn.addEventListener('click', (e) => {
          e.preventDefault();
          cycleTheme();
        });
        btn._hasThemeClickListener = true;
      }
    });

    initAllSliders();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setup);
  } else {
    setup();
  }

  // Global exports
  window.ThemeManager = {
    getPreference: getSavedPreference,
    getEffectiveTheme: () => getEffectiveTheme(),
    setTheme: (pref) => applyTheme(pref),
    cycleTheme,
    toggleTheme: cycleTheme,
    isLight: () => getEffectiveTheme() === 'light',
    isDark: () => getEffectiveTheme() === 'dark',
  };

  window.updateSliderTrack = updateSliderTrack;
  window.initAllSliders = initAllSliders;
})();
