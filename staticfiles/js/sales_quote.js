(function () {
  const table = document.querySelector('.sales-items-table');
  if (!table) {
    return;
  }

  const tbody = table.querySelector('[data-quote-items-body]');
  if (!tbody) {
    return;
  }

  const clientField = document.querySelector('[name="client"]');
  const itemsBlocker = document.querySelector('[data-items-blocker]');
  const quoteNumberDisplay = document.querySelector('[data-quote-number-display]');

  const formPrefix = table.dataset.formPrefix || 'items';
  const templateEl = document.querySelector('#quote-item-row-template');
  const totalFormsInput = document.querySelector(`input[name="${formPrefix}-TOTAL_FORMS"]`);
  const parentForm = table.closest('form');
  const addRowButtons = document.querySelectorAll('[data-action="add-item-row"]');

  const lookupUrl =
    table.dataset.productLookupUrl ||
    (window.SALES_QUOTE_CONFIG && window.SALES_QUOTE_CONFIG.productLookupUrl);

  const numberFormatter = new Intl.NumberFormat('pt-BR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const percentFormatter = new Intl.NumberFormat('pt-BR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });

  const searchCache = new Map();
  const rowState = new Map();
  let lastConfirmedSearchTerm = '';
  let itemsUnlocked = false;

  const summaryElements = {
    quantity: document.querySelector('[data-summary="quantity"]'),
    discount: document.querySelector('[data-summary="discount"]'),
    gross: document.querySelector('[data-summary="gross"]'),
    net: document.querySelector('[data-summary="net"]'),
    margin: document.querySelector('[data-summary="margin"]'),
    discountPercent: document.querySelector('[data-summary-discount-percent]'),
  };

  const initialRows = Array.from(tbody.querySelectorAll('.sales-item-row'));
  initialRows.forEach((row) => registerRow(row));

  if (!initialRows.length) {
    addNewRow({ focus: false, prefillTerm: '' });
  }
  refreshRowIndices();
  recalcSummary();
  setupDraftsToggle();
  initializeClientFlow();

  document.addEventListener('click', handleDocumentClick);
  document.addEventListener('keydown', handleGlobalShortcuts, true);
  if (parentForm) {
    parentForm.addEventListener('submit', normalizeAllDiscountInputs);
  }
  addRowButtons.forEach((button) => {
    button.addEventListener('click', () => {
      const activeRow = document.activeElement
        ? document.activeElement.closest('.sales-item-row')
        : null;
      if (activeRow && table.contains(activeRow)) {
        confirmRow(activeRow, { focusNext: false });
      }
      addNewRow({ focus: true, prefillTerm: '' });
    });
  });

  function registerRow(row) {
    if (!row || rowState.has(row)) {
      return;
    }
    const state = { timer: null, requestId: 0, lastSearchTerm: '', confirmedTerm: '' };
    rowState.set(row, state);
    setupRow(row, state);
    recalcRow(row);
    refreshRowIndices();
  }

  function setupRow(row, state) {
    const deleteCheckbox = row.querySelector('input[name$="-DELETE"]');
    const deleteButton = row.querySelector('[data-action="delete-item"]');
    const editButton = row.querySelector('[data-action="edit-item"]');
    const nextRowButton = row.querySelector('[data-action="next-row"]');

    if (deleteCheckbox) {
      row.classList.toggle('is-deleted', deleteCheckbox.checked);
      updateDeleteButtonState(deleteButton, deleteCheckbox.checked);
      deleteCheckbox.addEventListener('change', () => {
        row.classList.toggle('is-deleted', deleteCheckbox.checked);
        updateDeleteButtonState(deleteButton, deleteCheckbox.checked);
        recalcRow(row);
        recalcSummary();
      });
    } else if (deleteButton) {
      deleteButton.disabled = true;
    }

    if (deleteButton && deleteCheckbox) {
      deleteButton.addEventListener('click', (event) => {
        event.preventDefault();
        handleDeleteAction(row, deleteCheckbox, deleteButton);
      });
    }

    if (editButton) {
      editButton.addEventListener('click', (event) => {
        event.preventDefault();
        handleEditAction(row);
      });
    }

    if (nextRowButton) {
      nextRowButton.addEventListener('click', (event) => {
        event.preventDefault();
        confirmRow(row);
      });
    }

    const numericInputs = row.querySelectorAll('[data-field]');
    numericInputs.forEach((input) => {
      input.addEventListener('input', () => {
        recalcRow(row);
        recalcSummary();
      });
      input.addEventListener('change', () => {
        recalcRow(row);
        recalcSummary();
      });
      input.addEventListener('keydown', (event) => handleRowKeydown(event, row));
      input.addEventListener('focus', () => {
        scrollRowIntoView(row);
      });
    });

    const productSelect = row.querySelector('[data-product-select]');
    const searchInput = row.querySelector('[data-product-search-input]');
    const resultsPanel = row.querySelector('[data-product-search-results]');
    const descriptionInput = row.querySelector('[data-description-field]');

    initializeDiscountControl(row);

    if (productSelect && searchInput) {
      if (productSelect.value) {
        const option = productSelect.selectedOptions[0];
        if (option) {
          if (!option.dataset.productName) {
            option.dataset.productName = option.textContent.trim();
          }
          if (!option.dataset.productLabel) {
            option.dataset.productLabel = option.textContent.trim();
          }
          updateProductDisplay(row, {
            label: option.dataset.productLabel || option.textContent.trim(),
            name: option.dataset.productName || option.textContent.trim(),
          });
        }
        row.dataset.productId = productSelect.value;
      } else {
        updateProductDisplay(row, null);
        if (descriptionInput) {
          descriptionInput.value = '';
        }
        delete row.dataset.productId;
      }

      searchInput.addEventListener('input', () => {
        const rawValue = searchInput.value;
        state.lastSearchTerm = rawValue;
        searchInput.title = rawValue.trim();
        handleProductSearch(row, searchInput, productSelect, resultsPanel);
      });

      searchInput.addEventListener('focus', () => {
        scrollRowIntoView(row);
        requestAnimationFrame(() => {
          try {
            searchInput.select();
          } catch (err) {
            // ignore selection errors
          }
        });
      });

      searchInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
          const firstResult = resultsPanel?.querySelector('button');
          if (firstResult && resultsPanel.classList.contains('is-open')) {
            event.preventDefault();
            event.stopPropagation();
            firstResult.click();
            return;
          }
          event.preventDefault();
          event.stopPropagation();
          confirmRow(row);
        } else if (event.key === 'Escape') {
          event.preventDefault();
          state.lastSearchTerm = '';
          searchInput.value = '';
          searchInput.title = '';
          closeResults(resultsPanel);
        }
      });

      searchInput.addEventListener('lookup:selected', (event) => {
        const record = event.detail && event.detail.record;
        if (record) {
          applyProductSelection(row, record, productSelect, resultsPanel);
        }
      });
    }

    if (resultsPanel) {
      resultsPanel.addEventListener('mousedown', (event) => {
        event.preventDefault();
      });
    }

    row.addEventListener('keydown', (event) => handleRowKeydown(event, row), true);
  }

  function initializeClientFlow() {
    if (!clientField) {
      updateQuoteNumberDisplay(true);
      return;
    }
    const updateHandler = () => {
      updateClientFlowState();
    };
    ['change', 'blur', 'input'].forEach((eventName) => {
      clientField.addEventListener(eventName, updateHandler);
    });
    clientField.addEventListener('lookup:selected', updateHandler);
    updateClientFlowState();
  }

  function hasClientSelection() {
    if (!clientField) {
      return true;
    }
    const rawValue = clientField.value;
    if (rawValue === null || rawValue === undefined) {
      return false;
    }
    if (typeof rawValue === 'string') {
      return rawValue.trim() !== '';
    }
    return Boolean(rawValue);
  }

  function updateQuoteNumberDisplay(hasClient) {
    if (!quoteNumberDisplay || quoteNumberDisplay.dataset.numberFixed === 'true') {
      return;
    }
    const pendingNumber = quoteNumberDisplay.dataset.numberPending || '';
    if (hasClient && pendingNumber) {
      quoteNumberDisplay.textContent = pendingNumber;
      quoteNumberDisplay.classList.remove('is-awaiting-number');
    } else {
      quoteNumberDisplay.textContent = '—';
      quoteNumberDisplay.classList.add('is-awaiting-number');
    }
  }

  function updateClientFlowState() {
    const hasClient = hasClientSelection();
    if (itemsBlocker) {
      if (hasClient) {
        itemsBlocker.hidden = true;
        itemsBlocker.setAttribute('aria-hidden', 'true');
      } else {
        itemsBlocker.hidden = false;
        itemsBlocker.setAttribute('aria-hidden', 'false');
      }
    }
    addRowButtons.forEach((button) => {
      button.disabled = !hasClient;
    });
    updateQuoteNumberDisplay(hasClient);
    if (hasClient && !itemsUnlocked) {
      itemsUnlocked = true;
      focusFirstEmptyRow();
    }
    if (!hasClient) {
      itemsUnlocked = false;
    }
  }

  function handleDocumentClick(event) {
    rowState.forEach((state, row) => {
      if (!table.contains(row)) {
        rowState.delete(row);
        return;
      }
      const wrapper = row.querySelector('.product-search-wrapper');
      const resultsPanel = row.querySelector('[data-product-search-results]');
      if (!wrapper || !resultsPanel) {
        return;
      }
      if (!wrapper.contains(event.target)) {
        closeResults(resultsPanel);
      }
    });
  }

  function applyDiscountLockState(row, locked, options = {}) {
    if (!row) {
      return;
    }
    const input = row.querySelector('[data-field="discount"]');
    const button = row.querySelector('[data-discount-toggle]');
    if (!input) {
      return;
    }
    const { silent = false, focus = false, force = false } = options;
    const currentlyLocked = input.dataset.discountLocked !== 'false';
    if (!force && locked === currentlyLocked) {
      if (focus && !locked) {
        requestAnimationFrame(() => {
          input.focus();
          try {
            input.select();
          } catch (err) {
            // ignore selection errors
          }
        });
      }
      return;
    }

    if (locked) {
      input.dataset.discountLocked = 'true';
      input.setAttribute('readonly', 'readonly');
      input.setAttribute('tabindex', '-1');
      input.setAttribute('aria-disabled', 'true');
      input.classList.add('is-discount-locked');
      if (!silent) {
        input.blur();
      }
      if (button) {
        button.classList.remove('is-active');
        button.setAttribute('aria-pressed', 'false');
        button.setAttribute('title', 'Editar desconto');
      }
    } else {
      input.dataset.discountLocked = 'false';
      input.removeAttribute('readonly');
      input.removeAttribute('tabindex');
      input.removeAttribute('aria-disabled');
      input.classList.remove('is-discount-locked');
      if (button) {
        button.classList.add('is-active');
        button.setAttribute('aria-pressed', 'true');
        button.setAttribute('title', 'Concluir edição do desconto');
      }
      if (focus) {
        requestAnimationFrame(() => {
          input.focus();
          try {
            input.select();
          } catch (err) {
            // ignore selection errors
          }
        });
      }
    }
  }

  function initializeDiscountControl(row) {
    if (!row) {
      return;
    }
    const input = row.querySelector('[data-field="discount"]');
    const button = row.querySelector('[data-discount-toggle]');
    if (!input) {
      return;
    }

    applyDiscountLockState(row, true, { silent: true, force: true });

    if (!row.dataset.discountControlInitialized) {
      row.dataset.discountControlInitialized = 'true';

      input.addEventListener('blur', () => {
        if (input.dataset.discountLocked === 'false') {
          applyDiscountLockState(row, true);
          recalcRow(row);
          recalcSummary();
        }
      });

      input.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
          applyDiscountLockState(row, true);
          recalcRow(row);
          recalcSummary();
        }
      });

      if (button) {
        button.addEventListener('click', () => {
          const locked = input.dataset.discountLocked !== 'false';
          if (locked) {
            applyDiscountLockState(row, false, { focus: true });
          } else {
            applyDiscountLockState(row, true);
            recalcRow(row);
            recalcSummary();
          }
        });
      }
    }
  }

  function handleProductSearch(row, input, select, resultsPanel) {
    const state = rowState.get(row);
    if (!state) {
      return;
    }
    if (state.timer) {
      clearTimeout(state.timer);
    }
    const rawValue = input.value;
    state.lastSearchTerm = rawValue;
    const term = rawValue.trim();
    if (term.length < 2) {
      closeResults(resultsPanel);
      return;
    }

    state.timer = setTimeout(() => {
      const cacheKey = term.toLowerCase();
      if (searchCache.has(cacheKey)) {
        renderResults(row, select, resultsPanel, searchCache.get(cacheKey));
        return;
      }
      if (!lookupUrl) {
        renderResults(row, select, resultsPanel, []);
        return;
      }

      const requestId = ++state.requestId;
      const url = new URL(lookupUrl, window.location.origin);
      url.searchParams.set('q', term);

      fetch(url.toString(), {
        headers: { 'X-Requested-With': 'XMLHttpRequest' },
      })
        .then((response) => {
          if (!response.ok) {
            throw new Error('HTTP error');
          }
          return response.json();
        })
        .then((data) => {
          if (state.requestId !== requestId) {
            return;
          }
          const results = (data && data.results) || [];
          searchCache.set(cacheKey, results);
          renderResults(row, select, resultsPanel, results);
        })
        .catch(() => {
          if (state.requestId !== requestId) {
            return;
          }
          renderResults(row, select, resultsPanel, [], true);
        });
    }, 200);
  }

  function renderResults(row, select, panel, results, failed = false) {
    if (!panel) {
      return;
    }
    panel.innerHTML = '';
    if (!results || results.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'empty-state';
      empty.textContent = failed
        ? 'Não foi possível buscar produtos.'
        : 'Nenhum produto encontrado.';
      panel.appendChild(empty);
    } else {
      results.forEach((result) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.productId = result.id;
        button.dataset.productLabel = result.label || result.name || '';
        button.dataset.productPrice = result.price || '';
        button.dataset.productUnit = result.unit || '';
        button.dataset.productCost = result.cost_price || '';
        button.dataset.productCode = result.code || '';
        button.dataset.productName = result.name || '';
        button.dataset.productStock = result.stock || '';

        const priceDisplay = result.price
          ? formatNumber(parseDecimal(result.price))
          : '';
        const stockDisplay = result.stock
          ? formatNumber(parseDecimal(result.stock))
          : '';

        button.innerHTML = `
          <span class="result-label">
            <span>${result.label || result.name || ''}</span>
            <span>${priceDisplay}</span>
          </span>
          <span class="result-meta">
            ${result.code ? `<span>PLU ${result.code}</span>` : ''}
            ${result.unit ? `<span>${result.unit}</span>` : ''}
            ${
              stockDisplay
                ? `<span>Estoque: ${stockDisplay}</span>`
                : ''
            }
          </span>
        `;

        button.addEventListener('click', () => {
          applyProductSelection(
            row,
            {
              id: result.id,
              label: result.label || result.name || '',
              name: result.name || '',
              price: result.price || '',
              unit: result.unit || '',
              cost_price: result.cost_price || '',
              code: result.code || '',
            },
            select,
            panel
          );
        });

        panel.appendChild(button);
      });
    }
    panel.hidden = false;
    panel.classList.add('is-open');
  }

  function closeResults(panel) {
    if (!panel) {
      return;
    }
    panel.classList.remove('is-open');
    panel.hidden = true;
  }

  function applyProductSelection(row, product, select, panel) {
    if (!product || !select) {
      return;
    }

    const previousProductId = row.dataset.productId || '';
    const productId = product.id != null ? String(product.id) : '';
    let option = null;
    try {
      option = select.querySelector(`option[value="${CSS.escape(productId)}"]`);
    } catch (err) {
      option = select.querySelector(`option[value="${productId.replace(/"/g, '\\"')}"]`);
    }
    if (!option) {
      option = new Option(product.label || product.name || '', productId, true, true);
      select.appendChild(option);
    } else if (product.label) {
      option.textContent = product.label;
    }
    if (option) {
      if (product.name) {
        option.dataset.productName = product.name;
      }
      if (product.label) {
        option.dataset.productLabel = product.label;
      }
      if (product.unit) {
        option.dataset.productUnit = product.unit;
      }
    }
    select.value = productId;
    select.dispatchEvent(new Event('change', { bubbles: true }));

    const state = rowState.get(row);
    const referenceRaw =
      state && state.lastSearchTerm && state.lastSearchTerm.trim()
        ? state.lastSearchTerm.trim()
        : product.code || product.label || product.name || '';
    const referenceTerm = referenceRaw ? String(referenceRaw).trim() : '';
    if (state) {
      state.confirmedTerm = referenceTerm;
    }
    if (referenceTerm) {
      lastConfirmedSearchTerm = referenceTerm;
    }

    updateProductDisplay(row, {
      label: product.label || (option ? option.textContent.trim() : ''),
      name:
        product.name ||
        (option && option.dataset.productName ? option.dataset.productName : ''),
    });

    const unitText = row.querySelector('.unit-text');
    if (unitText) {
      unitText.textContent =
        product.unit ||
        (option && option.dataset.productUnit ? option.dataset.productUnit : '—');
    }

    if (product.cost_price) {
      row.dataset.costPrice = product.cost_price;
    }

    const unitPriceInput = row.querySelector('[data-field="unit_price"]');
    if (
      unitPriceInput &&
      (!unitPriceInput.value || parseDecimal(unitPriceInput.value) === 0) &&
      product.price
    ) {
      unitPriceInput.value = product.price;
    }

    const quantityInput = row.querySelector('[data-field="quantity"]');
    if (quantityInput && !quantityInput.value) {
      quantityInput.value = '1';
    }

    closeResults(panel);
    if (handleDuplicateSelection(row, productId, previousProductId)) {
      return;
    }

    if (productId) {
      row.dataset.productId = productId;
    } else {
      delete row.dataset.productId;
    }

    recalcRow(row);
    recalcSummary();
    focusNextEditable(row);
  }

  function updateProductDisplay(row, selection) {
    const searchInput = row.querySelector('[data-product-search-input]');
    const descriptionInput = row.querySelector('[data-description-field]');
    const nameDisplay = row.querySelector('[data-product-name-display]');

    const label = selection && selection.label ? String(selection.label).trim() : '';
    const name = selection && selection.name ? String(selection.name).trim() : '';
    const displayText = name || label;
    const inputLabel = label || name;

    if (searchInput) {
      if (selection && (selection.label || selection.name)) {
        searchInput.value = inputLabel;
      }
      const currentValue = selection ? inputLabel : searchInput.value;
      searchInput.title = currentValue ? String(currentValue).trim() : '';
    }

    if (descriptionInput) {
      descriptionInput.value = displayText || '';
    }

    if (nameDisplay) {
      if (displayText) {
        nameDisplay.textContent = displayText;
        nameDisplay.hidden = false;
        nameDisplay.title = displayText;
      } else {
        nameDisplay.textContent = '';
        nameDisplay.hidden = true;
        nameDisplay.removeAttribute('title');
      }
    }
  }

  function focusNextEditable(row) {
    const quantityInput = row.querySelector('[data-field="quantity"]');
    if (quantityInput) {
      requestAnimationFrame(() => {
        quantityInput.focus();
        if (typeof quantityInput.select === 'function') {
          quantityInput.select();
        }
        scrollRowIntoView(row);
      });
      return;
    }
    const fallback = row.querySelector('[data-field]');
    if (fallback) {
      requestAnimationFrame(() => {
        fallback.focus();
        if (typeof fallback.select === 'function') {
          fallback.select();
        }
        scrollRowIntoView(row);
      });
    }
  }

  function handleRowKeydown(event, row) {
    const target = event.target;
    if (event.key === 'Tab') {
      const focusables = getRowFocusables(row);
      const currentIndex = focusables.indexOf(target);
      if (currentIndex !== -1) {
        event.preventDefault();
        event.stopPropagation();
        const direction = event.shiftKey ? -1 : 1;
        const nextIndex = currentIndex + direction;
        if (nextIndex >= 0 && nextIndex < focusables.length) {
          focusRowElement(row, focusables[nextIndex]);
        } else if (direction > 0) {
          confirmRow(row);
        } else {
          focusPreviousRow(row);
        }
      }
      return;
    }
    if (event.defaultPrevented || event.key !== 'Enter') {
      return;
    }
    if (target && target.hasAttribute('data-product-search-input')) {
      return;
    }
    if (target && target.matches('textarea, [type="button"], [type="submit"]')) {
      return;
    }
    event.preventDefault();
    event.stopPropagation();
    confirmRow(row);
  }

  function confirmRow(row, options = {}) {
    if (!row || !table.contains(row)) {
      return;
    }
    const select = row.querySelector('[data-product-select]');
    if (!select || !select.value) {
      focusRowSearch(row, { prefillTerm: '', selectText: true, scroll: true });
      return;
    }

    const state = rowState.get(row);
    if (state && state.confirmedTerm) {
      lastConfirmedSearchTerm = state.confirmedTerm;
    }

    normalizeDiscountInput(row);
    recalcRow(row);
    recalcSummary();
    if (options.focusNext !== false) {
      advanceToNextRow(row);
    }
  }

  function advanceToNextRow(currentRow) {
    const nextEmpty = findNextEmptyRow(currentRow);
    if (nextEmpty) {
      focusRowSearch(nextEmpty, { prefillTerm: '', selectText: true, scroll: true });
      return;
    }
    const firstEmpty = findFirstEmptyRow();
    if (firstEmpty && firstEmpty !== currentRow) {
      focusRowSearch(firstEmpty, { prefillTerm: '', selectText: true, scroll: true });
      return;
    }
    addNewRow({ focus: true, prefillTerm: '' });
  }

  function findNextEmptyRow(currentRow) {
    const rows = Array.from(tbody.querySelectorAll('.sales-item-row'));
    const currentIndex = rows.indexOf(currentRow);
    for (let index = currentIndex + 1; index < rows.length; index += 1) {
      if (isRowEmpty(rows[index])) {
        return rows[index];
      }
    }
    return null;
  }

  function createRow() {
    if (!templateEl || !totalFormsInput) {
      return null;
    }
    const newIndex = Number(totalFormsInput.value || '0');
    const html = templateEl.innerHTML.replace(/__prefix__/g, String(newIndex));
    const container = document.createElement('tbody');
    container.innerHTML = html.trim();
    const newRow = container.firstElementChild;
    if (!newRow) {
      return null;
    }
    tbody.appendChild(newRow);
    totalFormsInput.value = String(newIndex + 1);
    registerRow(newRow);
    if (window.lucide) {
      window.lucide.createIcons();
    }
    recalcSummary();
    return newRow;
  }

  function refreshRowIndices() {
    const rows = Array.from(tbody.querySelectorAll('.sales-item-row'));
    rows.forEach((row, index) => {
      row.dataset.rowIndex = String(index);
      const badge = row.querySelector('[data-item-index]');
      if (badge) {
        badge.textContent = String(index + 1);
      }
    });
  }

  function isRowEmpty(row) {
    if (!row) {
      return true;
    }
    const select = row.querySelector('[data-product-select]');
    if (select && select.value) {
      return false;
    }
    const searchInput = row.querySelector('[data-product-search-input]');
    if (searchInput && searchInput.value.trim()) {
      return false;
    }
    return true;
  }

  function rowHasSelectedProduct(row) {
    if (!row) {
      return false;
    }
    const select = row.querySelector('[data-product-select]');
    return !!(select && select.value);
  }

  function focusRowSearch(row, options = {}) {
    const searchInput = row.querySelector('[data-product-search-input]');
    if (!searchInput) {
      return;
    }
    const state = rowState.get(row);
    const { prefillTerm, selectText = true, scroll = true } = options;

    if (typeof prefillTerm === 'string') {
      searchInput.value = prefillTerm;
      searchInput.title = prefillTerm.trim();
      if (state) {
        state.lastSearchTerm = prefillTerm;
      }
    }

    closeResults(row.querySelector('[data-product-search-results]'));

    requestAnimationFrame(() => {
      if (scroll) {
        scrollRowIntoView(row);
      }
      searchInput.focus();
      if (selectText) {
        try {
          searchInput.select();
        } catch (err) {
          // ignore selection errors
        }
      }
    });
  }

  function focusRowElement(row, element, { selectText = true } = {}) {
    if (!row || !element) {
      return;
    }
    scrollRowIntoView(row);
    requestAnimationFrame(() => {
      element.focus();
      if (selectText && typeof element.select === 'function') {
        try {
          element.select();
        } catch (err) {
          // ignore
        }
      }
    });
  }

  function findFirstEmptyRow() {
    return Array.from(tbody.querySelectorAll('.sales-item-row')).find((row) =>
      isRowEmpty(row)
    );
  }

  function addNewRow(options = {}) {
    const { prefillTerm = '', focus = true } = options;
    let targetRow = findFirstEmptyRow();
    if (!targetRow) {
      targetRow = createRow();
    }
    if (targetRow && focus) {
      focusRowSearch(targetRow, {
        prefillTerm,
        selectText: true,
        scroll: true,
      });
    }
    return targetRow;
  }

  function getRowFocusables(row) {
    if (!row) {
      return [];
    }
    const focusables = [];
    const searchInput = row.querySelector('[data-product-search-input]');
    if (searchInput) {
      focusables.push(searchInput);
    }
    if (rowHasSelectedProduct(row)) {
      const quantityInput = row.querySelector('[data-field="quantity"]');
      if (quantityInput) {
        focusables.push(quantityInput);
      }
      const discountInput = row.querySelector('[data-field="discount"]');
      if (discountInput && discountInput.dataset.discountLocked === 'false') {
        focusables.push(discountInput);
      }
      const unitPriceInput = row.querySelector('[data-field="unit_price"]');
      if (unitPriceInput) {
        focusables.push(unitPriceInput);
      }
      const nextRowButton = row.querySelector('[data-action="next-row"]');
      if (nextRowButton) {
        focusables.push(nextRowButton);
      }
    }
    return focusables;
  }

  function focusPreviousRow(row) {
    const rows = Array.from(tbody.querySelectorAll('.sales-item-row'));
    const currentIndex = rows.indexOf(row);
    for (let index = currentIndex - 1; index >= 0; index -= 1) {
      const candidate = rows[index];
      const focusables = getRowFocusables(candidate);
      if (focusables.length) {
        const last = focusables[focusables.length - 1];
        focusRowElement(candidate, last);
        return;
      }
    }
  }

  function focusFirstEmptyRow() {
    const target = findFirstEmptyRow();
    if (target) {
      focusRowSearch(target, { prefillTerm: '', selectText: true, scroll: false });
    }
  }

  function scrollRowIntoView(row) {
    if (!row || typeof row.scrollIntoView !== 'function') {
      return;
    }
    try {
      row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch (err) {
      row.scrollIntoView();
    }
  }

  function parseDecimal(raw) {
    if (raw === undefined || raw === null) {
      return 0;
    }
    let value = String(raw).trim();
    if (!value) {
      return 0;
    }
    value = value.replace(/[^\d.,-]/g, '');
    const hasComma = value.includes(',');
    const hasDot = value.includes('.');
    if (hasComma && hasDot) {
      value = value.replace(/\./g, '').replace(',', '.');
    } else {
      value = value.replace(',', '.');
    }
    const parsed = parseFloat(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function formatNumber(value) {
    const numeric = Number.isFinite(value) ? value : 0;
    return numberFormatter.format(numeric);
  }

  function formatPercent(value) {
    const numeric = Number.isFinite(value) ? value : 0;
    return `${percentFormatter.format(numeric)}%`;
  }

  function formatForInput(value, digits = 2) {
    if (!Number.isFinite(value)) {
      return '';
    }
    const fixed = value.toFixed(digits);
    const [intPart, decimalPart] = fixed.split('.');
    return `${intPart},${decimalPart}`;
  }

  function parseDiscount(rawValue, gross) {
    const result = { amount: 0, percent: null, mode: 'value' };
    let text = String(rawValue || '').trim();
    if (!text) {
      return result;
    }

    let mode = 'value';
    const normalized = text.toLowerCase().replace(/\s+/g, '');
    if (normalized.endsWith('%')) {
      mode = 'percent';
      text = text.slice(0, text.lastIndexOf('%'));
    } else if (normalized.endsWith('pct')) {
      mode = 'percent';
      text = text.slice(0, -3);
    } else if (normalized.endsWith('porc')) {
      mode = 'percent';
      text = text.slice(0, -4);
    } else if (normalized.endsWith('p')) {
      mode = 'percent';
      text = text.slice(0, -1);
    }

    const numericText = text.replace(/[^\d.,-]/g, '');
    const numericValue = parseDecimal(numericText);
    let discountAmount = numericValue;
    let discountPercent = null;

    if (mode === 'percent') {
      discountPercent = numericValue;
      discountAmount = gross > 0 ? (gross * discountPercent) / 100 : 0;
    } else if (gross > 0 && numericValue > 0) {
      discountPercent = (numericValue / gross) * 100;
    }

    result.amount = Number.isFinite(discountAmount) && discountAmount > 0 ? discountAmount : 0;
    result.percent = Number.isFinite(discountPercent) ? discountPercent : null;
    result.mode = mode;
    return result;
  }

  function normalizeDiscountInput(row) {
    const discountInput = row.querySelector('[data-field="discount"]');
    if (!discountInput) {
      return;
    }
    const raw = discountInput.value || '';
    if (!raw.trim()) {
      discountInput.value = '';
      return;
    }
    const quantityInput = row.querySelector('[data-field="quantity"]');
    const unitPriceInput = row.querySelector('[data-field="unit_price"]');
    const quantity = parseDecimal(quantityInput ? quantityInput.value : 0);
    const unitPrice = parseDecimal(unitPriceInput ? unitPriceInput.value : 0);
    const gross = quantity * unitPrice;
    const discountInfo = parseDiscount(raw, gross);
    if (discountInfo.amount > 0) {
      discountInput.value = formatForInput(discountInfo.amount);
    } else {
      discountInput.value = '';
    }
  }

  function normalizeAllDiscountInputs() {
    const rows = Array.from(tbody.querySelectorAll('.sales-item-row'));
    rows.forEach((row) => {
      normalizeDiscountInput(row);
    });
  }

  function handleGlobalShortcuts(event) {
    if (
      event.altKey &&
      !event.shiftKey &&
      !event.ctrlKey &&
      !event.metaKey &&
      event.code === 'KeyZ'
    ) {
      event.preventDefault();
      event.stopPropagation();
      const activeRow = document.activeElement
        ? document.activeElement.closest('.sales-item-row')
        : null;
      if (activeRow && table.contains(activeRow)) {
        confirmRow(activeRow, { focusNext: false });
      }
      addNewRow({ focus: true, prefillTerm: '' });
    }
  }

  function recalcRow(row) {
    const deleteCheckbox = row.querySelector('input[name$="-DELETE"]');
    if (deleteCheckbox && deleteCheckbox.checked) {
      row.dataset.quantityValue = '0';
      row.dataset.discountValue = '0';
      row.dataset.grossValue = '0';
      row.dataset.netValue = '0';
      row.dataset.costTotal = '0';
      row.dataset.marginValue = '';
      const lineTotalPlaceholder = row.querySelector('[data-line-total]');
      if (lineTotalPlaceholder) {
        lineTotalPlaceholder.textContent = '0,00';
        lineTotalPlaceholder.classList.add('placeholder');
      }
      const discountPercentEl = row.querySelector('[data-discount-percent]');
      if (discountPercentEl) {
        discountPercentEl.textContent = '—';
        discountPercentEl.classList.add('placeholder');
      }
      const marginEl = row.querySelector('.line-margin');
      if (marginEl) {
        marginEl.textContent = '—';
        marginEl.classList.add('placeholder');
        marginEl.classList.remove('is-negative');
      }
      return;
    }

    const quantityInput = row.querySelector('[data-field="quantity"]');
    const unitPriceInput = row.querySelector('[data-field="unit_price"]');
    const discountInput = row.querySelector('[data-field="discount"]');

    const quantity = parseDecimal(quantityInput ? quantityInput.value : 0);
    const unitPrice = parseDecimal(unitPriceInput ? unitPriceInput.value : 0);
    const gross = quantity * unitPrice;
    const discountInfo = parseDiscount(discountInput ? discountInput.value : '', gross);
    const discount = discountInfo.amount;

    let net = gross - discount;
    if (!Number.isFinite(net) || net < 0) {
      net = 0;
    }

    row.dataset.quantityValue = String(quantity);
    row.dataset.grossValue = String(gross);
    row.dataset.discountValue = String(discount);
    row.dataset.netValue = String(net);

    const lineTotalEl = row.querySelector('[data-line-total]');
    if (lineTotalEl) {
      lineTotalEl.textContent = formatNumber(net);
      if (net > 0) {
        lineTotalEl.classList.remove('placeholder');
      } else {
        lineTotalEl.classList.add('placeholder');
      }
      lineTotalEl.dataset.lineTotal = String(net);
    }

    const discountPercentEl = row.querySelector('[data-discount-percent]');
    let discountPercent = discountInfo.percent;
    if (discountPercent === null && gross > 0 && discount > 0) {
      discountPercent = (discount / gross) * 100;
    }
    if (discountPercentEl) {
      if (discountPercent !== null) {
        discountPercentEl.textContent = formatPercent(discountPercent);
        discountPercentEl.classList.remove('placeholder');
        discountPercentEl.dataset.discountPercent = String(discountPercent);
      } else {
        discountPercentEl.textContent = '—';
        discountPercentEl.classList.add('placeholder');
        discountPercentEl.dataset.discountPercent = '';
      }
    }

    const costPrice = parseDecimal(row.dataset.costPrice || '');
    let costTotal = 0;
    if (costPrice > 0 && quantity > 0) {
      costTotal = costPrice * quantity;
    }
    row.dataset.costTotal = String(costTotal);

    const marginEl = row.querySelector('.line-margin');
    if (marginEl) {
      let marginValue = null;
      if (costPrice > 0 && unitPrice > 0) {
        marginValue = ((unitPrice - costPrice) / unitPrice) * 100;
      }
      if (marginValue !== null) {
        marginEl.textContent = formatPercent(marginValue);
        marginEl.classList.remove('placeholder');
        marginEl.classList.toggle('is-negative', marginValue < 0);
        marginEl.dataset.lineMargin = String(marginValue);
        row.dataset.marginValue = String(marginValue);
      } else {
        const initialMargin = parseDecimal(marginEl.dataset.lineMargin || '');
        if (marginEl.dataset.lineMargin) {
          marginEl.textContent = formatPercent(initialMargin);
          marginEl.classList.toggle('is-negative', initialMargin < 0);
          marginEl.classList.remove('placeholder');
          row.dataset.marginValue = String(initialMargin);
        } else {
          marginEl.textContent = '—';
          marginEl.classList.add('placeholder');
          marginEl.classList.remove('is-negative');
          row.dataset.marginValue = '';
        }
      }
    }
  }

  function recalcSummary() {
    let totalQuantity = 0;
    let totalDiscount = 0;
    let totalGross = 0;
    let totalNet = 0;
    let totalCost = 0;

    rowState.forEach((state, row) => {
      if (!table.contains(row)) {
        rowState.delete(row);
        return;
      }
      const deleteCheckbox = row.querySelector('input[name$="-DELETE"]');
      if (deleteCheckbox && deleteCheckbox.checked) {
        return;
      }
      totalQuantity += parseDecimal(row.dataset.quantityValue);
      totalDiscount += parseDecimal(row.dataset.discountValue);
      totalGross += parseDecimal(row.dataset.grossValue);
      totalNet += parseDecimal(row.dataset.netValue);
      totalCost += parseDecimal(row.dataset.costTotal);
    });

    if (summaryElements.quantity) {
      summaryElements.quantity.textContent = formatNumber(totalQuantity);
    }
    if (summaryElements.discount) {
      summaryElements.discount.textContent = formatNumber(totalDiscount);
    }
    if (summaryElements.gross) {
      summaryElements.gross.textContent = formatNumber(totalGross);
    }
    if (summaryElements.net) {
      summaryElements.net.textContent = formatNumber(totalNet);
    }

    const discountPercentEl = summaryElements.discountPercent;
    if (discountPercentEl) {
      if (totalGross > 0 && totalDiscount > 0) {
        const discountPercent = (totalDiscount / totalGross) * 100;
        discountPercentEl.textContent = formatPercent(discountPercent);
        discountPercentEl.classList.remove('placeholder');
      } else {
        discountPercentEl.textContent = '—';
        discountPercentEl.classList.add('placeholder');
      }
    }

    if (summaryElements.margin) {
      if (totalGross > 0 && totalCost > 0) {
        const marginPercent = ((totalNet - totalCost) / totalGross) * 100;
        summaryElements.margin.textContent = formatPercent(marginPercent);
        summaryElements.margin.classList.remove('placeholder');
        summaryElements.margin.classList.toggle('is-negative', marginPercent < 0);
      } else {
        summaryElements.margin.textContent = '—';
        summaryElements.margin.classList.add('placeholder');
        summaryElements.margin.classList.remove('is-negative');
      }
    }
  }

  function handleEditAction(row) {
    const deleteCheckbox = row.querySelector('input[name$="-DELETE"]');
    if (deleteCheckbox && deleteCheckbox.checked) {
      deleteCheckbox.checked = false;
      deleteCheckbox.dispatchEvent(new Event('change', { bubbles: true }));
    }
    focusRowSearch(row, { selectText: true, scroll: true });
  }

  function handleDeleteAction(row, deleteCheckbox, deleteButton) {
    if (!deleteCheckbox) {
      return;
    }
    if (!deleteCheckbox.checked) {
      const nameDisplay = row.querySelector('[data-product-name-display]');
      const productLabel = nameDisplay && nameDisplay.textContent ? nameDisplay.textContent.trim() : '';
      const message = productLabel
        ? `Remover o item "${productLabel}" do orçamento?`
        : 'Remover este item do orçamento?';
      if (!window.confirm(message)) {
        return;
      }
    }
    deleteCheckbox.checked = !deleteCheckbox.checked;
    deleteCheckbox.dispatchEvent(new Event('change', { bubbles: true }));
    updateDeleteButtonState(deleteButton, deleteCheckbox.checked);
  }

  function updateDeleteButtonState(button, isDeleted) {
    if (!button) {
      return;
    }
    if (isDeleted) {
      button.textContent = 'Restaurar';
      button.classList.remove('is-danger');
      button.classList.add('is-warning');
    } else {
      button.textContent = 'Excluir';
      button.classList.add('is-danger');
      button.classList.remove('is-warning');
    }
  }

  function resetRow(row) {
    if (!row) {
      return;
    }
    const state = rowState.get(row);
    const select = row.querySelector('[data-product-select]');
    const searchInput = row.querySelector('[data-product-search-input]');
    const descriptionInput = row.querySelector('[data-description-field]');
    const unitText = row.querySelector('.unit-text');
    const quantityInput = row.querySelector('[data-field="quantity"]');
    const unitPriceInput = row.querySelector('[data-field="unit_price"]');
    const discountInput = row.querySelector('[data-field="discount"]');
    const deliveryDaysInput = row.querySelector('input[name$="-delivery_days"]');
    const deleteCheckbox = row.querySelector('input[name$="-DELETE"]');

    if (deleteCheckbox && deleteCheckbox.checked) {
      deleteCheckbox.checked = false;
      deleteCheckbox.dispatchEvent(new Event('change', { bubbles: true }));
    }

    if (select) {
      select.value = '';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }

    if (searchInput) {
      searchInput.value = '';
      searchInput.title = '';
    }

    if (descriptionInput) {
      descriptionInput.value = '';
    }

    if (unitText) {
      unitText.textContent = '—';
    }

    if (quantityInput) {
      quantityInput.value = '';
    }
    if (unitPriceInput) {
      unitPriceInput.value = '';
    }
    if (deliveryDaysInput) {
      deliveryDaysInput.value = '';
    }
    if (discountInput) {
      discountInput.value = '';
      applyDiscountLockState(row, true, { force: true, silent: true });
    }

    updateProductDisplay(row, null);

    delete row.dataset.productId;
    delete row.dataset.costPrice;
    delete row.dataset.quantityValue;
    delete row.dataset.discountValue;
    delete row.dataset.grossValue;
    delete row.dataset.netValue;
    delete row.dataset.costTotal;
    delete row.dataset.marginValue;

    if (state) {
      state.lastSearchTerm = '';
      state.confirmedTerm = '';
    }

    recalcRow(row);
  }

  function findDuplicateRows(productId, currentRow) {
    if (!productId) {
      return [];
    }
    return Array.from(tbody.querySelectorAll('.sales-item-row')).filter((row) => {
      if (row === currentRow) {
        return false;
      }
      if (isRowMarkedDeleted(row)) {
        return false;
      }
      const select = row.querySelector('[data-product-select]');
      if (!select || !select.value) {
        return false;
      }
      const rowProductId = row.dataset.productId || select.value;
      return rowProductId === productId;
    });
  }

  function handleDuplicateSelection(row, productId, previousProductId) {
    if (!productId || productId === previousProductId) {
      return false;
    }
    const duplicates = findDuplicateRows(productId, row);
    if (!duplicates.length) {
      return false;
    }

    const quantityInput = row.querySelector('[data-field="quantity"]');
    const quantityValue = parseDecimal(quantityInput ? quantityInput.value : 0) || 0;
    const increment = quantityValue > 0 ? quantityValue : 1;
    const message = `Este produto já foi lançado no orçamento. Deseja somar ${formatNumber(increment)} à quantidade existente? Clique em Cancelar para manter como item separado.`;
    if (!window.confirm(message)) {
      return false;
    }

    const targetRow = duplicates[0];
    const targetQuantityInput = targetRow.querySelector('[data-field="quantity"]');
    if (targetQuantityInput) {
      const current = parseDecimal(targetQuantityInput.value);
      const updated = current + increment;
      targetQuantityInput.value = formatInputValue(updated);
      targetQuantityInput.dispatchEvent(new Event('input', { bubbles: true }));
      targetQuantityInput.dispatchEvent(new Event('change', { bubbles: true }));
      recalcRow(targetRow);
    }

    resetRow(row);
    recalcSummary();
    focusRowSearch(row, { selectText: true, scroll: false });
    return true;
  }

  function formatInputValue(value) {
    if (!Number.isFinite(value) || value === null) {
      return '';
    }
    return value.toLocaleString('en-US', {
      useGrouping: false,
      maximumFractionDigits: 4,
    });
  }

  function isRowMarkedDeleted(row) {
    const deleteCheckbox = row && row.querySelector('input[name$="-DELETE"]');
    return !!(deleteCheckbox && deleteCheckbox.checked);
  }

  function setupDraftsToggle() {
    const toggle = document.querySelector('[data-drafts-toggle]');
    const sidebar = document.querySelector('[data-drafts-panel]');
    const workspace = document.querySelector('.sales-workspace');
    if (!toggle || !sidebar || !workspace) {
      return;
    }
    const label = toggle.querySelector('[data-toggle-label]');
    const icon = toggle.querySelector('[data-lucide]');

    const updateState = (collapsed) => {
      toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
      if (label) {
        label.textContent = collapsed ? 'Mostrar esboços' : 'Ocultar esboços';
      }
      if (icon) {
        icon.setAttribute('data-lucide', collapsed ? 'chevron-right' : 'chevron-left');
        if (window.lucide) {
          window.lucide.createIcons();
        }
      }
    };

    toggle.addEventListener('click', () => {
      const collapsed = sidebar.classList.toggle('is-collapsed');
      workspace.classList.toggle('drafts-collapsed', collapsed);
      updateState(collapsed);
    });

    updateState(false);
  }
})();
