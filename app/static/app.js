// DocStoreAI – Globale JavaScript-Hilfsfunktionen

/**
 * Flash-Nachricht anzeigen
 */
function showFlash(message, duration = 3000) {
    const el = document.getElementById('flash-message');
    if (!el) return;
    el.textContent = message;
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, duration);
}

/**
 * HTML-Sonderzeichen escapen
 */
function escapeHtml(text) {
    if (!text) return '';
    const d = document.createElement('div');
    d.appendChild(document.createTextNode(text));
    return d.innerHTML;
}

/**
 * Bytes in lesbare Größe umwandeln
 */
function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

/**
 * Aktiven Navigationslink hervorheben
 */
(function highlightActiveNav() {
    const path = window.location.pathname.split('/')[1];
    document.querySelectorAll('nav a').forEach(link => {
        const href = link.getAttribute('href') || '';
        if (href === '/' + path || (path === 'dashboard' && href === '/dashboard')) {
            link.setAttribute('aria-current', 'page');
        }
    });
})();
