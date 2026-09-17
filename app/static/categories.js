// JOLIA Docs - Kategorien-Arbeitsbereich

let categoriesCache = [];
let selectedCategoryId = null;
let selectedFileIds = new Set();
let expandedCategoryIds = new Set();
let categoryFilter = '';
let currentFiles = [];
let draggedCategoryId = null;
let categoryEditOpenId = null;

const categoryTree = document.getElementById('category-tree');
const categoryResult = document.getElementById('category-edit-result');
const filesList = document.getElementById('category-files-list');

async function requestJson(url, options = {}) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Fehler bei der Kategorienverwaltung.');
    return data;
}

function categoryById(categoryId) {
    return categoriesCache.find(category => category.id === categoryId);
}

function categoryChildren(parentId) {
    return categoriesCache.filter(category => category.parent_id === parentId)
        .sort((first, second) => first.name.localeCompare(second.name));
}

function categoryPath(categoryId) {
    const segments = [];
    let category = categoryById(categoryId);
    while (category) {
        segments.unshift(category.name);
        category = category.parent_id ? categoryById(category.parent_id) : null;
    }
    return segments.join(' > ');
}

function descendantIds(categoryId) {
    const result = new Set([categoryId]);
    let changed = true;
    while (changed) {
        changed = false;
        categoriesCache.forEach(category => {
            if (category.parent_id && result.has(category.parent_id) && !result.has(category.id)) {
                result.add(category.id);
                changed = true;
            }
        });
    }
    return result;
}

function expandAncestors(categoryId) {
    let category = categoryById(categoryId);
    while (category && category.parent_id) {
        expandedCategoryIds.add(category.parent_id);
        category = categoryById(category.parent_id);
    }
}

function matchesFilter(category) {
    return !categoryFilter || categoryPath(category.id).toLocaleLowerCase().includes(categoryFilter);
}

function hasMatchingDescendant(categoryId) {
    return categoriesCache.some(category => category.parent_id === categoryId
        && (matchesFilter(category) || hasMatchingDescendant(category.id)));
}

function showError(error) {
    categoryResult.textContent = error.message || 'Aktion konnte nicht ausgeführt werden.';
    categoryResult.className = 'error';
}

function clearMessage() {
    categoryResult.textContent = '';
    categoryResult.className = '';
}

async function loadCategories() {
    try {
        const data = await requestJson('/api/categories');
        categoriesCache = data.items || [];
        if (selectedCategoryId && !categoryById(selectedCategoryId)) selectedCategoryId = null;
        if (categoryEditOpenId && !categoryById(categoryEditOpenId)) categoryEditOpenId = null;
        if (selectedCategoryId) expandAncestors(selectedCategoryId);
        renderCategoryTree();
    } catch (error) {
        categoryTree.innerHTML = '<small class="error">Kategorien konnten nicht geladen werden.</small>';
    }
}

function renderCategoryTree() {
    if (!categoriesCache.length) {
        categoryTree.innerHTML = '<small>Noch keine Kategorien angelegt.</small>';
        return;
    }
    categoryTree.innerHTML = renderCategoryNodes(null);
}

function renderCategoryNodes(parentId) {
    const categories = categoryChildren(parentId).filter(category => matchesFilter(category)
        || hasMatchingDescendant(category.id));
    if (!categories.length) return '';
    return `<ul class="category-tree-list">${categories.map(category => {
        const children = categoryChildren(category.id);
        const visibleChildren = children.some(child => matchesFilter(child) || hasMatchingDescendant(child.id));
        const expanded = Boolean(categoryFilter) || expandedCategoryIds.has(category.id);
        const isSelected = category.id === selectedCategoryId;
        return `<li class="category-tree-item ${isSelected ? 'is-selected' : ''}"
            data-category-id="${category.id}" draggable="true">
            <div class="category-tree-row">
                ${children.length ? `<button class="category-expander" type="button" data-expand-category="${category.id}" aria-label="${expanded ? 'Unterkategorien einklappen' : 'Unterkategorien ausklappen'}">${expanded ? '-' : '+'}</button>` : '<span class="category-expander-spacer"></span>'}
                <button class="category-tree-select" type="button" data-select-category="${category.id}">${escapeHtml(category.name)}</button>
                <span class="category-tree-count">${category.count}</span>
                ${isSelected ? `<button class="category-edit-toggle" type="button" data-edit-category="${category.id}" title="Kategorie bearbeiten" aria-label="Kategorie bearbeiten">&#9998;</button>` : ''}
            </div>
            ${isSelected && categoryEditOpenId === category.id ? renderCategoryInlineActions(category) : ''}
            ${expanded && visibleChildren ? renderCategoryNodes(category.id) : ''}
        </li>`;
    }).join('')}</ul>`;
}

function categoryMoveOptions(categoryId) {
    const category = categoryById(categoryId);
    const blocked = descendantIds(categoryId);
    const options = categoriesCache.filter(item => !blocked.has(item.id))
        .sort((first, second) => categoryPath(first.id).localeCompare(categoryPath(second.id)));
    return '<option value="">Wurzelebene</option>' + options.map(item =>
        `<option value="${item.id}" ${category.parent_id === item.id ? 'selected' : ''}>${escapeHtml(categoryPath(item.id))}</option>`
    ).join('');
}

function renderCategoryInlineActions(category) {
    return `<div class="category-inline-actions" data-category-actions="${category.id}">
        <button class="outline secondary" type="button" data-add-child-category="${category.id}">Unterkategorie</button>
        <button class="outline secondary" type="button" data-rename-category="${category.id}">Umbenennen</button>
        <label>Verschieben nach
            <select data-category-move-target="${category.id}">${categoryMoveOptions(category.id)}</select>
        </label>
        <button class="outline secondary" type="button" data-move-category="${category.id}">Verschieben</button>
        <button class="outline secondary" type="button" data-delete-category="${category.id}">Ebene auflösen</button>
    </div>`;
}

function populateFileMoveSelect() {
    const select = document.getElementById('category-file-move-target');
    select.innerHTML = '<option value="">Zielkategorie auswählen</option>' + [...categoriesCache]
        .sort((first, second) => categoryPath(first.id).localeCompare(categoryPath(second.id)))
        .map(category => `<option value="${category.id}">${escapeHtml(categoryPath(category.id))}</option>`).join('');
}

async function selectCategory(categoryId) {
    selectedCategoryId = categoryId;
    selectedFileIds.clear();
    categoryEditOpenId = null;
    expandAncestors(categoryId);
    renderCategoryTree();
    populateFileMoveSelect();
    await loadCategoryFiles();
}

async function loadCategoryFiles() {
    const title = document.getElementById('category-files-title');
    const subtitle = document.getElementById('category-files-subtitle');
    if (!selectedCategoryId) {
        title.textContent = 'Kategorie auswählen';
        subtitle.textContent = '';
        filesList.innerHTML = '<small>Bitte eine Kategorie auswählen…</small>';
        return;
    }
    title.textContent = categoryPath(selectedCategoryId);
    subtitle.textContent = 'Direkt zugeordnete Dateien';
    filesList.innerHTML = '<small>Lädt…</small>';
    try {
        const data = await requestJson(`/api/categories/${selectedCategoryId}/files?include_subtree=false&limit=500`);
        currentFiles = data.items || [];
        renderCategoryFiles();
    } catch (error) {
        filesList.innerHTML = '<small class="error">Dateien konnten nicht geladen werden.</small>';
    }
}

function updateFileActions() {
    const actions = document.getElementById('category-file-actions');
    actions.hidden = selectedFileIds.size === 0;
    document.getElementById('category-file-selection-count').textContent = `${selectedFileIds.size} ausgewählt`;
}

function renderCategoryFiles() {
    document.getElementById('category-files-subtitle').textContent = `${currentFiles.length} direkte Datei${currentFiles.length === 1 ? '' : 'en'}`;
    if (!currentFiles.length) {
        filesList.innerHTML = '<small>Keine direkt zugeordneten Dateien in dieser Kategorie.</small>';
        updateFileActions();
        return;
    }
    const icons = { documents: 'Dokument', audio: 'Audio', video: 'Video', images: 'Bild' };
    filesList.innerHTML = currentFiles.map(file => `<div class="category-file-row" data-file-id="${file.id}" draggable="true">
        <input type="checkbox" class="category-file-select" data-select-file="${file.id}" ${selectedFileIds.has(file.id) ? 'checked' : ''} aria-label="${escapeHtml(file.original_filename)} auswählen">
        <span class="category-file-icon">${file.thumbnail_path ? `<img src="/api/files/${file.id}/thumbnail" alt="" loading="lazy">` : escapeHtml(icons[file.content_type] || 'Datei')}</span>
        <button class="category-file-name" type="button" data-open-file="${file.id}">${escapeHtml(file.original_filename)}</button>
        ${file.category_needs_review ? '<span class="status-badge status-needs_review">Review</span>' : ''}
        <span class="status-badge status-${file.status}">${escapeHtml(file.status)}</span>
    </div>`).join('');
    updateFileActions();
}

async function createCategory(parentId = selectedCategoryId) {
    const name = window.prompt('Name der neuen Kategorie:');
    if (!name || !name.trim()) return;
    try {
        const category = await requestJson('/api/categories', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name.trim(), parent_id: parentId }),
        });
        if (parentId) expandedCategoryIds.add(parentId);
        clearMessage();
        await loadCategories();
        await selectCategory(category.id);
    } catch (error) {
        showError(error);
    }
}

function startRename(categoryId) {
    const category = categoryById(categoryId);
    const button = document.querySelector(`[data-select-category="${categoryId}"]`);
    if (!category || !button) return;
    const input = document.createElement('input');
    input.type = 'text';
    input.value = category.name;
    input.className = 'category-rename-input';
    button.replaceWith(input);
    input.focus();
    input.select();
    let finished = false;
    const finish = async save => {
        if (finished) return;
        finished = true;
        if (!save || !input.value.trim() || input.value.trim() === category.name) {
            renderCategoryTree();
            return;
        }
        try {
            await requestJson(`/api/categories/${categoryId}`, {
                method: 'PUT', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: input.value.trim() }),
            });
            clearMessage();
            await loadCategories();
            await loadCategoryFiles();
        } catch (error) {
            showError(error);
            renderCategoryTree();
        }
    };
    input.addEventListener('keydown', event => {
        if (event.key === 'Enter') finish(true);
        if (event.key === 'Escape') finish(false);
    });
    input.addEventListener('blur', () => finish(true));
}

async function moveCategory(categoryId, parentId) {
    if (categoryId === parentId || (parentId && descendantIds(categoryId).has(parentId))) return;
    try {
        await requestJson(`/api/categories/${categoryId}/move`, {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ parent_id: parentId }),
        });
        if (parentId) expandedCategoryIds.add(parentId);
        clearMessage();
        await loadCategories();
    } catch (error) {
        showError(error);
    }
}

async function assignFiles(fileIds, categoryId) {
    if (!fileIds.length) return;
    try {
        await requestJson('/api/categories/files/assign', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_ids: fileIds, category_id: categoryId }),
        });
        selectedFileIds.clear();
        clearMessage();
        await loadCategories();
        await loadCategoryFiles();
    } catch (error) {
        showError(error);
    }
}

function openDeleteDialog() {
    const category = categoryById(selectedCategoryId);
    if (!category) return;
    const childCount = categoryChildren(category.id).length;
    const destination = category.parent_id ? categoryPath(category.parent_id) : 'die Wurzelebene bzw. ohne Kategorie';
    document.getElementById('category-delete-description').textContent = `${currentFiles.length} direkte Dateien und ${childCount} Unterkategorien werden nach ${destination} verschoben.`;
    document.getElementById('category-delete-dialog').showModal();
}

async function deleteSelectedCategory() {
    await deleteCategory(false);
}

async function deleteCategory(dissolveSubtree) {
    const category = categoryById(selectedCategoryId);
    if (!category) return;
    try {
        const mode = dissolveSubtree ? 'dissolve_subtree=true' : 'reassign_to_parent=true';
        await requestJson(`/api/categories/${category.id}?${mode}`, { method: 'DELETE' });
        selectedCategoryId = category.parent_id;
        selectedFileIds.clear();
        document.getElementById('category-delete-dialog').close();
        clearMessage();
        await loadCategories();
        await loadCategoryFiles();
    } catch (error) {
        showError(error);
    }
}

document.getElementById('category-filter').addEventListener('input', event => {
    categoryFilter = event.target.value.trim().toLocaleLowerCase();
    renderCategoryTree();
});
document.getElementById('category-add-root-btn').addEventListener('click', () => createCategory(null));
document.getElementById('category-delete-cancel-btn').addEventListener('click', () => document.getElementById('category-delete-dialog').close());
document.getElementById('category-delete-confirm-btn').addEventListener('click', deleteSelectedCategory);
document.getElementById('category-delete-subtree-btn').addEventListener('click', () => deleteCategory(true));
document.getElementById('category-files-move-btn').addEventListener('click', () => {
    const target = document.getElementById('category-file-move-target').value;
    if (target) assignFiles([...selectedFileIds], target);
});
document.getElementById('category-files-remove-btn').addEventListener('click', () => assignFiles([...selectedFileIds], null));

categoryTree.addEventListener('click', event => {
    const editToggle = event.target.closest('[data-edit-category]');
    if (editToggle) {
        const categoryId = editToggle.dataset.editCategory;
        categoryEditOpenId = categoryEditOpenId === categoryId ? null : categoryId;
        renderCategoryTree();
        return;
    }
    const addChild = event.target.closest('[data-add-child-category]');
    if (addChild) {
        createCategory(addChild.dataset.addChildCategory);
        return;
    }
    const rename = event.target.closest('[data-rename-category]');
    if (rename) {
        startRename(rename.dataset.renameCategory);
        return;
    }
    const move = event.target.closest('[data-move-category]');
    if (move) {
        const categoryId = move.dataset.moveCategory;
        const target = document.querySelector(`[data-category-move-target="${categoryId}"]`);
        moveCategory(categoryId, target.value || null);
        return;
    }
    const remove = event.target.closest('[data-delete-category]');
    if (remove) {
        openDeleteDialog();
        return;
    }
    const expander = event.target.closest('[data-expand-category]');
    if (expander) {
        const categoryId = expander.dataset.expandCategory;
        if (expandedCategoryIds.has(categoryId)) expandedCategoryIds.delete(categoryId);
        else expandedCategoryIds.add(categoryId);
        renderCategoryTree();
        return;
    }
    const selector = event.target.closest('[data-select-category]');
    if (selector) selectCategory(selector.dataset.selectCategory);
});
categoryTree.addEventListener('dragstart', event => {
    const item = event.target.closest('[data-category-id]');
    if (!item) return;
    draggedCategoryId = item.dataset.categoryId;
    event.dataTransfer.effectAllowed = 'move';
    item.classList.add('is-dragging');
});
categoryTree.addEventListener('dragend', event => {
    draggedCategoryId = null;
    event.target.closest('[data-category-id]')?.classList.remove('is-dragging');
    document.querySelectorAll('.is-drag-over').forEach(item => item.classList.remove('is-drag-over'));
});
categoryTree.addEventListener('dragover', event => {
    const item = event.target.closest('[data-category-id]');
    if (!item) return;
    const targetId = item.dataset.categoryId;
    if (draggedCategoryId && targetId !== draggedCategoryId && !descendantIds(draggedCategoryId).has(targetId)) {
        event.preventDefault();
        item.classList.add('is-drag-over');
    } else if (!draggedCategoryId && event.dataTransfer.types.includes('application/x-jolia-files')) {
        event.preventDefault();
        item.classList.add('is-drag-over');
    }
});
categoryTree.addEventListener('dragleave', event => event.target.closest('[data-category-id]')?.classList.remove('is-drag-over'));
categoryTree.addEventListener('drop', event => {
    const item = event.target.closest('[data-category-id]');
    if (!item) return;
    event.preventDefault();
    item.classList.remove('is-drag-over');
    if (draggedCategoryId) moveCategory(draggedCategoryId, item.dataset.categoryId);
    else assignFiles(JSON.parse(event.dataTransfer.getData('application/x-jolia-files') || '[]'), item.dataset.categoryId);
});

filesList.addEventListener('change', event => {
    const checkbox = event.target.closest('[data-select-file]');
    if (!checkbox) return;
    if (checkbox.checked) selectedFileIds.add(checkbox.dataset.selectFile);
    else selectedFileIds.delete(checkbox.dataset.selectFile);
    updateFileActions();
});
filesList.addEventListener('click', event => {
    const button = event.target.closest('[data-open-file]');
    if (button) openDetail(event, button.dataset.openFile);
});
filesList.addEventListener('dragstart', event => {
    const row = event.target.closest('[data-file-id]');
    if (!row) return;
    const fileIds = selectedFileIds.has(row.dataset.fileId) ? [...selectedFileIds] : [row.dataset.fileId];
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('application/x-jolia-files', JSON.stringify(fileIds));
    row.classList.add('is-dragging');
});
filesList.addEventListener('dragend', event => event.target.closest('[data-file-id]')?.classList.remove('is-dragging'));

loadCategories();