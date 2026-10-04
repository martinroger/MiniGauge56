/**
 * BMWP2000 LID Composer & Master CID Editor Client Controller
 * Conforms to BMW-FAST-over-CAN, ISO 14230-3 (KWP2000) & ISO 15765-2 (ISO-TP)
 */

(function () {
  'use strict';

  // Application State
  const state = {
    cids: {},          // Map of CID key -> CID definition
    lids: [],          // Array of train definitions (excluding _schema_guide)
    schemaGuides: {
      cids: null,
      lids: null
    },
    currentTrainIdx: 0,
    searchPaletteTerm: '',
    searchCidsTerm: '',
    cidsPath: '',
    lidsPath: '',
  };

  // DOM Element References
  const els = {
    tabBtnComposer: document.getElementById('tab-btn-composer'),
    tabBtnCids: document.getElementById('tab-btn-cids'),
    tabComposer: document.getElementById('tab-composer'),
    tabCids: document.getElementById('tab-cids'),

    badgeLids: document.getElementById('badge-lids-file'),
    badgeCids: document.getElementById('badge-cids-file'),

    selectTrain: document.getElementById('select-lid-train'),
    btnNewTrain: document.getElementById('btn-new-train'),
    btnDeleteTrain: document.getElementById('btn-delete-train'),
    btnSaveLids: document.getElementById('btn-save-lids'),

    inputTrainLocalId: document.getElementById('input-train-local-id'),
    inputTrainName: document.getElementById('input-train-name'),
    selectTrainMode: document.getElementById('select-train-mode'),

    metricCidCount: document.getElementById('metric-cid-count'),
    metricPayloadBytes: document.getElementById('metric-payload-bytes'),
    metricResponseBytes: document.getElementById('metric-response-bytes'),
    metricFraming: document.getElementById('metric-framing'),
    metricFrameCount: document.getElementById('metric-frame-count'),

    searchPalette: document.getElementById('search-palette'),
    paletteList: document.getElementById('palette-cid-list'),
    sequenceList: document.getElementById('active-sequence-list'),

    searchCids: document.getElementById('search-cids'),
    tbodyCids: document.getElementById('tbody-cids'),
    btnAddCid: document.getElementById('btn-add-cid'),
    btnSaveCids: document.getElementById('btn-save-cids'),

    modalCid: document.getElementById('modal-cid'),
    modalTitle: document.getElementById('modal-cid-title'),
    formCid: document.getElementById('form-cid'),
    btnCloseModal: document.getElementById('btn-close-modal'),
    btnCancelModal: document.getElementById('btn-cancel-modal'),

    cidOriginalName: document.getElementById('cid-original-name'),
    inputCidName: document.getElementById('input-cid-name'),
    inputCidHex: document.getElementById('input-cid-hex'),
    inputCidDesc: document.getElementById('input-cid-desc'),
    selectCidSize: document.getElementById('select-cid-size'),
    inputCidSigned: document.getElementById('input-cid-signed'),
    inputCidPosition: document.getElementById('input-cid-position'),
    inputCidMul: document.getElementById('input-cid-mul'),
    inputCidDiv: document.getElementById('input-cid-div'),
    inputCidAdd: document.getElementById('input-cid-add'),
    inputCidUnit: document.getElementById('input-cid-unit'),
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
    els.tabBtnCids.addEventListener('click', () => switchTab('cids'));
  }

  function switchTab(tabId) {
    if (tabId === 'composer') {
      els.tabBtnComposer.classList.add('active');
      els.tabBtnComposer.setAttribute('aria-selected', 'true');
      els.tabBtnCids.classList.remove('active');
      els.tabBtnCids.setAttribute('aria-selected', 'false');

      els.tabComposer.classList.add('active');
      els.tabCids.classList.remove('active');
    } else {
      els.tabBtnCids.classList.add('active');
      els.tabBtnCids.setAttribute('aria-selected', 'true');
      els.tabBtnComposer.classList.remove('active');
      els.tabBtnComposer.setAttribute('aria-selected', 'false');

      els.tabCids.classList.add('active');
      els.tabComposer.classList.remove('active');
    }
  }

  /**
   * Fetches cids.json and lids.json from backend
   */
  async function loadConfiguration() {
    setStatus('Loading configuration files...');
    try {
      const resp = await fetch('/api/config');
      if (!resp.ok) {
        throw new Error(`Failed to load config: HTTP ${resp.status}`);
      }
      const data = await resp.json();

      // Separate schema guide from CIDs
      state.cids = {};
      state.schemaGuides.cids = null;
      for (const [k, v] of Object.entries(data.cids || {})) {
        if (k === '_schema_guide') {
          state.schemaGuides.cids = v;
        } else {
          state.cids[k] = v;
        }
      }

      // Separate schema guide from LIDs
      state.lids = [];
      state.schemaGuides.lids = null;
      for (const item of (data.lids || [])) {
        if (item._schema_guide) {
          state.schemaGuides.lids = item._schema_guide;
        } else {
          state.lids.push(item);
        }
      }

      state.cidsPath = data.cids_path || 'config/cids.json';
      state.lidsPath = data.lids_path || 'config/lids.json';

      // Update badges
      if (els.badgeLids) els.badgeLids.textContent = state.lidsPath.split(/[\\/]/).pop();
      if (els.badgeCids) els.badgeCids.textContent = state.cidsPath.split(/[\\/]/).pop();

      // Render UI
      renderTrainSelector();
      renderActiveTrain();
      renderPalette();
      renderCidsTable();

      setStatus(`Loaded ${Object.keys(state.cids).length} CIDs, ${state.lids.length} LID trains`);
    } catch (err) {
      console.error(err);
      setStatus(`Error: ${err.message}`);
      if (window.showToast) {
        window.showToast(`Error loading config: ${err.message}`, 'error');
      }
    }
  }

  /**
   * Renders the LID Train dropdown selector
   */
  function renderTrainSelector() {
    els.selectTrain.innerHTML = '';
    if (state.lids.length === 0) {
      const opt = document.createElement('option');
      opt.value = '-1';
      opt.textContent = '(No LID trains defined)';
      els.selectTrain.appendChild(opt);
      return;
    }

    state.lids.forEach((train, idx) => {
      const opt = document.createElement('option');
      opt.value = idx;
      opt.textContent = `${train.local_id || '0x??'} - ${train.name || 'Unnamed'} (${(train.cids || []).length} CIDs)`;
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
    if (state.currentTrainIdx >= 0 && state.currentTrainIdx < state.lids.length) {
      return state.lids[state.currentTrainIdx];
    }
    return null;
  }

  /**
   * Renders metadata and CID sequence for active train
   */
  function renderActiveTrain() {
    const train = getCurrentTrain();
    if (!train) {
      els.inputTrainLocalId.value = '';
      els.inputTrainName.value = '';
      els.selectTrainMode.value = 'fast';
      els.sequenceList.innerHTML = '<div class="empty-sequence-msg">No train selected. Click "+ New LID" to create one.</div>';
      updateFramingMetrics([]);
      return;
    }

    els.inputTrainLocalId.value = train.local_id || '';
    els.inputTrainName.value = train.name || '';
    els.selectTrainMode.value = train.transmission_mode || 'fast';

    renderSequenceList(train.cids || []);
    updateFramingMetrics(train.cids || []);
  }

  /**
   * Renders the ordered list of CIDs in active train
   */
  function renderSequenceList(cidsSeq) {
    els.sequenceList.innerHTML = '';
    if (!cidsSeq || cidsSeq.length === 0) {
      els.sequenceList.innerHTML = '<div class="empty-sequence-msg">Train sequence is empty. Click "+ Add" on available CIDs from the left palette to add signals.</div>';
      return;
    }

    cidsSeq.forEach((cidKey, idx) => {
      const cidDef = state.cids[cidKey];
      const item = document.createElement('div');
      item.className = 'sequence-item';

      const hexId = cidDef ? cidDef.id : 'Unknown';
      const sizeBytes = cidDef ? cidDef.memory_size : 1;
      const unit = cidDef && cidDef.unit ? `[${cidDef.unit}]` : '';

      item.innerHTML = `
        <div class="sequence-item-left">
          <span class="seq-num-badge">${idx + 1}</span>
          <div class="sequence-item-details">
            <span class="sequence-item-name">${escapeHtml(cidKey)}</span>
            <div class="sequence-item-meta">
              <span class="palette-meta-tag mono">${escapeHtml(hexId)}</span>
              <span>${sizeBytes} ${sizeBytes === 1 ? 'byte' : 'bytes'}</span>
              <span>${escapeHtml(unit)}</span>
            </div>
          </div>
        </div>
        <div class="sequence-actions">
          <button type="button" class="btn-seq-move" data-action="up" data-idx="${idx}" title="Move Up" ${idx === 0 ? 'disabled' : ''}>▲</button>
          <button type="button" class="btn-seq-move" data-action="down" data-idx="${idx}" title="Move Down" ${idx === cidsSeq.length - 1 ? 'disabled' : ''}>▼</button>
          <button type="button" class="btn-seq-remove" data-action="remove" data-idx="${idx}" title="Remove CID">✕</button>
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
    if (!train || !train.cids) return;

    if (action === 'up' && idx > 0) {
      const temp = train.cids[idx];
      train.cids[idx] = train.cids[idx - 1];
      train.cids[idx - 1] = temp;
    } else if (action === 'down' && idx < train.cids.length - 1) {
      const temp = train.cids[idx];
      train.cids[idx] = train.cids[idx + 1];
      train.cids[idx + 1] = temp;
    } else if (action === 'remove') {
      train.cids.splice(idx, 1);
    }

    renderTrainSelector();
    renderActiveTrain();
  }

  /**
   * Updates ISO-TP / CAN Frame Telemetry Metrics
   */
  function updateFramingMetrics(cidsSeq) {
    let payloadBytes = 0;
    (cidsSeq || []).forEach(k => {
      const def = state.cids[k];
      payloadBytes += def ? (def.memory_size || 1) : 1;
    });

    const cidCount = (cidsSeq || []).length;
    // ISO 14230-3 positive response: 1 byte SID (0x61) + 1 byte local_id + payload bytes
    const responseBytes = payloadBytes + 2;

    els.metricCidCount.textContent = cidCount;
    els.metricPayloadBytes.textContent = `${payloadBytes} B`;
    els.metricResponseBytes.textContent = `${responseBytes} B`;

    // ISO 15765-2 standard CAN (11-bit ID):
    // Single Frame (SF): up to 7 payload data bytes in a single 8-byte CAN frame
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
   * Renders Available Master CIDs Palette (Left Column)
   */
  function renderPalette() {
    els.paletteList.innerHTML = '';
    const term = state.searchPaletteTerm.toLowerCase().trim();

    const sortedKeys = Object.keys(state.cids).sort((a, b) => a.localeCompare(b));
    let matchedCount = 0;

    sortedKeys.forEach(cidKey => {
      const def = state.cids[cidKey];
      const hexId = def.id || '';
      const unit = def.unit || '';

      if (term) {
        const matchesKey = cidKey.toLowerCase().includes(term);
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
          <span class="palette-item-name">${escapeHtml(cidKey)}</span>
          <div class="palette-item-meta">
            <span class="palette-meta-tag">${escapeHtml(hexId)}</span>
            <span class="palette-meta-tag">${sizeStr}</span>
            ${unit ? `<span class="palette-meta-tag">${escapeHtml(unit)}</span>` : ''}
          </div>
        </div>
        <button type="button" class="btn btn-secondary btn-sm" data-cid="${escapeHtml(cidKey)}">
          <span>➕ Add</span>
        </button>
      `;

      item.querySelector('button').addEventListener('click', () => {
        addCidToActiveTrain(cidKey);
      });

      els.paletteList.appendChild(item);
    });

    if (matchedCount === 0) {
      els.paletteList.innerHTML = '<div class="empty-sequence-msg">No matching Master CIDs found.</div>';
    }
  }

  function addCidToActiveTrain(cidKey) {
    const train = getCurrentTrain();
    if (!train) {
      if (window.showToast) window.showToast('Please select or create an LID train first.', 'warning');
      return;
    }

    if (!train.cids) {
      train.cids = [];
    }

    train.cids.push(cidKey);
    renderTrainSelector();
    renderActiveTrain();
    if (window.showToast) {
      window.showToast(`Added ${cidKey} to train sequence.`, 'info');
    }
  }

  /**
   * Renders Master CIDs Table (Tab 2)
   */
  function renderCidsTable() {
    els.tbodyCids.innerHTML = '';
    const term = state.searchCidsTerm.toLowerCase().trim();
    const sortedKeys = Object.keys(state.cids).sort((a, b) => a.localeCompare(b));

    sortedKeys.forEach(cidKey => {
      const def = state.cids[cidKey];
      const hexId = def.id || '';
      const unit = def.unit || '';
      const desc = def.description || '';
      const isSigned = !!def.signed;

      if (term) {
        const matchesKey = cidKey.toLowerCase().includes(term);
        const matchesHex = hexId.toLowerCase().includes(term);
        const matchesUnit = unit.toLowerCase().includes(term);
        const matchesDesc = desc.toLowerCase().includes(term);
        if (!matchesKey && !matchesHex && !matchesUnit && !matchesDesc) return;
      }

      const tr = document.createElement('tr');
      const formulaStr = `((raw * ${def.mul ?? 1}) / ${def.div ?? 1}) + ${def.add ?? 0}`;

      tr.innerHTML = `
        <td><strong>${escapeHtml(cidKey)}</strong></td>
        <td class="mono">${escapeHtml(hexId)}</td>
        <td style="max-width: 260px; font-size: 13px; color: var(--text-muted);">${escapeHtml(desc)}</td>
        <td><span class="badge-size">${def.memory_size || 1} byte${def.memory_size > 1 ? 's' : ''}</span></td>
        <td><span class="badge ${isSigned ? 'badge-signed' : 'badge-unsigned'}" style="font-size: 11px; padding: 2px 6px; border-radius: 4px; background: ${isSigned ? 'rgba(239,68,68,0.15); color: #ef4444' : 'rgba(16,185,129,0.15); color: #10b981'}">${isSigned ? 'Signed' : 'Unsigned'}</span></td>
        <td>${def.position ?? 1}</td>
        <td>${def.mul ?? 1}</td>
        <td>${def.div ?? 1}</td>
        <td>${def.add ?? 0}</td>
        <td>${escapeHtml(unit)}</td>
        <td><span class="formula-chip">${escapeHtml(formulaStr)}</span></td>
        <td>
          <div class="table-actions">
            <button type="button" class="btn btn-secondary btn-sm" data-edit="${escapeHtml(cidKey)}">✏️ Edit</button>
            <button type="button" class="btn btn-danger btn-sm" data-del="${escapeHtml(cidKey)}">🗑️</button>
          </div>
        </td>
      `;

      tr.querySelector('[data-edit]').addEventListener('click', () => openEditCidModal(cidKey));
      tr.querySelector('[data-del]').addEventListener('click', () => deleteCid(cidKey));

      els.tbodyCids.appendChild(tr);
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
      let nextId = 0xF0;
      const existingIds = new Set(state.lids.map(t => parseInt(t.local_id, 16)));
      while (existingIds.has(nextId) && nextId <= 0xFE) {
        nextId++;
      }
      const hexStr = '0x' + nextId.toString(16).toUpperCase();

      const newTrain = {
        local_id: hexStr,
        name: `Custom_Train_${state.lids.length + 1}`,
        transmission_mode: 'fast',
        cids: []
      };

      state.lids.push(newTrain);
      state.currentTrainIdx = state.lids.length - 1;
      renderTrainSelector();
      renderActiveTrain();
      if (window.showToast) window.showToast(`Created new LID train ${hexStr}.`, 'success');
    });

    // Delete Train button
    els.btnDeleteTrain.addEventListener('click', () => {
      const train = getCurrentTrain();
      if (!train) return;
      if (!confirm(`Are you sure you want to delete train "${train.name || train.local_id}"?`)) return;

      state.lids.splice(state.currentTrainIdx, 1);
      state.currentTrainIdx = Math.max(0, state.lids.length - 1);
      renderTrainSelector();
      renderActiveTrain();
      if (window.showToast) window.showToast('Train deleted.', 'info');
    });

    // Save buttons
    els.btnSaveLids.addEventListener('click', saveLids);
    els.btnSaveCids.addEventListener('click', saveCids);
  }

  /**
   * Live Search Events
   */
  function setupSearchEvents() {
    els.searchPalette.addEventListener('input', (e) => {
      state.searchPaletteTerm = e.target.value;
      renderPalette();
    });

    els.searchCids.addEventListener('input', (e) => {
      state.searchCidsTerm = e.target.value;
      renderCidsTable();
    });
  }

  /**
   * Modal Setup & Form Handling
   */
  function setupModalEvents() {
    els.btnAddCid.addEventListener('click', () => openAddCidModal());
    els.btnCloseModal.addEventListener('click', closeModal);
    els.btnCancelModal.addEventListener('click', closeModal);

    // Live preview on formula input changes
    [els.inputCidMul, els.inputCidDiv, els.inputCidAdd, els.inputCidUnit].forEach(input => {
      input.addEventListener('input', updateFormulaPreview);
    });

    // Form submit
    els.formCid.addEventListener('submit', (e) => {
      e.preventDefault();
      applyModalCid();
    });
  }

  function updateFormulaPreview() {
    const mul = els.inputCidMul.value || 1;
    const div = els.inputCidDiv.value || 1;
    const add = els.inputCidAdd.value || 0;
    const unit = els.inputCidUnit.value.trim();
    els.formulaPreviewText.textContent = `((raw * ${mul}) / ${div}) + ${add} ${unit ? `[${unit}]` : ''}`;
  }

  function generateUniqueCidKey(baseKey, existingKeys) {
    let candidate = baseKey.trim();
    if (!candidate) candidate = 'cid';
    if (!existingKeys.has(candidate)) return candidate;

    let counter = 1;
    const match = candidate.match(/^(.*?)(?:_(\d+))?$/);
    const root = (match && match[1]) ? match[1] : candidate;

    while (existingKeys.has(`${root}_${counter}`)) {
      counter++;
    }
    return `${root}_${counter}`;
  }

  function openAddCidModal() {
    els.modalTitle.textContent = 'Add New Master Common Identifier (CID)';
    els.cidOriginalName.value = '';
    els.inputCidName.value = '';
    els.inputCidName.disabled = false;
    els.inputCidHex.value = '0x';
    els.inputCidDesc.value = '';
    els.selectCidSize.value = '1';
    els.inputCidSigned.checked = false;
    els.inputCidPosition.value = '1';
    els.inputCidMul.value = '1';
    els.inputCidDiv.value = '1';
    els.inputCidAdd.value = '0';
    els.inputCidUnit.value = '';

    updateFormulaPreview();
    els.modalCid.classList.add('open');
    els.inputCidName.focus();
  }

  function openEditCidModal(cidKey) {
    const def = state.cids[cidKey];
    if (!def) return;

    els.modalTitle.textContent = `Edit CID: ${cidKey}`;
    els.cidOriginalName.value = cidKey;
    els.inputCidName.value = cidKey;
    els.inputCidName.disabled = false;
    els.inputCidHex.value = def.id || '';
    els.inputCidDesc.value = def.description || '';
    els.selectCidSize.value = String(def.memory_size || 1);
    els.inputCidSigned.checked = !!def.signed;
    els.inputCidPosition.value = String(def.position ?? 1);
    els.inputCidMul.value = String(def.mul ?? 1);
    els.inputCidDiv.value = String(def.div ?? 1);
    els.inputCidAdd.value = String(def.add ?? 0);
    els.inputCidUnit.value = def.unit || '';

    updateFormulaPreview();
    els.modalCid.classList.add('open');
    els.inputCidHex.focus();
  }

  function closeModal() {
    els.modalCid.classList.remove('open');
  }

  function applyModalCid() {
    const origName = els.cidOriginalName.value.trim();
    let requestedName = els.inputCidName.value.trim();
    const hexId = els.inputCidHex.value.trim();
    const desc = els.inputCidDesc.value.trim();
    const size = parseInt(els.selectCidSize.value, 10);
    const isSigned = els.inputCidSigned.checked;
    const pos = parseInt(els.inputCidPosition.value, 10) || 1;
    const mul = parseFloat(els.inputCidMul.value) || 1;
    const div = parseFloat(els.inputCidDiv.value) || 1;
    const add = parseFloat(els.inputCidAdd.value) || 0;
    const unit = els.inputCidUnit.value.trim();

    if (!requestedName) {
      alert('CID Name is required.');
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

    // Determine final key name with unique suffix if needed
    let finalKey = requestedName;
    const existingKeys = new Set(Object.keys(state.cids));

    if (origName && origName === requestedName) {
      finalKey = origName;
    } else {
      if (origName) {
        existingKeys.delete(origName);
      }
      finalKey = generateUniqueCidKey(requestedName, existingKeys);

      if (origName && origName !== finalKey) {
        delete state.cids[origName];
        // Update references in active trains
        state.lids.forEach(train => {
          if (train.cids) {
            train.cids = train.cids.map(k => k === origName ? finalKey : k);
          }
        });
      }
    }

    state.cids[finalKey] = {
      id: hexId,
      memory_size: size,
      position: pos,
      signed: isSigned,
      mul: mul,
      div: div,
      add: add,
      unit: unit,
    };
    if (desc) {
      state.cids[finalKey].description = desc;
    }

    closeModal();
    renderPalette();
    renderActiveTrain();
    renderCidsTable();

    if (window.showToast) {
      const msg = (finalKey !== requestedName)
        ? `Saved CID as unique "${finalKey}" (suffixed from "${requestedName}"). Click "Save cids.json" to persist.`
        : `Saved CID "${finalKey}". Click "Save cids.json" to persist.`;
      window.showToast(msg, 'success');
    }
  }

  function deleteCid(cidKey) {
    if (!confirm(`Are you sure you want to delete Master CID "${cidKey}"?`)) return;

    delete state.cids[cidKey];
    state.lids.forEach(train => {
      if (train.cids) {
        train.cids = train.cids.filter(k => k !== cidKey);
      }
    });

    renderPalette();
    renderActiveTrain();
    renderCidsTable();
    if (window.showToast) {
      window.showToast(`Deleted CID "${cidKey}".`, 'info');
    }
  }

  /**
   * Persists lids.json to Backend
   */
  async function saveLids() {
    setStatus('Saving lids.json...');
    try {
      const payload = [];
      if (state.schemaGuides.lids) {
        payload.push({ _schema_guide: state.schemaGuides.lids });
      }
      payload.push(...state.lids);

      const resp = await fetch('/api/lids', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lids: payload })
      });

      if (!resp.ok) {
        const errJson = await resp.json().catch(() => ({}));
        throw new Error(errJson.error || `HTTP ${resp.status}`);
      }

      const res = await resp.json();
      setStatus(`Saved lids.json successfully (Backup: ${res.backup || 'created'})`);
      if (window.showToast) {
        window.showToast('lids.json saved successfully! Backup created.', 'success');
      }
    } catch (err) {
      console.error(err);
      setStatus(`Failed to save lids.json: ${err.message}`);
      if (window.showToast) {
        window.showToast(`Error saving lids.json: ${err.message}`, 'error');
      }
    }
  }

  /**
   * Persists cids.json to Backend
   */
  async function saveCids() {
    setStatus('Saving cids.json...');
    try {
      const payload = {};
      if (state.schemaGuides.cids) {
        payload._schema_guide = state.schemaGuides.cids;
      }
      for (const [k, v] of Object.entries(state.cids)) {
        payload[k] = v;
      }

      const resp = await fetch('/api/cids', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cids: payload })
      });

      if (!resp.ok) {
        const errJson = await resp.json().catch(() => ({}));
        throw new Error(errJson.error || `HTTP ${resp.status}`);
      }

      const res = await resp.json();
      setStatus(`Saved cids.json successfully (Backup: ${res.backup || 'created'})`);
      if (window.showToast) {
        window.showToast('cids.json saved successfully! Backup created.', 'success');
      }
    } catch (err) {
      console.error(err);
      setStatus(`Failed to save cids.json: ${err.message}`);
      if (window.showToast) {
        window.showToast(`Error saving cids.json: ${err.message}`, 'error');
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
