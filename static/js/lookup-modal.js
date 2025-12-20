(function () {
  const modal = document.querySelector('[data-lookup-modal]');
  const lookupUrls = window.APP_LOOKUP_URLS || {};
  if (!modal || !Object.keys(lookupUrls).length) {
    return;
  }

  const titleEl = modal.querySelector('[data-lookup-title]');
  const formEl = modal.querySelector('[data-lookup-form]');
  const searchInput = modal.querySelector('[data-lookup-input]');
  const tableEl = modal.querySelector('[data-lookup-table]');
  const headRow = modal.querySelector('[data-lookup-head]');
  const bodyEl = modal.querySelector('[data-lookup-body]');
  const feedbackEl = modal.querySelector('[data-lookup-feedback]');
  const confirmBtn = modal.querySelector('[data-lookup-confirm]');
  const closeButtons = modal.querySelectorAll('[data-lookup-close]');
  const hintEl = modal.querySelector('[data-lookup-hint]');

  const metadata = {
    clients: { title: 'Selecionar cliente' },
    products: { title: 'Selecionar produto' },
    suppliers: { title: 'Selecionar fornecedor' },
    quotes: { title: 'Selecionar orçamento' },
  };

  const lastSearchTerm = {};

  const state = {
    type: null,
    target: null,
    results: [],
    selectedIndex: -1,
    columns: [],
    previousFocus: null,
    searchTerm: '',
    multiple: false,
    selection: new Set(),
  };

  let requestToken = 0;

  function attachLookup(element) {
    if (!element || element.dataset.lookupBound) {
      return;
    }
    element.dataset.lookupBound = '1';
    element.addEventListener('keydown', (event) => {
      if (event.key === 'F2') {
        event.preventDefault();
        const type = element.dataset.lookupType;
        if (!type) {
          return;
        }
        openLookup(element, type);
      }
    });
  }

  function findTargetFromTrigger(trigger) {
    const scope = trigger.closest('.lookup-field');
    if (scope) {
      return scope.querySelector('[data-lookup-type]');
    }
    const forId = trigger.getAttribute('data-lookup-target');
    if (forId) {
      return document.getElementById(forId);
    }
    return null;
  }

  function openLookup(target, type) {
    if (!lookupUrls[type]) {
      console.warn('Lookup URL não configurada para', type);
      return;
    }
    state.type = type;
    state.target = target;
    const multiAttr = (target?.dataset.lookupMultiple || '').toLowerCase();
    state.multiple = ['true', '1', 'yes', 'on'].includes(multiAttr);
    state.selection = new Set();
    state.previousFocus = document.activeElement;
    state.results = [];
    state.selectedIndex = -1;
    state.columns = [];
    state.searchTerm = lastSearchTerm[type] || '';
    titleEl.textContent = (metadata[type] && metadata[type].title) || 'Pesquisar';
    feedbackEl.textContent = '';
    confirmBtn.disabled = true;
    tableEl.hidden = true;
    headRow.innerHTML = '';
    bodyEl.innerHTML = '';
    if (hintEl) {
      hintEl.hidden = false;
    }

    modal.classList.add('is-active');
    modal.setAttribute('aria-hidden', 'false');
    document.documentElement.classList.add('is-clipped');
    window.setTimeout(() => {
      if (searchInput) {
        searchInput.value = state.searchTerm;
        searchInput.focus();
        searchInput.select();
      }
    }, 10);
    fetchResults(state.searchTerm);
  }

  function closeLookup() {
    persistSearchTerm();
    modal.classList.remove('is-active');
    modal.setAttribute('aria-hidden', 'true');
    document.documentElement.classList.remove('is-clipped');
    state.type = null;
    state.target = null;
    state.results = [];
    state.selectedIndex = -1;
    if (state.previousFocus && typeof state.previousFocus.focus === 'function') {
      try {
        state.previousFocus.focus();
      } catch (err) {
        // ignore
      }
    }
  }

  function fetchResults(term) {
    if (!state.type) {
      return;
    }
    state.searchTerm = term || '';
    lastSearchTerm[state.type] = state.searchTerm;
    const urlTemplate = lookupUrls[state.type];
    if (!urlTemplate) {
      return;
    }
    const fetchId = ++requestToken;
    feedbackEl.textContent = 'Carregando resultados...';
    tableEl.hidden = true;
    bodyEl.innerHTML = '';
    state.selection = new Set();
    confirmBtn.disabled = true;

    const url = new URL(urlTemplate, window.location.origin);
    if (term) {
      url.searchParams.set('q', term);
    }

    fetch(url.toString(), {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json();
      })
      .then((payload) => {
        if (fetchId !== requestToken) {
          return;
        }
        renderResults(payload);
      })
      .catch((err) => {
        console.error('Lookup fetch error', err);
        if (fetchId !== requestToken) {
          return;
        }
        feedbackEl.textContent = 'Não foi possível carregar os resultados. Tente novamente.';
        tableEl.hidden = true;
        confirmBtn.disabled = true;
      });
  }

  function renderResults(payload) {
    state.results = Array.isArray(payload?.results) ? payload.results : [];
    state.columns = Array.isArray(payload?.columns) ? payload.columns : [];
    state.selection = new Set();
    headRow.innerHTML = '';
    bodyEl.innerHTML = '';

    if (!state.columns.length) {
      state.columns = Object.keys(state.results[0] || {})
        .filter((key) => !['id', 'label'].includes(key))
        .map((key) => ({ key, label: key.toUpperCase() }));
    }

    if (state.multiple) {
      const th = document.createElement('th');
      th.style.width = '40px';
      const masterCheckbox = document.createElement('input');
      masterCheckbox.type = 'checkbox';
      masterCheckbox.setAttribute('aria-label', 'Selecionar todos');
      masterCheckbox.addEventListener('change', () => {
        masterCheckbox.indeterminate = false;
        if (masterCheckbox.checked) {
          state.selection = new Set(state.results.map((_, idx) => idx));
        } else {
          state.selection.clear();
        }
        updateRowSelectionVisuals();
        updateConfirmState();
      });
      th.appendChild(masterCheckbox);
      headRow.appendChild(th);
    }

    state.columns.forEach((column) => {
      const th = document.createElement('th');
      th.textContent = column.label;
      headRow.appendChild(th);
    });

    if (!state.results.length) {
      feedbackEl.textContent = 'Nenhum registro encontrado.';
      tableEl.hidden = true;
      confirmBtn.disabled = true;
      return;
    }

    feedbackEl.textContent = '';
    tableEl.hidden = false;

    state.results.forEach((record, index) => {
      const tr = document.createElement('tr');
      tr.dataset.index = String(index);
      tr.tabIndex = -1;
      if (state.multiple) {
        const tdSelect = document.createElement('td');
        tdSelect.style.width = '40px';
        tdSelect.style.textAlign = 'center';
        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.dataset.lookupCheckbox = '1';
        checkbox.addEventListener('click', (event) => event.stopPropagation());
        checkbox.addEventListener('change', () => {
          toggleRowSelection(index, checkbox.checked);
        });
        tdSelect.appendChild(checkbox);
        tr.appendChild(tdSelect);
      }
      state.columns.forEach((column) => {
        const td = document.createElement('td');
        const raw = record[column.key];
        td.textContent = raw === null || raw === undefined ? '' : String(raw);
        tr.appendChild(td);
      });
      tr.addEventListener('click', () => {
        if (state.multiple) {
          const shouldSelect = !state.selection.has(index);
          toggleRowSelection(index, shouldSelect);
        } else {
          selectRow(index, { focus: true });
        }
      });
      tr.addEventListener('dblclick', () => {
        if (state.multiple) {
          const shouldSelect = !state.selection.has(index);
          toggleRowSelection(index, shouldSelect);
        } else {
          selectRow(index);
          confirmSelection();
        }
      });
      bodyEl.appendChild(tr);
    });

    selectRow(0, { focus: true });
    updateRowSelectionVisuals();
  }

  function selectRow(index, options = {}) {
    const rows = bodyEl.querySelectorAll('tr');
    rows.forEach((row) => row.classList.remove('is-active'));

    const row = rows[index];
    if (!row) {
      state.selectedIndex = -1;
      confirmBtn.disabled = true;
      return;
    }
    row.classList.add('is-active');
    if (options.focus) {
      row.focus();
    }
    state.selectedIndex = index;
    updateConfirmState();
  }

  function updateRowSelectionVisuals() {
    if (!state.multiple) {
      return;
    }
    const rows = bodyEl.querySelectorAll('tr');
    rows.forEach((row, idx) => {
      const checkbox = row.querySelector('input[type="checkbox"][data-lookup-checkbox]');
      const isSelected = state.selection.has(idx);
      row.classList.toggle('is-selected', isSelected);
      if (checkbox) {
        checkbox.checked = isSelected;
      }
    });
    const masterCheckbox = headRow.querySelector('th input[type="checkbox"]');
    if (masterCheckbox) {
      const total = state.results.length;
      const selected = state.selection.size;
      masterCheckbox.checked = total > 0 && selected === total;
      masterCheckbox.indeterminate = selected > 0 && selected < total;
    }
  }

  function toggleRowSelection(index, shouldSelect) {
    if (!state.results[index]) {
      return;
    }
    if (shouldSelect) {
      state.selection.add(index);
    } else {
      state.selection.delete(index);
    }
    updateRowSelectionVisuals();
    updateConfirmState();
  }

  function updateConfirmState() {
    if (state.multiple) {
      confirmBtn.disabled = state.selection.size === 0;
    } else {
      confirmBtn.disabled = state.selectedIndex < 0;
    }
  }

  function confirmSelection() {
    if (state.multiple) {
      const records = Array.from(state.selection)
        .map((idx) => state.results[idx])
        .filter(Boolean);
      if (!records.length) {
        return;
      }
      persistSearchTerm();
      applyMultipleSelection(records);
      closeLookup();
      return;
    }
    if (state.selectedIndex < 0 || !state.results[state.selectedIndex]) {
      return;
    }
    persistSearchTerm();
    const record = state.results[state.selectedIndex];
    applySelection(record);
    closeLookup();
  }

  function applySelection(record) {
    const target = state.target;
    if (!target || !record) {
      return;
    }
    const value = record.id != null ? String(record.id) : '';
    const label = record.label || record.name || value;
    if (target.tagName === 'SELECT') {
      let option = null;
      try {
        option = target.querySelector(`option[value=\"${CSS.escape(value)}\"]`);
      } catch (err) {
        option = target.querySelector(`option[value=\"${value.replace(/\"/g, '\\"')}\"]`);
      }
      if (!option && value) {
        option = new Option(label, value, true, true);
        target.appendChild(option);
      }
      if (value) {
        target.value = value;
      }
      target.dispatchEvent(new Event('change', { bubbles: true }));
    } else {
      target.value = label;
      target.dataset.lookupValue = value;
      target.dispatchEvent(new Event('input', { bubbles: true }));
      target.dispatchEvent(new Event('change', { bubbles: true }));
    }

    dispatchSelectionEvent(target, {
      record,
      records: record ? [record] : [],
    });
  }

  function applyMultipleSelection(records) {
    const target = state.target;
    if (!target || !records.length) {
      return;
    }
    dispatchSelectionEvent(target, {
      record: records[0] || null,
      records,
    });
  }

  function dispatchSelectionEvent(target, detail) {
    try {
      target.dispatchEvent(
        new CustomEvent('lookup:selected', {
          bubbles: true,
          detail,
        })
      );
    } catch (err) {
      console.warn('lookup:selected dispatch error', err);
    }
  }

  document.querySelectorAll('[data-lookup-type]').forEach((element) => {
    attachLookup(element);
  });

  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-lookup-trigger]');
    if (!trigger) {
      return;
    }
    const type = trigger.dataset.lookupType;
    const field = findTargetFromTrigger(trigger);
    if (field && type) {
      openLookup(field, type);
    }
  });

  formEl.addEventListener('submit', (event) => {
    event.preventDefault();
    fetchResults(searchInput.value.trim());
  });

  closeButtons.forEach((button) => {
    button.addEventListener('click', (event) => {
      event.preventDefault();
      closeLookup();
    });
  });

  confirmBtn.addEventListener('click', (event) => {
    event.preventDefault();
    confirmSelection();
  });

  function persistSearchTerm() {
    if (!state.type || !searchInput) {
      return;
    }
    const value = searchInput.value || '';
    state.searchTerm = value;
    lastSearchTerm[state.type] = value;
  }

  modal.addEventListener('keydown', (event) => {
    if (!modal.classList.contains('is-active')) {
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      closeLookup();
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      if (state.selectedIndex < state.results.length - 1) {
        selectRow(state.selectedIndex + 1, { focus: true });
      }
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      if (state.selectedIndex > 0) {
        selectRow(state.selectedIndex - 1, { focus: true });
      }
    } else if (event.key === 'Enter') {
      const active = document.activeElement;
      if (active === searchInput) {
        event.preventDefault();
        fetchResults(searchInput.value.trim());
      } else if (bodyEl.contains(active)) {
        event.preventDefault();
        if (state.multiple) {
          const currentIndex = state.selectedIndex;
          if (currentIndex >= 0) {
            const shouldSelect = !state.selection.has(currentIndex);
            toggleRowSelection(currentIndex, shouldSelect);
          }
        } else {
          confirmSelection();
        }
      }
    }
  });

  modal.addEventListener('click', (event) => {
    if (event.target === modal) {
      closeLookup();
    }
  });

  document.addEventListener('lucide:icons-updated', () => {
    document.querySelectorAll('[data-lookup-type]').forEach((element) => attachLookup(element));
  });
})();
