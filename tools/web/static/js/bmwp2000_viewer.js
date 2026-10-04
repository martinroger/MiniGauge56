/**
 * BMWP2000 Exchange Viewer Frontend Controller
 * Conforms to REQ-SYS-004, REQ-SYS-008, and python-tools-ecosystem recipe.
 */

(function () {
  'use strict';

  // State
  let currentLogFile = '';
  let exchangesData = null;
  let activeFilter = 'all';
  let serviceFilter = null; // Filter by specific SID from sidebar (e.g. "0x21")
  let selectedIndex = -1;
  let searchQuery = '';
  let activeSidebarTab = 'active'; // 'active' or 'all'

  // Toast notification helper that safely connects to window.Toast
  function showToast(message, type = 'info') {
    if (window.Toast && typeof window.Toast.show === 'function') {
      window.Toast.show(message, 3200, type);
    } else {
      console.log(`[Toast ${type}] ${message}`);
    }
  }

  // DOM Elements
  const selectLogFile = document.getElementById('select-log-file');
  const btnBrowseFile = document.getElementById('btn-browse-file');
  const inputFilePicker = document.getElementById('input-file-picker');
  const chkParseCids = document.getElementById('chk-parse-cids');
  const chkShowRawCan = document.getElementById('chk-show-raw-can');
  const chkHideUnknown = document.getElementById('chk-hide-unknown');
  const inputSearch = document.getElementById('input-search-exchanges');
  const exchangeTbody = document.getElementById('exchange-tbody');
  const exchangeTable = document.getElementById('exchange-table');
  const detailPane = document.getElementById('detail-pane');
  const inspectorBadgeContainer = document.getElementById('inspector-badge-container');
  const inspectorSelectedInfo = document.getElementById('inspector-selected-info');
  const filterBtns = document.querySelectorAll('.filter-btn');
  const resizerH = document.getElementById('resizer-h');
  const bottomInspector = document.getElementById('viewer-bottom-inspector');
  const tableSection = document.getElementById('viewer-table-section');

  // Services Sidebar Elements
  const servicesSidebar = document.getElementById('services-sidebar');
  const btnToggleServicesSidebar = document.getElementById('btn-toggle-services-sidebar');
  const btnCloseServicesSidebar = document.getElementById('btn-close-services-sidebar');
  const servicesActiveCount = document.getElementById('services-active-count');
  const sidebarServicesBadge = document.getElementById('sidebar-services-badge');
  const inputSearchServices = document.getElementById('input-search-services');
  const sidebarTabs = document.querySelectorAll('.sidebar-tab');
  const sidebarServicesList = document.getElementById('sidebar-services-list');
  const tabActiveCount = document.getElementById('tab-active-count');
  const tabAllCount = document.getElementById('tab-all-count');

  // Stats Elements
  const statOutgoing = document.getElementById('stat-outgoing');
  const statIncoming = document.getElementById('stat-incoming');
  const statNrc = document.getElementById('stat-nrc');
  const statUnimplemented = document.getElementById('stat-unimplemented');
  const statWarning = document.getElementById('stat-warning');

  // Modal Elements
  const modalAddCid = document.getElementById('modal-add-cid');
  const formAddCid = document.getElementById('form-add-cid');
  const btnCloseModal = document.getElementById('btn-close-modal');
  const btnCancelModal = document.getElementById('btn-cancel-modal');

  // Initialize
  function init() {
    setupEventListeners();
    setupPaneResizer();
    setupColumnResizers();
    setupServicesSidebarState();
    loadFileList();
  }

  function setupEventListeners() {
    selectLogFile.addEventListener('change', (e) => {
      currentLogFile = e.target.value;
      if (currentLogFile) {
        fetchExchanges();
      }
    });

    if (chkParseCids) {
      chkParseCids.addEventListener('change', () => {
        if (currentLogFile) {
          fetchExchanges();
        }
      });
    }

    if (chkShowRawCan) {
      chkShowRawCan.addEventListener('change', () => {
        renderExchangeTable();
      });
    }

    if (chkHideUnknown) {
      chkHideUnknown.addEventListener('change', () => {
        renderExchangeTable();
      });
    }

    if (inputSearch) {
      inputSearch.addEventListener('input', (e) => {
        searchQuery = (e.target.value || '').trim().toLowerCase();
        renderExchangeTable();
      });
    }

    btnBrowseFile.addEventListener('click', () => {
      inputFilePicker.click();
    });

    inputFilePicker.addEventListener('change', handleLocalFileUpload);

    filterBtns.forEach((btn) => {
      btn.addEventListener('click', () => {
        filterBtns.forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        activeFilter = btn.getAttribute('data-filter');
        serviceFilter = null; // clear service-specific filter if a main category button is clicked
        renderExchangeTable();
      });
    });

    // Services Sidebar Events
    if (btnToggleServicesSidebar) {
      btnToggleServicesSidebar.addEventListener('click', () => {
        toggleServicesSidebar();
      });
    }

    if (btnCloseServicesSidebar) {
      btnCloseServicesSidebar.addEventListener('click', () => {
        setServicesSidebarOpen(false);
      });
    }

    if (inputSearchServices) {
      inputSearchServices.addEventListener('input', () => {
        renderServicesList();
      });
    }

    sidebarTabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        sidebarTabs.forEach((t) => t.classList.remove('active'));
        tab.classList.add('active');
        activeSidebarTab = tab.getAttribute('data-tab');
        renderServicesList();
      });
    });

    // Modal Events
    if (btnCloseModal) btnCloseModal.addEventListener('click', () => closeModal());
    if (btnCancelModal) btnCancelModal.addEventListener('click', () => closeModal());
    if (formAddCid) formAddCid.addEventListener('submit', handleSaveNewCid);
  }

  function setupServicesSidebarState() {
    const saved = localStorage.getItem('bmwp2000_services_sidebar_open');
    if (saved === 'true') {
      setServicesSidebarOpen(true);
    } else {
      setServicesSidebarOpen(false);
    }
  }

  function toggleServicesSidebar() {
    if (!servicesSidebar) return;
    const isClosed = servicesSidebar.classList.contains('collapsed');
    setServicesSidebarOpen(isClosed);
  }

  function setServicesSidebarOpen(isOpen) {
    if (!servicesSidebar) return;
    if (isOpen) {
      servicesSidebar.classList.remove('collapsed');
      localStorage.setItem('bmwp2000_services_sidebar_open', 'true');
    } else {
      servicesSidebar.classList.add('collapsed');
      localStorage.setItem('bmwp2000_services_sidebar_open', 'false');
    }
  }

  // 1. Pane Resizer (Vertical splitter between upper table and bottom inspector)
  function setupPaneResizer() {
    if (!resizerH || !bottomInspector) return;

    let isDragging = false;
    let startY = 0;
    let startHeight = 0;

    // Load saved height
    const savedHeight = localStorage.getItem('bmwp2000_inspector_height');
    if (savedHeight) {
      bottomInspector.style.height = `${savedHeight}px`;
    }

    resizerH.addEventListener('mousedown', (e) => {
      isDragging = true;
      startY = e.clientY;
      startHeight = bottomInspector.getBoundingClientRect().height;
      resizerH.classList.add('is-dragging');
      document.body.style.cursor = 'row-resize';
      document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
      if (!isDragging) return;
      const deltaY = startY - e.clientY;
      const newHeight = Math.max(120, Math.min(window.innerHeight * 0.75, startHeight + deltaY));
      bottomInspector.style.height = `${newHeight}px`;
    });

    document.addEventListener('mouseup', () => {
      if (isDragging) {
        isDragging = false;
        resizerH.classList.remove('is-dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        localStorage.setItem('bmwp2000_inspector_height', bottomInspector.getBoundingClientRect().height);
      }
    });
  }

  // 2. Column Resizers for Table
  function setupColumnResizers() {
    if (!exchangeTable) return;
    const ths = exchangeTable.querySelectorAll('thead th');

    ths.forEach((th) => {
      // Add resizer handle to each header except last if needed
      const resizer = document.createElement('div');
      resizer.className = 'col-resizer';
      th.appendChild(resizer);

      let isDragging = false;
      let startX = 0;
      let startWidth = 0;

      resizer.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        isDragging = true;
        startX = e.clientX;
        startWidth = th.offsetWidth;
        resizer.classList.add('is-dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
      });

      document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        const deltaX = e.clientX - startX;
        const newWidth = Math.max(40, startWidth + deltaX);
        th.style.width = `${newWidth}px`;
      });

      document.addEventListener('mouseup', () => {
        if (isDragging) {
          isDragging = false;
          resizer.classList.remove('is-dragging');
          document.body.style.cursor = '';
          document.body.style.userSelect = '';
        }
      });
    });
  }

  function loadFileList() {
    fetch('/api/files')
      .then((res) => res.json())
      .then((files) => {
        selectLogFile.innerHTML = '';
        if (files.length === 0) {
          selectLogFile.innerHTML = '<option value="">No logs found</option>';
          return;
        }

        files.forEach((f) => {
          const opt = document.createElement('option');
          opt.value = f.filename;
          opt.textContent = `${f.filename} (${f.format.toUpperCase()}, ${(f.size / 1024).toFixed(1)} KB)`;
          selectLogFile.appendChild(opt);
        });

        currentLogFile = files[0].filename;
        selectLogFile.value = currentLogFile;
        fetchExchanges();
      })
      .catch((err) => {
        console.error('Error fetching log files:', err);
        showToast('Failed to load log file list', 'error');
      });
  }

  function fetchExchanges() {
    if (!currentLogFile) return;

    const parseCids = chkParseCids ? chkParseCids.checked : true;
    exchangeTbody.innerHTML = '<tr><td colspan="10" style="padding: 24px; text-align: center; color: var(--text-muted);">Loading and analyzing exchanges...</td></tr>';

    fetch(`/api/exchanges?file=${encodeURIComponent(currentLogFile)}&parse_cids=${parseCids}&parse_dids=${parseCids}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data) => {
        exchangesData = data;
        updateStats(data.stats);
        renderServicesList();
        selectedIndex = data.exchanges && data.exchanges.length > 0 ? 0 : -1;
        renderExchangeTable();
        renderDetailPane();
      })
      .catch((err) => {
        console.error('Error fetching exchanges:', err);
        exchangeTbody.innerHTML = `<tr><td colspan="10" style="padding: 24px; text-align: center; color: var(--danger);">Failed to load exchanges: ${err.message}</td></tr>`;
        showToast('Error analyzing log file', 'error');
      });
  }

  function updateStats(stats) {
    if (!stats) return;
    statOutgoing.textContent = `Outgoing: ${stats.outgoing_count}`;
    statIncoming.textContent = `Incoming: ${stats.incoming_count}`;
    statNrc.textContent = `Errors (0x7F): ${stats.negative_responses}`;
    statUnimplemented.textContent = `Unimplemented: ${stats.unimplemented_count}`;
    if (statWarning) {
      const warns = (stats.interrupted_count || 0) + (stats.non_compliant_count || 0);
      statWarning.textContent = `⚠️ Warnings: ${warns}`;
      statWarning.style.display = warns > 0 ? 'inline-block' : 'none';
    }
    if (servicesActiveCount) {
      servicesActiveCount.textContent = stats.identified_services_count || 0;
    }
    if (sidebarServicesBadge && exchangesData && exchangesData.canonical_services) {
      sidebarServicesBadge.textContent = `${stats.identified_services_count || 0} / ${exchangesData.canonical_services.length}`;
    }
    if (tabActiveCount) {
      tabActiveCount.textContent = stats.identified_services_count || 0;
    }
    if (tabAllCount && exchangesData && exchangesData.canonical_services) {
      tabAllCount.textContent = exchangesData.canonical_services.length;
    }
  }

  function renderServicesList() {
    if (!sidebarServicesList || !exchangesData || !exchangesData.canonical_services) {
      if (sidebarServicesList) {
        sidebarServicesList.innerHTML = '<div style="padding: 16px; text-align: center; color: var(--text-muted); font-size: 12px;">No services loaded</div>';
      }
      return;
    }

    const query = (inputSearchServices ? inputSearchServices.value : '').trim().toLowerCase();
    let services = exchangesData.canonical_services;

    if (activeSidebarTab === 'active') {
      services = services.filter((s) => s.is_active);
    }

    if (query) {
      services = services.filter((s) =>
        s.sid_hex.toLowerCase().includes(query) ||
        s.service_name.toLowerCase().includes(query)
      );
    }

    if (services.length === 0) {
      sidebarServicesList.innerHTML = '<div style="padding: 16px; text-align: center; color: var(--text-muted); font-size: 12px;">No matching services</div>';
      return;
    }

    sidebarServicesList.innerHTML = '';
    services.forEach((svc) => {
      const card = document.createElement('div');
      card.className = 'service-item-card';
      if (svc.is_active) card.classList.add('is-active-service');
      if (serviceFilter === svc.sid_hex) card.classList.add('selected-filter');

      const countPillClass = svc.total_count > 0 ? 'service-count-pill has-count' : 'service-count-pill';

      card.innerHTML = `
        <div class="service-item-left">
          <div class="service-sid-badge">${svc.sid_hex}</div>
          <div class="service-name-label" title="${escapeHtml(svc.service_name)}">${escapeHtml(svc.service_name)}</div>
        </div>
        <div class="${countPillClass}" title="Total occurrences in log (Req: ${svc.req_count}, Resp: ${svc.resp_count})">
          ${svc.total_count}
        </div>
      `;

      card.addEventListener('click', () => {
        if (serviceFilter === svc.sid_hex) {
          serviceFilter = null; // toggle off
        } else {
          serviceFilter = svc.sid_hex;
        }
        renderServicesList();
        renderExchangeTable();
      });

      sidebarServicesList.appendChild(card);
    });
  }

  function matchesFilter(item) {
    // 1. Raw CAN Frames toggle (e.g. 0x130, 0x153 broadcast frames)
    if (item.is_raw_can) {
      return !!(chkShowRawCan && chkShowRawCan.checked);
    }

    // 2. Hide Unknown Services
    if (chkHideUnknown && chkHideUnknown.checked) {
      if (!item.is_implemented) {
        return false;
      }
    }

    // 3. Service Filter from right sidebar checklist
    if (serviceFilter) {
      // Matches request SID or positive response SID (base SID + 0x40)
      const sidHex = item.service_id;
      let matchesSid = (sidHex === serviceFilter);
      if (!matchesSid && item.details && item.details.rejected_service_id) {
        matchesSid = (item.details.rejected_service_id === serviceFilter);
      }
      if (!matchesSid) {
        try {
          const sidNum = parseInt(sidHex, 16);
          const filterNum = parseInt(serviceFilter, 16);
          if (sidNum === (filterNum + 0x40)) {
            matchesSid = true;
          }
        } catch (e) {}
      }
      if (!matchesSid) return false;
    }

    // 4. Category Filter Buttons
    if (activeFilter === 'outgoing' && item.direction !== 'OUTGOING') return false;
    if (activeFilter === 'incoming' && item.direction !== 'INCOMING') return false;
    if (activeFilter === 'lid' && item.service_id !== '0x2C' && item.service_id !== '0x6C') return false;
    if (activeFilter === 'data' && item.service_id !== '0x21' && item.service_id !== '0x61') return false;
    if (activeFilter === 'cid' && item.service_id !== '0x22' && item.service_id !== '0x62') return false;
    if (activeFilter === 'nrc' && !item.is_negative_response) return false;
    if (activeFilter === 'warning' && !item.is_interrupted && item.is_compliant && (!item.warnings || item.warnings.length === 0)) return false;
    if (activeFilter === 'known' && !item.is_implemented) return false;
    if (activeFilter === 'unimplemented' && item.is_implemented) return false;

    // 5. Text Search Query
    if (searchQuery) {
      const summaryText = buildSummaryText(item).toLowerCase();
      const serviceText = (item.service_name || '').toLowerCase();
      const sidText = (item.service_id || '').toLowerCase();
      const canIdText = (item.can_id || '').toLowerCase();
      const rawHexText = (item.raw_hex || '').toLowerCase();
      const targetEcuText = (item.target_ecu || '').toLowerCase();

      const combined = `${item.index} ${serviceText} ${sidText} ${canIdText} ${targetEcuText} ${rawHexText} ${summaryText}`;
      if (!combined.includes(searchQuery)) {
        return false;
      }
    }

    return true;
  }

  function buildSummaryText(item) {
    const details = item.details || {};
    if (item.is_raw_can) {
      return `Broadcast CAN Frame [DLC ${details.dlc || 8}] (ID ${item.can_id})`;
    }
    if (item.is_interrupted) {
      return `⚠️ INTERRUPTED: ${(item.warnings || []).join('; ') || 'Incomplete stream'}`;
    }
    if (item.is_negative_response) {
      return `REJECTED ${details.rejected_service_name || details.rejected_service_id}: ${details.nrc_name || ''} (${details.nrc || ''})`;
    }
    if (item.service_id === '0x2C') {
      const entryCount = (details.entries || []).length;
      if (details.subfunction === '0x04') return `Clear LID ${details.local_id || ''}`;
      return `LID ${details.local_id || ''} [${details.subfunction_name || ''}] ${entryCount} CIDs (${details.total_bytes || 0} bytes)`;
    }
    if (item.service_id === '0x6C') {
      return `LID ${details.local_id || ''} configured OK`;
    }
    if (item.service_id === '0x21') {
      const modeStr = details.transmission_mode_name ? ` [${details.transmission_mode_name}]` : '';
      return `Read Local ID ${details.local_id || ''}${modeStr}`;
    }
    if (item.service_id === '0x61') {
      if (details.signals && details.signals.length > 0) {
        return details.signals.map((s) => `${s.cid_name || s.did_name}: ${s.scaled_value} ${s.unit}`).join(' | ');
      }
      return `Data for Local ID ${details.local_id || ''} (${details.data_length || 0} bytes)`;
    }
    if (item.service_id === '0x22') {
      return `Read Common CID ${details.recordCommonIdentifier || ''} (${details.cid_name || details.did_name || ''})`;
    }
    if (item.service_id === '0x62') {
      return `Common CID ${details.recordCommonIdentifier || ''} Data: ${details.data_hex || ''}`;
    }
    if (item.service_id === '0x23' || item.service_id === '0x63') {
      return `Read Memory ${details.memoryAddress || ''} [${details.memorySize || ''} bytes]`;
    }
    if (item.service_id === '0x26' || item.service_id === '0x66') {
      return `SetDataRates (slow:${details.slowRate || ''}, med:${details.mediumRate || ''}, fast:${details.fastRate || ''})`;
    }
    if (item.service_id === '0x27' || item.service_id === '0x67') {
      return `Security Access [${details.accessMode || ''}] ${details.securityAccessStatus || ''}`;
    }
    if (item.service_id === '0x11' || item.service_id === '0x51') {
      return `ECU Reset [${details.resetMode || details.resetStatus || 'PowerOn'}]`;
    }
    if (item.service_id === '0x14' || item.service_id === '0x54') {
      return `Clear Diagnostic Info / DTCs`;
    }
    if (item.service_id === '0x13' || item.service_id === '0x53' || item.service_id === '0x17' || item.service_id === '0x57' || item.service_id === '0x18' || item.service_id === '0x58') {
      return `Read DTCs: ${details.numberOfDTC !== undefined ? details.numberOfDTC + ' stored' : ''}`;
    }
    if (item.service_id === '0x20' || item.service_id === '0x60') {
      return `Stop Diagnostic Session`;
    }
    if (item.service_id === '0x3E' || item.service_id === '0x7E') {
      return `Tester Present [${details.subFunction || 'Keep-Alive'}]`;
    }
    if (item.service_id === '0x10' || item.service_id === '0x50') {
      return `Session: ${details.diagnosticSessionName || details.session_type || 'Default'}`;
    }
    if (item.service_id === '0x1A' || item.service_id === '0x5A') {
      return `ECU Ident: ${details.identificationOptionName || details.ident_option || ''} ${details.ident_data || ''}`;
    }
    if (item.service_id === '0x31' || item.service_id === '0x71') {
      return `Start Routine [${details.routineIdentifier || ''}]`;
    }
    if (item.service_id === '0x32' || item.service_id === '0x72') {
      return `Stop Routine [${details.routineIdentifier || ''}]`;
    }
    if (item.service_id === '0x33' || item.service_id === '0x73') {
      return `Routine Results [${details.routineIdentifier || ''}]`;
    }
    if (item.service_id === '0x34' || item.service_id === '0x74') {
      return `Request Download`;
    }
    if (item.service_id === '0x35' || item.service_id === '0x75') {
      return `Request Upload`;
    }
    if (item.service_id === '0x36' || item.service_id === '0x76') {
      return `Transfer Data`;
    }
    if (item.service_id === '0x37' || item.service_id === '0x77') {
      return `Request Transfer Exit`;
    }
    if (item.service_id === '0x30' || item.service_id === '0x70' || item.service_id === '0x2F' || item.service_id === '0x6F') {
      return `I/O Control [${details.io_identifier || ''}]`;
    }
    if (item.service_id === '0x3B' || item.service_id === '0x7B' || item.service_id === '0x2E' || item.service_id === '0x6E') {
      return `Write Data [${details.recordIdentifier || ''}]`;
    }
    if (!item.is_implemented) {
      return `Proprietary Service (Payload: ${item.raw_hex.substring(2, 14)}...)`;
    }
    return '';
  }

  function renderExchangeTable() {
    if (!exchangesData || !exchangesData.exchanges) {
      exchangeTbody.innerHTML = '<tr><td colspan="10" style="padding: 24px; text-align: center; color: var(--text-muted);">No exchanges found</td></tr>';
      return;
    }

    const filtered = exchangesData.exchanges.filter(matchesFilter);
    if (filtered.length === 0) {
      exchangeTbody.innerHTML = '<tr><td colspan="10" style="padding: 24px; text-align: center; color: var(--text-muted);">No messages match current filter criteria</td></tr>';
      return;
    }

    exchangeTbody.innerHTML = '';
    filtered.forEach((item) => {
      const tr = document.createElement('tr');
      const isOutgoing = item.direction === 'OUTGOING';

      if (item.is_raw_can) {
        tr.classList.add('row-raw-can');
      } else if (isOutgoing) {
        tr.classList.add('row-outgoing');
      } else {
        tr.classList.add('row-incoming');
      }
      if (item.is_negative_response) tr.classList.add('row-nrc');
      if (!item.is_implemented && !item.is_raw_can) tr.classList.add('row-unimplemented');
      if (item.is_interrupted || !item.is_compliant) tr.classList.add('row-warning');
      if (item.index === selectedIndex) tr.classList.add('selected');

      // Badges
      let dirBadge = '';
      if (item.is_raw_can) {
        dirBadge = '<span class="badge badge-raw-can">RAW CAN</span>';
      } else if (item.is_interrupted || !item.is_compliant) {
        dirBadge = '<span class="badge" style="background: rgba(239, 68, 68, 0.2); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.4);">⚠️ WARN</span>';
      } else if (item.is_negative_response) {
        dirBadge = '<span class="badge badge-nrc">0x7F NRC</span>';
      } else if (!item.is_implemented) {
        dirBadge = '<span class="badge badge-unimplemented">UNKNOWN</span>';
      } else if (isOutgoing) {
        dirBadge = '<span class="badge badge-outgoing">REQ</span>';
      } else {
        dirBadge = '<span class="badge badge-incoming">RESP</span>';
      }

      // Timing Cell Formatting: delta to previous message + request-to-request interval or response latency
      const prevDeltaText = item.delta_prev_ms !== null && item.delta_prev_ms !== undefined ? `+${item.delta_prev_ms} ms` : '-';
      let timingHtml = `<div class="timing-cell"><span class="timing-prev" title="Time elapsed since previous message">Δt: ${prevDeltaText}</span>`;
      if (isOutgoing && item.req_interval_ms !== null && item.req_interval_ms !== undefined) {
        timingHtml += `<span class="timing-req" title="Cycle interval since previous tester request">Req Δt: +${item.req_interval_ms} ms</span>`;
      } else if (!isOutgoing && !item.is_raw_can && item.delta_ms !== undefined) {
        timingHtml += `<span class="timing-latency" title="ECU response latency">+${item.delta_ms} ms</span>`;
      }
      timingHtml += '</div>';

      const summaryText = buildSummaryText(item);
      const hexSnippet = item.raw_hex.length > 16 ? `${item.raw_hex.substring(0, 16)}...` : item.raw_hex;

      tr.innerHTML = `
        <td style="font-weight: 600; color: var(--text-muted);">${item.index + 1}</td>
        <td style="font-family: monospace;">${item.time_s.toFixed(4)}</td>
        <td>${timingHtml}</td>
        <td>${dirBadge}</td>
        <td><code>${item.can_id}</code></td>
        <td><code>${item.target_ecu}</code></td>
        <td><code>${item.service_id}</code></td>
        <td style="font-weight: 500;">${item.service_name}</td>
        <td style="max-width: 450px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(summaryText)}">
          ${escapeHtml(summaryText)}
        </td>
        <td><code style="font-size: 11px;">${hexSnippet}</code></td>
      `;

      tr.addEventListener('click', () => {
        selectedIndex = item.index;
        document.querySelectorAll('.exchange-table tr').forEach((r) => r.classList.remove('selected'));
        tr.classList.add('selected');
        renderDetailPane();
      });

      exchangeTbody.appendChild(tr);
    });
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function renderDetailPane() {
    if (!exchangesData || selectedIndex < 0 || selectedIndex >= exchangesData.exchanges.length) {
      if (inspectorSelectedInfo) inspectorSelectedInfo.textContent = 'No message selected';
      if (inspectorBadgeContainer) inspectorBadgeContainer.innerHTML = '';
      detailPane.innerHTML = `
        <div class="detail-section-card" style="text-align: center; padding: 40px; color: var(--text-muted);">
          Select an exchange from the table above to inspect protocol details.
        </div>
      `;
      return;
    }

    const item = exchangesData.exchanges[selectedIndex];
    const details = item.details || {};

    if (inspectorSelectedInfo) {
      inspectorSelectedInfo.textContent = `Msg #${item.index + 1} | Time: ${item.time_s.toFixed(4)}s | ${item.can_id} | ${item.service_name} (${item.service_id})`;
    }
    if (inspectorBadgeContainer) {
      let badge = '';
      if (item.is_interrupted || !item.is_compliant) {
        badge = '<span class="badge" style="background: rgba(239, 68, 68, 0.2); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.4);">⚠️ COMPLIANCE WARN</span>';
      } else if (item.is_negative_response) {
        badge = '<span class="badge badge-nrc">NRC 0x7F</span>';
      } else if (!item.is_implemented) {
        badge = '<span class="badge badge-unimplemented">UNKNOWN</span>';
      } else if (item.direction === 'OUTGOING') {
        badge = '<span class="badge badge-outgoing">REQ</span>';
      } else {
        badge = '<span class="badge badge-incoming">RESP</span>';
      }
      inspectorBadgeContainer.innerHTML = badge;
    }

    let contentHtml = `
      <div class="detail-section-card">
        <div class="detail-section-title">
          <span>Diagnostic Protocol Overview</span>
          ${item.is_interrupted ? '<span class="badge" style="background: rgba(239, 68, 68, 0.2); color: var(--danger);">INTERRUPTED</span>' : ''}
          ${item.is_negative_response ? '<span class="badge badge-nrc">NEGATIVE RESPONSE</span>' : ''}
          ${!item.is_implemented ? '<span class="badge badge-unimplemented">UNIMPLEMENTED / UNKNOWN</span>' : ''}
        </div>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; font-size: 13px;">
          <div><strong style="color: var(--text-muted);">Timestamp:</strong> ${item.time_s.toFixed(6)} s</div>
          <div><strong style="color: var(--text-muted);">Direction:</strong> ${item.direction} (${item.can_id})</div>
          <div><strong style="color: var(--text-muted);">Target ECU / Address:</strong> ${item.target_ecu}</div>
          <div><strong style="color: var(--text-muted);">Service:</strong> ${item.service_name} (${item.service_id})</div>
          <div><strong style="color: var(--text-muted);">Transport:</strong> ${item.is_multiframe ? `Multi-frame (${item.frame_count} CAN frames)` : 'Single Frame'}</div>
          <div><strong style="color: var(--text-muted);">Payload Size:</strong> ${item.raw_hex.length / 2} bytes</div>
        </div>
      </div>
    `;

    // Warnings / Interruption Block
    if (item.warnings && item.warnings.length > 0) {
      let warnItems = item.warnings.map((w) => `<li>⚠️ ${escapeHtml(w)}</li>`).join('');
      contentHtml += `
        <div class="detail-section-card" style="border-left: 4px solid var(--danger); background: rgba(239, 68, 68, 0.08);">
          <div class="detail-section-title" style="color: var(--danger);">
            ⚠️ Protocol Compliance & Stream Interruption Warnings
          </div>
          <ul style="margin: 6px 0 0 16px; padding: 0; font-size: 13px; color: var(--text);">
            ${warnItems}
          </ul>
        </div>
      `;
    }

    // 1. Negative Response Warning Block
    if (item.is_negative_response) {
      contentHtml += `
        <div class="detail-section-card" style="border-left: 4px solid var(--danger); background: rgba(239, 68, 68, 0.06);">
          <div class="detail-section-title" style="color: var(--danger);">
            ⚠️ Negative Response Details (${details.nrc})
          </div>
          <div style="font-size: 14px; margin-bottom: 6px;">
            <strong>Rejected Service:</strong> ${details.rejected_service_name} (${details.rejected_service_id})
          </div>
          <div style="font-size: 14px; margin-bottom: 6px;">
            <strong>Negative Response Code (NRC):</strong> <span class="badge badge-nrc">${details.nrc_name} (${details.nrc})</span>
          </div>
          <div style="font-size: 13px; color: var(--text-muted);">
            ${details.human_description || ''}
          </div>
        </div>
      `;
    }

    // 2. Unimplemented Command Block
    if (!item.is_implemented) {
      contentHtml += `
        <div class="detail-section-card" style="border-left: 4px solid #f59e0b; background: rgba(245, 158, 11, 0.06);">
          <div class="detail-section-title" style="color: #f59e0b;">
            ⚠️ Unimplemented or Proprietary BMW Diagnostic Service
          </div>
          <p style="font-size: 13px; color: var(--text-muted); margin: 0;">
            This command (Service ${item.service_id}) is not yet officially implemented in the MiniGauge BMWP2000 dissector.
            Inspect the raw hex payload below for reverse engineering.
          </p>
        </div>
      `;
    }

    // 3. LID Configuration Block
    if (details.local_id && details.entries) {
      let entriesRows = details.entries.map((e) => `
        <tr>
          <td><strong style="color: var(--primary);">${escapeHtml(e.cid_name || e.did_name)}</strong></td>
          <td><code>${e.cid_hex || e.did_hex}</code></td>
          <td>${e.memory_size} Byte(s)</td>
          <td>Pos ${e.position}</td>
          <td>${e.is_known ? '<span style="color: #10b981;">✓ Known in cids.json</span>' : '<span style="color: #f59e0b;">⚠️ Unknown CID</span>'}</td>
        </tr>
      `).join('');

      let unknownPrompts = (details.unknown_cids || details.unknown_dids || []).map((uk) => `
        <div class="discovered-did-card">
          <div>
            <strong>Discovered New CID:</strong> <code>${uk.id}</code> (${uk.memory_size} bytes, position ${uk.position})
          </div>
          <button type="button" class="btn btn-primary btn-sm btn-prompt-add-cid"
            data-id="${uk.id}" data-size="${uk.memory_size}" data-pos="${uk.position}">
            ➕ Add to cids.json
          </button>
        </div>
      `).join('');

      // Visual Memory Strip: Horizontal layout of byte blocks in the train
      let memoryStripBlocks = details.entries.map((e) => {
        const name = escapeHtml(e.cid_name || e.did_name || 'CID');
        const hex = escapeHtml(e.cid_hex || e.did_hex || '');
        const size = e.memory_size || 1;
        const color = e.is_known ? 'var(--primary)' : '#f59e0b';
        return `
          <div style="flex: ${size}; min-width: 70px; border: 1px solid ${color}; border-radius: 4px; padding: 6px 8px; background: rgba(0,0,0,0.25); text-align: center;">
            <div style="font-weight: 600; font-size: 11px; color: ${color}; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${name}</div>
            <div style="font-family: monospace; font-size: 10px; color: var(--text-muted);">${hex}</div>
            <div style="font-size: 10px; margin-top: 2px;"><span class="badge" style="font-size: 9px; padding: 1px 4px;">${size}B</span></div>
          </div>
        `;
      }).join('');

      contentHtml += `
        <div class="detail-section-card">
          <div class="detail-section-title">
            Dynamically Defined Local Identifier (LID ${details.local_id}) Configuration
          </div>
          <div style="font-size: 13px; margin-bottom: 8px;">
            <strong>Subfunction:</strong> ${details.subfunction_name} (${details.subfunction}) &nbsp;|&nbsp;
            <strong>Total Stream Length:</strong> ${details.total_bytes} bytes
          </div>

          <div style="margin-bottom: 14px;">
            <div style="font-size: 11px; font-weight: 600; text-transform: uppercase; color: var(--text-muted); margin-bottom: 6px;">CID Train Memory Layout</div>
            <div style="display: flex; gap: 6px; overflow-x: auto; padding-bottom: 4px;">
              ${memoryStripBlocks}
            </div>
          </div>

          <table class="signals-table">
            <thead>
              <tr>
                <th>CID Name</th>
                <th>CID Hex</th>
                <th>Size</th>
                <th>Position</th>
                <th>Dictionary Status</th>
              </tr>
            </thead>
            <tbody>${entriesRows}</tbody>
          </table>
          ${unknownPrompts}
        </div>
      `;
    }

    // 4. Decoded Signals Table (from 0x61 or periodic responses, including all configured CIDs)
    if (details.signals && details.signals.length > 0) {
      let signalsRows = details.signals.map((sig) => `
        <tr>
          <td><strong>${escapeHtml(sig.cid_name || sig.did_name)}</strong> (<code>${sig.cid_hex || sig.did_hex}</code>)</td>
          <td><span class="signal-val-badge">${sig.scaled_value}</span> ${sig.unit ? escapeHtml(sig.unit) : ''}</td>
          <td><code>0x${sig.raw_hex}</code> (${sig.raw_int})</td>
          <td style="font-size: 11px; color: var(--text-muted); font-family: monospace;">${escapeHtml(sig.formula || 'raw')}</td>
        </tr>
      `).join('');

      contentHtml += `
        <div class="detail-section-card">
          <div class="detail-section-title">
            Decoded Physical Telemetry Signals (${details.local_id})
          </div>
          <table class="signals-table">
            <thead>
              <tr>
                <th>Parameter</th>
                <th>Physical / Scaled Value</th>
                <th>Raw Bytes (Int)</th>
                <th>Scaling Formula</th>
              </tr>
            </thead>
            <tbody>${signalsRows}</tbody>
          </table>
        </div>
      `;
    }

    // 5. Decrypted Service Parameters Card
    const paramItems = [];
    if (details.recordLocalIdentifier) paramItems.push(`<div><strong>recordLocalIdentifier:</strong> <code>${details.recordLocalIdentifier}</code></div>`);
    if (details.recordCommonIdentifier) paramItems.push(`<div><strong>recordCommonIdentifier:</strong> <code>${details.recordCommonIdentifier}</code> (${escapeHtml(details.cid_name || details.did_name || '')})</div>`);
    if (details.transmission_mode) paramItems.push(`<div><strong>transmissionMode:</strong> <code>${details.transmission_mode}</code> (${escapeHtml(details.transmission_mode_name || '')}) &mdash; <span class="text-muted">${escapeHtml(details.transmission_mode_desc || '')}</span></div>`);
    if (details.subFunction) paramItems.push(`<div><strong>subFunction:</strong> <code>${escapeHtml(details.subFunction)}</code></div>`);
    if (details.diagnosticSessionType) paramItems.push(`<div><strong>diagnosticSessionType:</strong> <code>${details.diagnosticSessionType}</code> (${escapeHtml(details.diagnosticSessionName || '')})</div>`);
    if (details.identificationOption) paramItems.push(`<div><strong>identificationOption:</strong> <code>${details.identificationOption}</code> (${escapeHtml(details.identificationOptionName || '')})</div>`);
    if (details.subfunction_name) paramItems.push(`<div><strong>definitionMode / Subfunction:</strong> ${escapeHtml(details.subfunction_name)} (<code>${details.subfunction}</code>)</div>`);

    if (paramItems.length > 0) {
      contentHtml += `
        <div class="detail-section-card" style="border-left: 4px solid var(--primary);">
          <div class="detail-section-title">
            ⚙️ Decrypted Service Parameters (${item.service_name})
          </div>
          <div style="display: flex; flex-direction: column; gap: 6px; font-size: 13px;">
            ${paramItems.join('')}
          </div>
        </div>
      `;
    }

    // 6. Raw Hex Payload
    contentHtml += `
      <div class="detail-section-card">
        <div class="detail-section-title">Reassembled Diagnostic Payload</div>
        <div class="hex-box">${formatHexDump(item.raw_hex)}</div>
      </div>
    `;

    // 7. Underlying CAN Frames (Collapsible Accordion, collapsed by default)
    if (item.can_frames && item.can_frames.length > 0) {
      let framesRows = item.can_frames.map((cf, idx) => `
        <tr>
          <td>#${idx + 1}</td>
          <td>${cf.ts_s.toFixed(6)} s</td>
          <td><code>${cf.can_id}</code></td>
          <td><code>${cf.data_hex}</code></td>
        </tr>
      `).join('');

      contentHtml += `
        <details class="can-frames-accordion" style="display: block; margin-top: 12px; margin-bottom: 24px;">
          <summary style="cursor: pointer; user-select: none;">
            <span>Underlying CAN Frames (${item.can_frames.length})</span>
          </summary>
          <div class="can-frames-accordion-content" style="margin-top: 8px; overflow-x: auto;">
            <table class="signals-table">
              <thead>
                <tr>
                  <th>Frame</th>
                  <th>Timestamp</th>
                  <th>CAN ID</th>
                  <th>Raw Bytes</th>
                </tr>
              </thead>
              <tbody>${framesRows}</tbody>
            </table>
          </div>
        </details>
      `;
    }

    detailPane.innerHTML = contentHtml;

    // Bind prompt buttons for adding unknown CIDs
    document.querySelectorAll('.btn-prompt-add-cid').forEach((btn) => {
      btn.addEventListener('click', () => {
        const id = btn.getAttribute('data-id');
        const size = btn.getAttribute('data-size');
        const pos = btn.getAttribute('data-pos');
        openAddCidModal(id, size, pos);
      });
    });
  }

  function formatHexDump(hexStr) {
    if (!hexStr) return '';
    const chunks = [];
    for (let i = 0; i < hexStr.length; i += 2) {
      chunks.push(hexStr.substr(i, 2));
    }
    return chunks.join(' ');
  }

  function handleLocalFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;

    showToast(`Uploading and reading: ${file.name}...`, 'info');

    const reader = new FileReader();
    reader.onload = function (readEvent) {
      const binaryString = readEvent.target.result;
      const base64Content = btoa(
        new Uint8Array(binaryString).reduce((data, byte) => data + String.fromCharCode(byte), '')
      );

      fetch('/api/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filename: file.name,
          content_base64: base64Content,
        }),
      })
        .then((res) => {
          if (!res.ok) throw new Error(`Upload HTTP ${res.status}`);
          return res.json();
        })
        .then((data) => {
          showToast(`Loaded ${data.filename} (${data.format.toUpperCase()})`, 'success');

          // Add to select if not present
          let exists = false;
          for (let i = 0; i < selectLogFile.options.length; i++) {
            if (selectLogFile.options[i].value === data.filename) {
              exists = true;
              break;
            }
          }

          if (!exists) {
            const opt = document.createElement('option');
            opt.value = data.filename;
            opt.textContent = `${data.filename} (${data.format.toUpperCase()}, ${(data.size / 1024).toFixed(1)} KB)`;
            selectLogFile.insertBefore(opt, selectLogFile.firstChild);
          }

          selectLogFile.value = data.filename;
          currentLogFile = data.filename;
          fetchExchanges();
        })
        .catch((err) => {
          console.error('Error uploading file:', err);
          showToast(`Upload failed: ${err.message}`, 'error');
        });
    };

    reader.readAsArrayBuffer(file);
  }

  function openAddCidModal(hexId, size, pos) {
    const idInput = document.getElementById('cid-id');
    if (idInput) idInput.value = hexId || '';
    const sizeInput = document.getElementById('cid-size');
    if (sizeInput) sizeInput.value = size || '2';
    const posInput = document.getElementById('cid-pos');
    if (posInput) posInput.value = pos || '1';
    const nameInput = document.getElementById('cid-name');
    if (nameInput) nameInput.value = '';
    const descInput = document.getElementById('cid-desc');
    if (descInput) descInput.value = '';
    const signedInput = document.getElementById('cid-signed');
    if (signedInput) signedInput.checked = false;
    const unitInput = document.getElementById('cid-unit');
    if (unitInput) unitInput.value = '';
    const mulInput = document.getElementById('cid-mul');
    if (mulInput) mulInput.value = '1';
    const divInput = document.getElementById('cid-div');
    if (divInput) divInput.value = '1';
    const addInput = document.getElementById('cid-add');
    if (addInput) addInput.value = '0';

    if (modalAddCid) modalAddCid.classList.add('open');
  }

  function closeModal() {
    if (modalAddCid) modalAddCid.classList.remove('open');
  }

  function handleSaveNewCid(e) {
    e.preventDefault();

    const mulVal = parseFloat(document.getElementById('cid-mul').value) || 1;
    const divVal = parseFloat(document.getElementById('cid-div').value) || 1;
    const addVal = parseFloat(document.getElementById('cid-add').value) || 0;

    const payload = {
      name: document.getElementById('cid-name').value.trim(),
      id: document.getElementById('cid-id').value.trim().toUpperCase(),
      description: document.getElementById('cid-desc').value.trim(),
      signed: document.getElementById('cid-signed').checked,
      memory_size: parseInt(document.getElementById('cid-size').value, 10),
      position: parseInt(document.getElementById('cid-pos').value, 10),
      unit: document.getElementById('cid-unit').value.trim(),
      mul: mulVal,
      div: divVal !== 0 ? divVal : 1,
      add: addVal,
    };

    fetch('/api/add_cid', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((resData) => {
        closeModal();
        showToast(resData.message || 'CID saved successfully', 'success');
        // Re-analyze active exchange log to reflect newly added CID
        fetchExchanges();
      })
      .catch((err) => {
        console.error('Error saving CID:', err);
        showToast(`Failed to save CID: ${err.message}`, 'error');
      });
  }

  // Self-start
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
