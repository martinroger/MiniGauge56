/**
 * MiniGauge Plotly Chart Theme & Responsiveness Utilities
 */

(function () {
  function getPlotlyTheme(isLight) {
    return {
      paper_bgcolor: 'transparent',
      plot_bgcolor: 'transparent',
      font: {
        family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        color: isLight ? '#0f172a' : '#f5f5f5',
        size: 11,
      },
      xaxis: {
        gridcolor: isLight ? 'rgba(0,0,0,0.07)' : 'rgba(255,255,255,0.07)',
        zerolinecolor: isLight ? 'rgba(0,0,0,0.15)' : 'rgba(255,255,255,0.15)',
        tickcolor: isLight ? '#64748b' : '#9ca3af',
      },
      yaxis: {
        gridcolor: isLight ? 'rgba(0,0,0,0.07)' : 'rgba(255,255,255,0.07)',
        zerolinecolor: isLight ? 'rgba(0,0,0,0.15)' : 'rgba(255,255,255,0.15)',
        tickcolor: isLight ? '#64748b' : '#9ca3af',
      },
    };
  }

  function setupAutoResize(plotDivIds) {
    if (typeof Plotly === 'undefined') return;
    const ids = Array.isArray(plotDivIds) ? plotDivIds : [plotDivIds];

    window.addEventListener('resize', () => {
      ids.forEach((id) => {
        const el = document.getElementById(id);
        if (el && el.data) {
          Plotly.Plots.resize(el);
        }
      });
    });
  }

  window.PlotlyTheme = {
    getPlotlyTheme,
    setupAutoResize,
  };
})();

