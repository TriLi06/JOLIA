// JOLIA Docs – Globale JavaScript-Hilfsfunktionen

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

/**
 * Globale Detail-Sidebar: öffnen/schließen (genutzt von Dateien- & Suche-Seite)
 */
async function openDetail(evt, fileId) {
    if (evt) evt.preventDefault();
    const sidebar = document.getElementById('file-sidebar');
    const overlay = document.getElementById('file-sidebar-overlay');
    const content = document.getElementById('file-sidebar-content');
    if (!sidebar || !overlay || !content) return false;
    content.innerHTML = '<p>Lade…</p>';
    sidebar.classList.add('open');
    overlay.style.display = 'block';
    const r = await fetch(`/files/${fileId}/panel`);
    content.innerHTML = await r.text();
    // Eingebettete <script>-Tags aus dem geladenen HTML manuell ausführen
    content.querySelectorAll('script').forEach(old => {
        const s = document.createElement('script');
        s.textContent = old.textContent;
        old.replaceWith(s);
    });
    return false;
}

function closeDetail() {
    const sidebar = document.getElementById('file-sidebar');
    const overlay = document.getElementById('file-sidebar-overlay');
    if (sidebar) sidebar.classList.remove('open');
    if (overlay) overlay.style.display = 'none';
}

// Sidebar-Breite per Ziehen am linken Rand anpassen (Breite wird gemerkt)
(function initSidebarResize() {
    const sidebar = document.getElementById('file-sidebar');
    const handle = document.getElementById('file-sidebar-resize-handle');
    if (!sidebar || !handle) return;
    const savedWidth = localStorage.getItem('fileSidebarWidth');
    if (savedWidth) sidebar.style.width = savedWidth + 'px';

    let dragging = false;
    let startX = 0;
    let startWidth = 0;

    handle.addEventListener('mousedown', (evt) => {
        dragging = true;
        startX = evt.clientX;
        startWidth = sidebar.getBoundingClientRect().width;
        document.body.style.userSelect = 'none';
        evt.preventDefault();
    });

    document.addEventListener('mousemove', (evt) => {
        if (!dragging) return;
        // Sidebar haengt rechts am Bildschirmrand, daher Breite = Startbreite minus Delta der Mausbewegung nach rechts
        const delta = evt.clientX - startX;
        const minWidth = 320;
        const maxWidth = window.innerWidth * 0.95;
        const newWidth = Math.min(maxWidth, Math.max(minWidth, startWidth - delta));
        sidebar.style.width = newWidth + 'px';
    });

    document.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        document.body.style.userSelect = '';
        localStorage.setItem('fileSidebarWidth', Math.round(sidebar.getBoundingClientRect().width));
    });
})();
