// JOLIA Docs – Vollbild-Ansicht für einzelne Dateien (Bild/PDF/Text), aus der Timeline heraus.

let fsFiles = [];       // { id, mime, contentType, date }
let fsIndex = -1;
const fsCache = new Map(); // fileId -> { kind: 'image'|'pdf'|'text', url?, text? }
let fsPlayTimer = null;

function isPreviewableMime(mime) {
    if (!mime) return false;
    return mime.startsWith('image/') || mime.startsWith('audio/') || mime.startsWith('video/')
        || mime === 'application/pdf' || mime === 'text/plain' || mime === 'text/markdown';
}

function fsKindForMime(mime) {
    if (mime.startsWith('image/')) return 'image';
    if (mime.startsWith('audio/')) return 'audio';
    if (mime.startsWith('video/')) return 'video';
    if (mime === 'application/pdf') return 'pdf';
    return 'text';
}

async function openFullscreenViewer(fileId) {
    const tiles = Array.from(document.querySelectorAll('.thumb-tile'));
    fsFiles = tiles.map(t => ({
        id: t.dataset.id,
        mime: t.dataset.mime || '',
        contentType: t.dataset.type || '',
        date: t.dataset.date || '',
    }));
    fsIndex = fsFiles.findIndex(f => f.id === fileId);
    if (fsIndex === -1) {
        // Aufruf ohne Timeline-Kacheln im DOM (z.B. Suche/Liste) - Mime-Type nachladen, nur die aktuelle Datei anzeigen.
        let mime = '';
        try {
            const meta = await fetch(`/api/files/${fileId}`).then(r => r.json());
            mime = meta.mime_type || '';
        } catch (e) {
            // Metadaten nicht verfügbar - Anzeige versucht es trotzdem als Text.
        }
        fsFiles = [{ id: fileId, mime, contentType: '', date: '' }];
        fsIndex = 0;
    }
    document.getElementById('file-fullscreen').style.display = 'flex';
    renderCurrent();
}

function closeFullscreenViewer() {
    stopFullscreenPlay();
    document.getElementById('file-fullscreen').style.display = 'none';
    for (const entry of fsCache.values()) {
        if (entry.url) URL.revokeObjectURL(entry.url);
    }
    fsCache.clear();
    fsFiles = [];
    fsIndex = -1;
}

async function loadFileContent(id, mime) {
    const kind = fsKindForMime(mime);
    if (kind === 'text') {
        const text = await fetch(`/api/files/${id}/download`).then(r => r.text());
        return { kind, text };
    }
    const blob = await fetch(`/api/files/${id}/download`).then(r => r.blob());
    return { kind, url: URL.createObjectURL(blob) };
}

async function ensureCached(id, mime) {
    if (fsCache.has(id)) return fsCache.get(id);
    const entry = await loadFileContent(id, mime);
    fsCache.set(id, entry);
    return entry;
}

function trimCache(keepIds) {
    for (const [id, entry] of fsCache.entries()) {
        if (!keepIds.includes(id)) {
            if (entry.url) URL.revokeObjectURL(entry.url);
            fsCache.delete(id);
        }
    }
}

function renderContentHtml(entry, name) {
    if (entry.kind === 'image') return `<img src="${entry.url}" alt="${escapeHtml(name || '')}">`;
    if (entry.kind === 'pdf') return `<iframe src="${entry.url}" title="${escapeHtml(name || '')}"></iframe>`;
    if (entry.kind === 'audio') return `<audio src="${entry.url}" controls autoplay></audio>`;
    if (entry.kind === 'video') return `<video src="${entry.url}" controls autoplay playsinline></video>`;
    return `<pre>${escapeHtml(entry.text || '')}</pre>`;
}

async function renderCurrent() {
    const content = document.getElementById('ff-content');
    const current = fsFiles[fsIndex];
    if (!current) return;
    content.innerHTML = '<p class="ff-loading">Lädt…</p>';
    try {
        const entry = await ensureCached(current.id, current.mime);
        content.innerHTML = renderContentHtml(entry, current.id);
    } catch (e) {
        content.innerHTML = '<p class="ff-error">Vorschau konnte nicht geladen werden.</p>';
    }
    const prevIdx = await findAdjacentSupported(-1);
    const nextIdx = await findAdjacentSupported(1);
    document.getElementById('ff-prev').style.display = prevIdx === -1 ? 'none' : '';
    document.getElementById('ff-next').style.display = nextIdx === -1 ? 'none' : '';
    if (nextIdx !== -1) prefetch(fsFiles[nextIdx]);
}

// Sucht ausgehend von fsIndex den naechsten/vorherigen darstellbaren Eintrag; laedt bei Bedarf
// weitere Kalendertage per API nach (robuste Navigation ueber die Grenzen geladener Tage hinaus).
async function findAdjacentSupported(dir) {
    let i = fsIndex + dir;
    while (true) {
        while (i >= 0 && i < fsFiles.length) {
            if (isPreviewableMime(fsFiles[i].mime)) return i;
            i += dir;
        }
        const added = await loadAdjacentDay(dir);
        if (!added) return -1;
        i = dir > 0 ? fsFiles.length - added.length : added.length - 1;
    }
}

// Laedt den naechsten/vorherigen Kalendertag (laut window.timelineDates) und haengt ihn an fsFiles
// an (hinten bei dir=+1, vorne bei dir=-1). Gibt die neu geladenen Eintraege zurueck, oder null,
// wenn keine weiteren Tage vorhanden sind.
async function loadAdjacentDay(dir) {
    const dates = window.timelineDates || [];
    if (dates.length === 0) return null;
    const boundaryDate = dir > 0
        ? (fsFiles.length ? fsFiles[fsFiles.length - 1].date : null)
        : (fsFiles.length ? fsFiles[0].date : null);
    let dateIdx = boundaryDate ? dates.indexOf(boundaryDate) : -1;
    let nextDateIdx = dateIdx === -1 ? (dir > 0 ? 0 : dates.length - 1) : dateIdx + dir;
    while (nextDateIdx >= 0 && nextDateIdx < dates.length) {
        const date = dates[nextDateIdx];
        const params = new URLSearchParams(window.timelineFilterParams ? window.timelineFilterParams.toString() : '');
        params.set('date', date);
        let data;
        try {
            data = await fetch(`/api/files/timeline/day?${params}`).then(r => r.json());
        } catch (e) {
            return null;
        }
        const existingIds = new Set(fsFiles.map(f => f.id));
        const newEntries = (data.files || [])
            .filter(f => !existingIds.has(f.id))
            .map(f => ({ id: f.id, mime: f.mime_type || '', contentType: f.content_type || '', date }));
        if (newEntries.length > 0) {
            if (dir > 0) {
                fsFiles = fsFiles.concat(newEntries);
            } else {
                fsFiles = newEntries.concat(fsFiles);
                fsIndex += newEntries.length;
            }
            return newEntries;
        }
        nextDateIdx += dir;
    }
    return null;
}

async function fullscreenNav(dir) {
    const idx = await findAdjacentSupported(dir);
    if (idx === -1) return false;
    fsIndex = idx;
    await renderCurrent();
    trimCache(fsFiles.slice(Math.max(0, fsIndex - 1), fsIndex + 2).map(f => f.id));
    return true;
}

async function prefetch(fileEntry) {
    if (fsCache.has(fileEntry.id)) return;
    try {
        fsCache.set(fileEntry.id, await loadFileContent(fileEntry.id, fileEntry.mime));
    } catch (e) {
        // Prefetch-Fehler ignorieren, wird bei tatsächlicher Navigation erneut versucht.
    }
}

function toggleFullscreenPlay() {
    if (fsPlayTimer) {
        stopFullscreenPlay();
        return;
    }
    document.getElementById('ff-play').classList.add('is-active');
    fsPlayTimer = setInterval(async () => {
        const advanced = await fullscreenNav(1);
        if (!advanced) stopFullscreenPlay();
    }, 8000);
}

function stopFullscreenPlay() {
    if (fsPlayTimer) {
        clearInterval(fsPlayTimer);
        fsPlayTimer = null;
    }
    const btn = document.getElementById('ff-play');
    if (btn) btn.classList.remove('is-active');
}

document.addEventListener('keydown', (evt) => {
    const viewer = document.getElementById('file-fullscreen');
    if (!viewer || viewer.style.display === 'none') return;
    if (evt.key === 'ArrowLeft') fullscreenNav(-1);
    else if (evt.key === 'ArrowRight') fullscreenNav(1);
});
