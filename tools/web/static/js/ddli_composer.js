/**
 * BMWP2000 DDLI Composer & Master DID Editor Client Controller
 * Conforms to ISO 14230-3 (KWP2000) & ISO 15765-2 (ISO-TP)
 */

(function () {
  'use strict';

  // Application State
  const state = {
    dids: {},          // Map of DID key -> DID definition
    ddlis: [],         // Array of train definitions (excluding _schema_guide)
    schemaGuides: {
      dids: null,
      ddlis: null
    },
    currentTrainIdx: 0,
    searchPaletteTerm: '',
    searchDidsTerm: '',
    didsPath: '',
    ddlisPath: '',
  };

  // DOM Element References
  const els = {
    tabBtnComposer: document.getElementById('tab-btn-composer'),
    tabBtnDids: document.getElementById('tab-btn-dids'),
    tabComposer: document.getElementById('tab-composer'),
    tabDids: document.getElementById('tab-dids'),

    badgeDdlis: document.getElementById('badge-ddlis-file'),
    badgeDids: document.getElementById('badge-dids-file'),

    selectTrain: document.getElementById('select-ddli-train'),
    btnNewTrain: document.getElementById('btn-new-train'),
    btnDeleteTrain: document.getElementById('btn-delete-train'),
    btnSaveDdlis: document.getElementById('btn-save-ddlis'),

    inputTrainLocalId: document.getElementById('input-train-local-id'),
    inputTrainName: document.getElementById('input-train-name'),
    selectTrainMode: document.getElementById('select-train-mode'),

    metricDidCount: document.getElementById('metric-did-count'),
    metricPayloadBytes: document.getElementById('metric-payload-bytes'),
    metricResponseBytes: document.getElementById('metric-response-bytes'),
    metricFraming: document.getElementById('metric-framing'),
    metricFrameCount: document.getElementById('metric-frame-count'),

    searchPalette: document.getElementById('search-palette'),
    paletteList: document.getElementById('palette-did-list'),
    sequenceList: document.getElementById('active-sequence-list'),

    searchDids: document.getElementById('search-dids'),
    tbodyDids: document.getElementById('tbody-dids'),
    btnAddDid: document.getElementById('btn-add-did'),
    btnSaveDids: document.getElementById('btn-save-dids'),

    modalDid: document.getElementById('modal-did'),
    modalTitle: document.getElementById('modal-did-title'),
    formDid: document.getElementById('form-did'),
    btnCloseModal: document.getElementById('btn-close-modal'),
    btnCancelModal: document.getElementById('btn-cancel-modal'),

    didOriginalName: document.getElementById('did-original-name'),
    inputDidName: document.getElementById('input-did-name'),
    inputDidHex: document.getElementById('input-did-hex'),
    selectDidSize: document.getElementById('select-did-size'),
    inputDidPosition: document.getElementById('input-did-position'),
    inputDidMul: document.getElementById('input-did-mul'),
    inputDidDiv: document.getElementById('input-did-div'),
    inputDidAdd: document.getElementById('input-did-add'),
    inputDidUnit: document.getElementById('input-did-unit'),
    formulaPreviewText: document.getElementById('formula-preview-text'),

    footerStatusMsg: document.getElementById('footer-status-msg'),
  };

  /**
   * Updates footer status text
   */
  function setStatus(msg) {
    if (els.footerStatusMsg) {
      els.footerStatusMsg.textContent = msg;
    }
  }

  /**
   * Initializes event bindings and loads initial configuration
   */
  async function init() {
    setupTabs();
    setupModalEvents();
    setupTrainControlEvents();
    setupSearchEvents();

    await loadConfiguration();
  }

  /**
   * Tab Navigation Setup
   */
  function setupTabs() {
    els.tabBtnComposer.addEventListener('click', () => switchTab('composer'));
    els.tabBtnDids.addEventListener('click', () => switchTab('dids'));
  }

  function switchTab(tabId) {
    if (tabId === 'composer') {
      els.tabBtnComposer.classList.add('active');
      els.tabBtnComposer.setAttribute('aria-selected', 'true');
      els.tabBtnDids.classList.remove('active');
      els.tabBtnDids.setAttribute('aria-selected', 'false');

      els.tabComposer.classList.add('active');
      els.tabDids.classList.remove('active');
    } else {
      els.tabBtnDids.classList.add('active');
      els.tabBtnDids.setAttribute('aria-selected', 'true');
      els.tabBtnComposer.classList.remove('active');
      els.tabBtnComposer.setAttribute('aria-selected', 'false');

      els.tabDids.classList.add('active');
      els.tabComposer.classList.remove('active');
    }
  }

  /**
   * Fetches dids.json and ddlis.json from backend
   */
  async function loadConfiguration() {
    setStatus('Loading configuration files...');
    try {
      const resp = await fetch('/api/config');
      if (!resp.ok) {
        throw new Error(`Failed to load config: HTTP ${resp.status}`);
      }
      const data = await resp.json();

      // Separate schema guide from DIDs
      state.dids = {};
      state.schemaGuides.dids = null;
      for (const [k, v] of Object.entries(data.dids || {})) {
        if (k === '_schema_guide') {
          state.schemaGuides.dids = v;
        } else {
          state.dids[k] = v;
        }
      }

      // Separate schema guide from DDLIs
      state.ddlis = [];
      state.schemaGuides.ddlis = null;
      for (const item of (data.ddlis || [])) {
        if (item._schema_guide) {
          state.schemaGuides.ddlis = item._schema_guide;
        } else {
          state.ddlis.push(item);
        }
      }

      state.didsPath = data.dids_path || 'config/dids.json';
      state.ddlisPath = data.ddlis_path || 'config/ddlis.json';

      // Update badges
      if (els.badgeDdlis) els.badgeDdlis.textContent = state.ddlisPath.split(/[\\/]/).pop();
      if (els.badgeDids) els.badgeDids.textContent = state.didsPath.split(/[\\/]/).pop();

      // Render UI
      renderTrainSelector();
      renderActiveTrain();
      renderPalette();
      renderDidsTable();

      setStatus(`Loaded ${Object.keys(state.dids).length} DIDs, ${state.ddlis.length} DDLI trains`);
    } catch (err) {
      console.error(err);
      setStatus(`Error: ${err.message}`);
      if (window.showToast) {
        window.showToast(`Error loading config: ${err.message}`, 'error');
      }
    }
  }

  /**
   * Renders the DDLI Train dropdown selector
   */
  function renderTrainSelector() {
    els.selectTrain.innerHTML = '';
    if (state.ddlis.length === 0) {
      const opt = document.createElement('option');
      opt.value = '-1';
      opt.textContent = '(No DDLI trains defined)';
      els.selectTrain.appendChild(opt);
      return;
    }

    state.ddlis.forEach((train, idx) => {
      const opt = document.createElement('option');
      opt.value = idx;
      opt.textContent = `${train.local_id || '0x??'} - ${train.name || 'Unnamed'} (${(train.dids || []).length} DIDs)`;
      if (idx === state.currentTrainIdx) {
        opt.selected = true;
      }
      els.selectTrain.appendChild(opt);
    });
  }

  /**
   * Retrieves active train object
   */
  function getCurrentTrain() {
    if (state.currentTrainIdx >= 0 && state.currentTrainIdx < state.ddlis.length) {
      return state.ddlis[state.currentTrainIdx];
    }
    return null;
  }

  /**
   * Renders metadata and DID sequence for active train
   */
  function renderActiveTrain() {
    const train = getCurrentTrain();
    if (!train) {
      els.inputTrainLocalId.value = '';
      els.inputTrainName.value = '';
      els.selectTrainMode.value = 'fast';
      els.sequenceList.innerHTML = '<div class="empty-sequence-msg">No train selected. Click "+ New DDLI" to create one.</div>';
      updateFramingMetrics([]);
      return;
    }

    els.inputTrainLocalId.value = train.local_id || '';
    els.inputTrainName.value = train.name || '';
    els.selectTrainMode.value = train.transmission_mode || 'fast';

    renderSequenceList(train.dids || []);
    updateFramingMetrics(train.dids || []);
  }

  /**
   * Renders the ordered list of DIDs in active train
   */
  function renderSequenceList(didsSeq) {
    els.sequenceList.innerHTML = '';
    if (!didsSeq || didsSeq.length === 0) {
      els.sequenceList.innerHTML = '<div class="empty-sequence-msg">Train sequence is empty. Click "+ Add" on available DIDs from the left palette to add signals.</div>';
      return;
    }

    didsSeq.forEach((didKey, idx) => {
      const didDef = state.dids[didKey];
      const item = document.createElement('div');
      item.className = 'sequence-item';

      const hexId = didDef ? didDef.id : 'Unknown';
      const sizeBytes = didDef ? didDef.memory_size : 1;
      const unit = didDef && didDef.unit ? `[${didDef.unit}]` : '';

      item.innerHTML = `
        <div class="sequence-item-left">
          <span class="seq-num-badge">${idx + 1}</span>
          <div class="sequence-item-details">
            <span class="sequence-item-name">${escapeHtml(didKey)}</span>
            <div class="sequence-item-meta">
              <span class="palette-meta-tag mono">${escapeHtml(hexId)}</span>
              <span>${sizeBytes} ${sizeBytes === 1 ? 'byte' : 'bytes'}</span>
              <span>${escapeHtml(unit)}</span>
            </div>
          </div>
        </div>
        <div class="sequence-actions">
          <button type="button" class="btn-seq-move" data-action="up" data-idx="${idx}" title="Move Up" ${idx === 0 ? 'disabled' : ''}>▲</button>
          <button type="button" class="btn-seq-move" data-action="down" data-idx="${idx}" title="Move Down" ${idx === didsSeq.length - 1 ? 'disabled' : ''}>▼</button>
          <button type="button" class="btn-seq-remove" data-action="remove" data-idx="${idx}" title="Remove DID">✕</button>
        </div>
      `;

      els.sequenceList.appendChild(item);
    });

    // Event delegation for move/remove actions
    els.sequenceList.querySelectorAll('.btn-seq-move, .btn-seq-remove').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const action = btn.dataset.action;
        const idx = parseInt(btn.dataset.idx, 10);
        handleSequenceAction(action, idx);
      });
    });
  }

  function handleSequenceAction(action, idx) {
    const train = getCurrentTrain();
    if (!train || !train.dids) return;

    if (action === 'up' && idx > 0) {
      const temp = train.dids[idx];
      train.dids[idx] = train.dids[idx - 1];
      train.dids[idx - 1] = temp;
    } else if (action === 'down' && idx < train.dids.length - 1) {
      const temp = train.dids[idx];
      train.dids[idx] = train.dids[idx + 1];
      train.dids[idx + 1] = temp;
    } else if (action === 'remove') {
      train.dids.splice(idx, 1);
    }

    renderTrainSelector();
    renderActiveTrain();
  }

  /**
   * Updates ISO-TP / CAN Frame Telemetry Metrics
   */
  function updateFramingMetrics(didsSeq) {
    let payloadBytes = 0;
    (didsSeq || []).forEach(k => {
      const def = state.dids[k];
      payloadBytes += def ? (def.memory_size || 1) : 1;
    });

    const didCount = (didsSeq || []).length;
    // ISO 14230-3 positive response: 1 byte SID (0x61) + 1 byte local_id + payload bytes
    const responseBytes = payloadBytes + 2;

    els.metricDidCount.textContent = didCount;
    els.metricPayloadBytes.textContent = `${payloadBytes} B`;
    els.metricResponseBytes.textContent = `${responseBytes} B`;

    // ISO 15765-2 standard CAN (11-bit ID):
    // Single Frame (SF): up to 7 payload data bytes in a single 8-byte CAN frame (Byte 0 = PCI 0x0L)
    if (responseBytes <= 7) {
      els.metricFraming.textContent = 'Single Frame (SF)';
      els.metricFraming.className = 'telemetry-val badge-framing sf';
      els.metricFrameCount.textContent = '1 CAN Frame';
    } else {
      // First Frame (FF): Byte 0-1 = PCI + length (12-bit). Carries 6 bytes of data.
      // Consecutive Frames (CF): Byte 0 = PCI + SN (4-bit). Carries 7 bytes of data each.
      const remainingBytes = responseBytes - 6;
      const cfCount = Math.ceil(remainingBytes / 7);
      const totalFrames = 1 + cfCount;

      els.metricFraming.textContent = `Multi-Frame (1 FF + ${cfCount} CF)`;
      els.metricFraming.className = 'telemetry-val badge-framing mf';
      els.metricFrameCount.textContent = `${totalFrames} CAN Frames`;
    }
  }

  /**
   * Renders Available Master DIDs Palette (Left Column)
   */
  function renderPalette() {
    els.paletteList.innerHTML = '';
    const term = state.searchPaletteTerm.toLowerCase().trim();

    const sortedKeys = Object.keys(state.dids).sort((a, b) => a.localeCompare(b));
    let matchedCount = 0;

    sortedKeys.forEach(didKey => {
      const def = state.dids[didKey];
      const hexId = def.id || '';
      const unit = def.unit || '';

      if (term) {
        const matchesKey = didKey.toLowerCase().includes(term);
        const matchesHex = hexId.toLowerCase().includes(term);
        const matchesUnit = unit.toLowerCase().includes(term);
        if (!matchesKey && !matchesHex && !matchesUnit) return;
      }

      matchedCount++;
      const item = document.createElement('div');
      item.className = 'palette-item';

      const sizeStr = `${def.memory_size || 1}B`;

      item.innerHTML = `
        <div class="palette-item-info">
          <span class="palette-item-name">${escapeHtml(didKey)}</span>
          <div class="palette-item-meta">
            <span class="palette-meta-tag">${escapeHtml(hexId)}</span>
            <span class="palette-meta-tag">${sizeStr}</span>
            ${unit ? `<span class="palette-meta-tag">${escapeHtml(unit)}</span>` : ''}
          </div>
        </div>
        <button type="button" class="btn btn-secondary btn-sm" data-did="${escapeHtml(didKey)}">
          <span>➕ Add</span>
        </button>
      `;

      item.querySelector('button').addEventListener('click', () => {
        addDidToActiveTrain(didKey);
      });

      els.paletteList.appendChild(item);
    });

    if (matchedCount === 0) {
      els.paletteList.innerHTML = '<div class="empty-sequence-msg">No matching Master DIDs found.</div>';
    }
  }

  function addDidToActiveTrain(didKey) {
    const train = getCurrentTrain();
    if (!train) {
      if (window.showToast) window.showToast('Please select or create a DDLI train first.', 'warning');
      return;
    }

    if (!train.dids) {
      train.dids = [];
    }

    train.dids.push(didKey);
    renderTrainSelector();
    renderActiveTrain();
    if (window.showToast) {
      window.showToast(`Added ${didKey} to train sequence.`, 'info');
    }
  }

  /**
   * Renders Master DIDs Table (Tab 2)
   */
  function renderDidsTable() {
    els.tbodyDids.innerHTML = '';
    const term = state.searchDidsTerm.toLowerCase().trim();
    const sortedKeys = Object.keys(state.dids).sort((a, b) => a.localeCompare(b));

    sortedKeys.forEach(didKey => {
      const def = state.dids[didKey];
      const hexId = def.id || '';
      const unit = def.unit || '';

      if (term) {
        const matchesKey = didKey.toLowerCase().includes(term);
        const matchesHex = hexId.toLowerCase().includes(term);
        const matchesUnit = unit.toLowerCase().includes(term);
        if (!matchesKey && !matchesHex && !matchesUnit) return;
      }

      const tr = document.createElement('tr');
      const formulaStr = `((raw * ${def.mul ?? 1}) / ${def.div ?? 1}) + ${def.add ?? 0}`;

      tr.innerHTML = `
        <td><strong>${escapeHtml(didKey)}</strong></td>
        <td class="mono">${escapeHtml(hexId)}</td>
        <td><span class="badge-size">${def.memory_size || 1} byte${def.memory_size > 1 ? 's' : ''}</span></td>
        <td>${def.position ?? 1}</td>
        <td>${def.mul ?? 1}</td>
        <td>${def.div ?? 1}</td>
        <td>${def.add ?? 0}</td>
        <td>${escapeHtml(unit)}</td>
        <td><span class="formula-chip">${escapeHtml(formulaStr)}</span></td>
        <td>
          <div class="table-actions">
            <button type="button" class="btn btn-secondary btn-sm" data-edit="${escapeHtml(didKey)}">✏️ Edit</button>
            <button type="button" class="btn btn-danger btn-sm" data-del="${escapeHtml(didKey)}">🗑️</button>
          </div>
        </td>
      `;

      tr.querySelector('[data-edit]').addEventListener('click', () => openEditDidModal(didKey));
      tr.querySelector('[data-del]').addEventListener('click', () => deleteDid(didKey));

      els.tbodyDids.appendChild(tr);
    });
  }

  /**
   * Train Controls Setup
   */
  function setupTrainControlEvents() {
    // Train selector change
    els.selectTrain.addEventListener('change', (e) => {
      state.currentTrainIdx = parseInt(e.target.value, 10);
      renderActiveTrain();
    });

    // Metadata live edit listeners
    els.inputTrainLocalId.addEventListener('input', (e) => {
      const train = getCurrentTrain();
      if (train) {
        train.local_id = e.target.value.trim();
        renderTrainSelector();
      }
    });

    els.inputTrainName.addEventListener('input', (e) => {
      const train = getCurrentTrain();
      if (train) {
        train.name = e.target.value.trim();
        renderTrainSelector();
      }
    });

    els.selectTrainMode.addEventListener('change', (e) => {
      const train = getCurrentTrain();
      if (train) {
        train.transmission_mode = e.target.value;
      }
    });

    // New Train button
    els.btnNewTrain.addEventListener('click', () => {
      // Find next free local_id e.g. 0xF0, 0xF1, etc.
      let nextId = 0xF0;
      const existingIds = new Set(state.ddlis.map(t => parseInt(t.local_id, 16)));
      while (existingIds.has(nextId) && nextId <= 0xFE) {
        nextId++;
      }
      const hexStr = '0x' + nextId.toString(16).toUpperCase();

      const newTrain = {
        local_id: hexStr,
        name: `Custom_Train_${state.ddlis.length + 1}`,
        transmission_mode: 'fast',
        dids: []
      };

      state.ddlis.push(newTrain);
      state.currentTrainIdx = state.ddlis.length - 1;
      renderTrainSelector();
      renderActiveTrain();
      if (window.showToast) window.showToast(`Created new DDLI train ${hexStr}.`, 'success');
    });

    // Delete Train button
    els.btnDeleteTrain.addEventListener('click', () => {
      const train = getCurrentTrain();
      if (!train) return;
      if (!confirm(`Are you sure you want to delete train "${train.name || train.local_id}"?`)) return;

      state.ddlis.splice(state.currentTrainIdx, 1);
      state.currentTrainIdx = Math.max(0, state.ddlis.length - 1);
      renderTrainSelector();
      renderActiveTrain();
      if (window.showToast) window.showToast('Train deleted.', 'info');
    });

    // Save DDLIs button
    els.btnSaveDdlis.addEventListener('click', saveDdlis);
    els.btnSaveDids.addEventListener('click', saveDids);
  }

  /**
   * Live Search Events
   */
  function setupSearchEvents() {
    els.searchPalette.addEventListener('input', (e) => {
      state.searchPaletteTerm = e.target.value;
      renderPalette();
    });

    els.searchDids.addEventListener('input', (e) => {
      state.searchDidsTerm = e.target.value;
      renderDidsTable();
    });
  }

  /**
   * Modal Setup & Form Handling
   */
  function setupModalEvents() {
    els.btnAddDid.addEventListener('click', () => openAddDidModal());
    els.btnCloseModal.addEventListener('click', closeModal);
    els.btnCancelModal.addEventListener('click', closeModal);

    // Live preview on formula input changes
    [els.inputDidMul, els.inputDidDiv, els.inputDidAdd, els.inputDidUnit].forEach(input => {
      input.addEventListener('input', updateFormulaPreview);
    });

    // Form submit
    els.formDid.addEventListener('submit', (e) => {
      e.preventDefault();
      applyModalDid();
    });
  }

  function updateFormulaPreview() {
    const mul = els.inputDidMul.value || 1;
    const div = els.inputDidDiv.value || 1;
    const add = els.inputDidAdd.value || 0;
    const unit = els.inputDidUnit.value.trim();
    els.formulaPreviewText.textContent = `((raw * ${mul}) / ${div}) + ${add} ${unit ? `[${unit}]` : ''}`;
  }

  function openAddDidModal() {
    els.modalTitle.textContent = 'Add New Master Data Identifier (DID)';
    els.didOriginalName.value = '';
    els.inputDidName.value = '';
    els.inputDidName.disabled = false;
    els.inputDidHex.value = '0x';
    els.selectDidSize.value = '1';
    els.inputDidPosition.value = '1';
    els.inputDidMul.value = '1';
    els.inputDidDiv.value = '1';
    els.inputDidAdd.value = '0';
    els.inputDidUnit.value = '';

    updateFormulaPreview();
    els.modalDid.classList.add('open');
    els.inputDidName.focus();
  }

  function openEditDidModal(didKey) {
    const def = state.dids[didKey];
    if (!def) return;

    els.modalTitle.textContent = `Edit DID: ${didKey}`;
    els.didOriginalName.value = didKey;
    els.inputDidName.value = didKey;
    els.inputDidName.disabled = false;
    els.inputDidHex.value = def.id || '';
    els.selectDidSize.value = String(def.memory_size || 1);
    els.inputDidPosition.value = String(def.position ?? 1);
    els.inputDidMul.value = String(def.mul ?? 1);
    els.inputDidDiv.value = String(def.div ?? 1);
    els.inputDidAdd.value = String(def.add ?? 0);
    els.inputDidUnit.value = def.unit || '';

    updateFormulaPreview();
    els.modalDid.classList.add('open');
    els.inputDidHex.focus();
  }

  function closeModal() {
    els.modalDid.classList.remove('open');
  }

  function applyModalDid() {
    const origName = els.didOriginalName.value.trim();
    const newName = els.inputDidName.value.trim();
    const hexId = els.inputDidHex.value.trim();
    const size = parseInt(els.selectDidSize.value, 10);
    const pos = parseInt(els.inputDidPosition.value, 10) || 1;
    const mul = parseInt(els.inputDidMul.value, 10) || 1;
    const div = parseInt(els.inputDidDiv.value, 10) || 1;
    const add = parseInt(els.inputDidAdd.value, 10) || 0;
    const unit = els.inputDidUnit.value.trim();

    if (!newName) {
      alert('DID Name is required.');
      return;
    }

    if (!/^0x[0-9a-fA-F]{2,6}$/.test(hexId)) {
      alert('Hex Identifier must be in format 0xXXXX (e.g. 0x580C).');
      return;
    }

    if (div === 0) {
      alert('Formula Divisor cannot be zero.');
      return;
    }

    // Check key renaming collisions
    if (origName && origName !== newName) {
      if (state.dids[newName]) {
        alert(`A DID with name "${newName}" already exists.`);
        return;
      }
      delete state.dids[origName];
      // Update references in active trains
      state.ddlis.forEach(train => {
        if (train.dids) {
          train.dids = train.dids.map(k => k === origName ? newName : k);
        }
      });
    } else if (!origName && state.dids[newName]) {
      alert(`A DID with name "${newName}" already exists.`);
      return;
    }

    state.dids[newName] = {
      id: hexId,
      memory_size: size,
      position: pos,
      mul: mul,
      div: div,
      add: add,
      unit: unit,
    };

    closeModal();
    renderPalette();
    renderActiveTrain();
    renderDidsTable();

    if (window.showToast) {
      window.showToast(`Saved DID "${newName}". Click "Save dids.json" to persist.`, 'success');
    }
  }

  function deleteDid(didKey) {
    if (!confirm(`Are you sure you want to delete Master DID "${didKey}"?`)) return;

    delete state.dids[didKey];
    // Remove from any train sequences
    state.ddlis.forEach(train => {
      if (train.dids) {
        train.dids = train.dids.filter(k => k !== didKey);
      }
    });

    renderPalette();
    renderActiveTrain();
    renderDidsTable();
    if (window.showToast) {
      window.showToast(`Deleted DID "${didKey}".`, 'info');
    }
  }

  /**
   * Persists ddlis.json to Backend
   */
  async function saveDdlis() {
    setStatus('Saving ddlis.json...');
    try {
      // Re-compose list with schema guide if available
      const payload = [];
      if (state.schemaGuides.ddlis) {
        payload.push({ _schema_guide: state.schemaGuides.ddlis });
      }
      payload.push(...state.ddlis);

      const resp = await fetch('/api/ddlis', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ddlis: payload })
      });

      if (!resp.ok) {
        const errJson = await resp.json().catch(() => ({}));
        throw new Error(errJson.error || `HTTP ${resp.status}`);
      }

      const res = await resp.json();
      setStatus(`Saved ddlis.json successfully (Backup: ${res.backup || 'created'})`);
      if (window.showToast) {
        window.showToast('ddlis.json saved successfully! Backup created.', 'success');
      }
    } catch (err) {
      console.error(err);
      setStatus(`Failed to save ddlis.json: ${err.message}`);
      if (window.showToast) {
        window.showToast(`Error saving ddlis.json: ${err.message}`, 'error');
      }
    }
  }

  /**
   * Persists dids.json to Backend
   */
  async function saveDids() {
    setStatus('Saving dids.json...');
    try {
      // Re-compose object with schema guide if available
      const payload = {};
      if (state.schemaGuides.dids) {
        payload._schema_guide = state.schemaGuides.dids;
      }
      for (const [k, v] of Object.entries(state.dids)) {
        payload[k] = v;
      }

      const resp = await fetch('/api/dids', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dids: payload })
      });

      if (!resp.ok) {
        const errJson = await resp.json().catch(() => ({}));
        throw new Error(errJson.error || `HTTP ${resp.status}`);
      }

      const res = await resp.json();
      setStatus(`Saved dids.json successfully (Backup: ${res.backup || 'created'})`);
      if (window.showToast) {
        window.showToast('dids.json saved successfully! Backup created.', 'success');
      }
    } catch (err) {
      console.error(err);
      setStatus(`Failed to save dids.json: ${err.message}`);
      if (window.showToast) {
        window.showToast(`Error saving dids.json: ${err.message}`, 'error');
      }
    }
  }

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Initialize on DOM load
  document.addEventListener('DOMContentLoaded', init);
})();
