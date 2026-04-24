// Global utilities for AI Gateway frontend
// HTMX extension and shared helpers

// Auto-configure HTMX to send JSON
document.addEventListener('DOMContentLoaded', () => {
  document.body.addEventListener('htmx:configRequest', (e) => {
    if (e.detail.verb !== 'get') {
      e.detail.headers['Content-Type'] = 'application/json';
    }
  });
});
