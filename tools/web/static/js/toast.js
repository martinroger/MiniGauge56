/**
 * MiniGauge Global Toast Notification Utility
 */

(function () {
  let toastContainer = null;

  function ensureContainer() {
    if (!toastContainer || !document.body.contains(toastContainer)) {
      toastContainer = document.getElementById('toast');
      if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = 'toast';
        document.body.appendChild(toastContainer);
      }
    }
    return toastContainer;
  }

  function show(message, duration = 3200, type = 'info') {
    const container = ensureContainer();
    const item = document.createElement('div');
    item.className = `toast-msg toast-${type}`;
    item.innerHTML = message;
    container.appendChild(item);

    setTimeout(() => {
      item.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
      item.style.opacity = '0';
      item.style.transform = 'translateY(10px)';
      setTimeout(() => {
        if (item.parentNode) {
          item.parentNode.removeChild(item);
        }
      }, 300);
    }, duration);
  }

  window.Toast = {
    show,
    success: (msg, dur) => show(`✓ ${msg}`, dur, 'success'),
    error: (msg, dur) => show(`⚠️ ${msg}`, dur, 'error'),
    info: (msg, dur) => show(`ℹ️ ${msg}`, dur, 'info'),
  };
})();

