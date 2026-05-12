let eventAnalyticsState = {
  loaded: false,
  facets: null,
  mode: 'user',
  dimension: 'auth_method',
  selectedUser: '',
  selectedValue: '',
};

let eventAnalyticsCharts = {
  volume: null,
  cost: null,
  auth: null,
  ocr: null,
  parsing: null,
};

const EVENT_DIMENSION_OPTIONS = [
  { value: 'auth_method', label: 'Auth Method' },
  { value: 'ocr_model', label: 'OCR Model' },
  { value: 'parsing_model', label: 'Parsing Model' },
  { value: 'endpoint', label: 'Endpoint' },
  { value: 'source_type', label: 'Source Type' },
  { value: 'prompt', label: 'Prompt' },
  { value: 'success', label: 'Success Flag' },
];

const EVENT_AUTH_COLORS = {
  server: '#4285f4',
  user_gemini: '#fbbc05',
  user_vertex: '#34a853',
  unknown: '#9ca3af',
};

function fmtEventUSD(n) {
  const num = Number(n || 0);
  return `$${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtEventCount(n) {
  return Number(n || 0).toLocaleString();
}

function fmtEventPct(numerator, denominator) {
  if (!denominator) return '0.0%';
  return `${((Number(numerator || 0) / Number(denominator || 0)) * 100).toFixed(1)}%`;
}

function escapeEventHtml(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function destroyEventCharts() {
  Object.keys(eventAnalyticsCharts).forEach(key => {
    if (eventAnalyticsCharts[key]) {
      eventAnalyticsCharts[key].destroy();
      eventAnalyticsCharts[key] = null;
    }
  });
}

function ensureEventChartJs() {
  if (typeof Chart !== 'undefined') {
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.3.0/dist/chart.umd.min.js';
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Failed to load Chart.js'));
    document.head.appendChild(script);
  });
}

function getFacetValuesForDimension(dimension) {
  const facets = (eventAnalyticsState.facets || {}).facets || {};
  switch (dimension) {
    case 'auth_method':
      return facets.auth_methods || [];
    case 'ocr_model':
      return facets.ocr_models || [];
    case 'parsing_model':
      return facets.parsing_models || [];
    case 'endpoint':
      return facets.endpoints || [];
    case 'source_type':
      return facets.source_types || [];
    case 'prompt':
      return facets.prompts || [];
    case 'success':
      return ['true', 'false'];
    default:
      return [];
  }
}

function buildEventAnalyticsQuery(baseParams = {}) {
  const params = new URLSearchParams();
  Object.entries(baseParams).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      params.set(key, value);
    }
  });

  const dateFrom = document.getElementById('ea-date-from')?.value;
  const dateTo = document.getElementById('ea-date-to')?.value;
  const authMethod = document.getElementById('ea-secondary-auth')?.value;
  const sourceType = document.getElementById('ea-secondary-source')?.value;

  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  if (authMethod) params.set('auth_method', authMethod);
  if (sourceType) params.set('source_type', sourceType);

  return params;
}

function renderEventAnalyticsShell() {
  const container = document.getElementById('event-analytics-container');
  const facets = eventAnalyticsState.facets || {};
  const firstTracked = facets.first_tracked_event_at
    ? new Date(facets.first_tracked_event_at).toLocaleString()
    : 'after deployment';

  container.innerHTML = `
    <div class="ea-banner">
      Event-level analytics are forward-only. This view includes requests tracked from
      <strong>${escapeEventHtml(firstTracked)}</strong> onward; older history remains in aggregate rollups.
    </div>

    <div class="ea-controls">
      <div class="ea-mode-toggle">
        <button type="button" class="ea-toggle-btn ${eventAnalyticsState.mode === 'user' ? 'active' : ''}" data-mode="user">User Overview</button>
        <button type="button" class="ea-toggle-btn ${eventAnalyticsState.mode === 'dimension' ? 'active' : ''}" data-mode="dimension">Metadata Overview</button>
      </div>

      <div class="ea-control-grid">
        <label class="ea-control">
          <span>Mode Target</span>
          <select id="ea-target-select"></select>
        </label>
        <label class="ea-control ${eventAnalyticsState.mode === 'dimension' ? '' : 'ea-hidden'}" id="ea-dimension-wrap">
          <span>Dimension</span>
          <select id="ea-dimension-select">
            ${EVENT_DIMENSION_OPTIONS.map(option => `
              <option value="${option.value}" ${option.value === eventAnalyticsState.dimension ? 'selected' : ''}>
                ${escapeEventHtml(option.label)}
              </option>
            `).join('')}
          </select>
        </label>
        <label class="ea-control">
          <span>Date From</span>
          <input type="date" id="ea-date-from">
        </label>
        <label class="ea-control">
          <span>Date To</span>
          <input type="date" id="ea-date-to">
        </label>
        <label class="ea-control">
          <span>Secondary Auth Filter</span>
          <select id="ea-secondary-auth">
            <option value="">All auth methods</option>
            ${((facets.facets || {}).auth_methods || []).map(value => `<option value="${escapeEventHtml(value)}">${escapeEventHtml(value)}</option>`).join('')}
          </select>
        </label>
        <label class="ea-control">
          <span>Secondary Source Filter</span>
          <select id="ea-secondary-source">
            <option value="">All source types</option>
            ${((facets.facets || {}).source_types || []).map(value => `<option value="${escapeEventHtml(value)}">${escapeEventHtml(value)}</option>`).join('')}
          </select>
        </label>
      </div>
    </div>

    <div id="ea-summary"></div>
  `;

  bindEventAnalyticsControls();
  populateEventAnalyticsTargetSelect();
}

function populateEventAnalyticsTargetSelect() {
  const select = document.getElementById('ea-target-select');
  if (!select) return;

  let options = [];
  if (eventAnalyticsState.mode === 'user') {
    options = ((eventAnalyticsState.facets || {}).facets || {}).users || [];
    if ((!eventAnalyticsState.selectedUser || !options.includes(eventAnalyticsState.selectedUser)) && options.length) {
      eventAnalyticsState.selectedUser = options[0];
    }
    select.innerHTML = options.map(value => `
      <option value="${escapeEventHtml(value)}" ${value === eventAnalyticsState.selectedUser ? 'selected' : ''}>
        ${escapeEventHtml(value)}
      </option>
    `).join('');
  } else {
    options = getFacetValuesForDimension(eventAnalyticsState.dimension);
    if ((!eventAnalyticsState.selectedValue || !options.map(String).includes(String(eventAnalyticsState.selectedValue))) && options.length) {
      eventAnalyticsState.selectedValue = options[0];
    }
    select.innerHTML = options.map(value => `
      <option value="${escapeEventHtml(value)}" ${String(value) === String(eventAnalyticsState.selectedValue) ? 'selected' : ''}>
        ${escapeEventHtml(value)}
      </option>
    `).join('');
  }
}

function bindEventAnalyticsControls() {
  document.querySelectorAll('.ea-toggle-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      eventAnalyticsState.mode = btn.dataset.mode;
      if (eventAnalyticsState.mode === 'dimension') {
        eventAnalyticsState.selectedValue = '';
      }
      renderEventAnalyticsShell();
      await refreshEventAnalyticsOverview();
    });
  });

  const dimensionSelect = document.getElementById('ea-dimension-select');
  if (dimensionSelect) {
    dimensionSelect.addEventListener('change', async (event) => {
      eventAnalyticsState.dimension = event.target.value;
      eventAnalyticsState.selectedValue = '';
      populateEventAnalyticsTargetSelect();
      await refreshEventAnalyticsOverview();
    });
  }

  const targetSelect = document.getElementById('ea-target-select');
  if (targetSelect) {
    targetSelect.addEventListener('change', async (event) => {
      if (eventAnalyticsState.mode === 'user') {
        eventAnalyticsState.selectedUser = event.target.value;
      } else {
        eventAnalyticsState.selectedValue = event.target.value;
      }
      await refreshEventAnalyticsOverview();
    });
  }

  ['ea-date-from', 'ea-date-to', 'ea-secondary-auth', 'ea-secondary-source'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('change', async () => {
        await refreshEventAnalyticsOverview();
      });
    }
  });
}

function renderEventAnalyticsSummary(data) {
  const headline = data.headline || {};
  const failureRate = fmtEventPct(headline.failure_count, headline.total_events);
  const recentEvents = data.recent_events || [];

  const ocrRows = Object.entries(data.ocr_model_mix || {})
    .sort((a, b) => (b[1].cost_usd || 0) - (a[1].cost_usd || 0))
    .slice(0, 8);
  const parsingRows = Object.entries(data.parsing_model_mix || {})
    .sort((a, b) => (b[1].cost_usd || 0) - (a[1].cost_usd || 0))
    .slice(0, 8);

  const summary = document.getElementById('ea-summary');
  summary.innerHTML = `
    <div class="ea-kpis">
      <div class="ea-kpi">
        <div class="ea-kpi-label">Matching Events</div>
        <div class="ea-kpi-value">${fmtEventCount(headline.total_events)}</div>
      </div>
      <div class="ea-kpi">
        <div class="ea-kpi-label">Estimated Cost</div>
        <div class="ea-kpi-value">${fmtEventUSD(headline.total_cost_usd)}</div>
        <div class="ea-kpi-sub">Avg ${fmtEventUSD(headline.average_cost_usd)} / event</div>
      </div>
      <div class="ea-kpi">
        <div class="ea-kpi-label">Total Tokens</div>
        <div class="ea-kpi-value">${fmtEventCount(headline.total_tokens_all)}</div>
      </div>
      <div class="ea-kpi">
        <div class="ea-kpi-label">Failures</div>
        <div class="ea-kpi-value">${fmtEventCount(headline.failure_count)}</div>
        <div class="ea-kpi-sub">${failureRate} of matching events</div>
      </div>
      <div class="ea-kpi">
        <div class="ea-kpi-label">PDF Pages</div>
        <div class="ea-kpi-value">${fmtEventCount(headline.total_pdf_pages)}</div>
      </div>
      <div class="ea-kpi">
        <div class="ea-kpi-label">Unique Users</div>
        <div class="ea-kpi-value">${fmtEventCount(headline.unique_users)}</div>
      </div>
    </div>

    <div class="ea-chart-grid">
      <div class="ea-panel">
        <h4>Event Volume Over Time</h4>
        <div class="ea-chart-wrap"><canvas id="ea-volume-chart"></canvas></div>
      </div>
      <div class="ea-panel">
        <h4>Estimated Cost Over Time</h4>
        <div class="ea-chart-wrap"><canvas id="ea-cost-chart"></canvas></div>
      </div>
      <div class="ea-panel">
        <h4>Auth Method Split</h4>
        <div class="ea-chart-wrap"><canvas id="ea-auth-chart"></canvas></div>
      </div>
      <div class="ea-panel">
        <h4>OCR Model Mix</h4>
        <div class="ea-chart-wrap"><canvas id="ea-ocr-chart"></canvas></div>
      </div>
      <div class="ea-panel">
        <h4>Parsing Model Mix</h4>
        <div class="ea-chart-wrap"><canvas id="ea-parsing-chart"></canvas></div>
      </div>
      <div class="ea-panel">
        <h4>Failure Snapshot</h4>
        <div class="ea-failure-box">
          <div><strong>Successful events:</strong> ${fmtEventCount(headline.success_count)}</div>
          <div><strong>Failed events:</strong> ${fmtEventCount(headline.failure_count)}</div>
          <div><strong>Failure rate:</strong> ${failureRate}</div>
        </div>
      </div>
    </div>

    <div class="ea-panel">
      <h4>Recent Matching Events</h4>
      <div class="ea-table-wrap">
        <table class="ea-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>User</th>
              <th>Auth</th>
              <th>Source</th>
              <th>OCR</th>
              <th>Parsing</th>
              <th>Success</th>
              <th>Cost</th>
              <th>Tokens</th>
            </tr>
          </thead>
          <tbody>
            ${recentEvents.map(event => `
              <tr>
                <td>${escapeEventHtml(event.created_at || '')}</td>
                <td>${escapeEventHtml(event.user_email || '')}</td>
                <td>${escapeEventHtml(event.auth_method || '')}</td>
                <td>${escapeEventHtml(event.source_type || '')}</td>
                <td>${escapeEventHtml((event.ocr_models || []).join(', '))}</td>
                <td>${escapeEventHtml(event.parsing_model || 'none')}</td>
                <td>${event.success ? 'Yes' : 'No'}</td>
                <td>${fmtEventUSD(event.total_request_cost_usd)}</td>
                <td>${fmtEventCount(event.total_tokens_all)}</td>
              </tr>
            `).join('') || '<tr><td colspan="9">No matching events found.</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>
  `;

  renderEventAnalyticsCharts(data, ocrRows, parsingRows);
}

function renderEventAnalyticsCharts(data, ocrRows, parsingRows) {
  destroyEventCharts();

  const daily = (data.timeseries || {}).daily || [];
  const authSplit = data.auth_method_split || {};

  eventAnalyticsCharts.volume = new Chart(document.getElementById('ea-volume-chart'), {
    type: 'bar',
    data: {
      labels: daily.map(row => row.date),
      datasets: [{
        label: 'Events',
        data: daily.map(row => row.events),
        backgroundColor: '#4285f4',
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
    },
  });

  eventAnalyticsCharts.cost = new Chart(document.getElementById('ea-cost-chart'), {
    type: 'line',
    data: {
      labels: daily.map(row => row.date),
      datasets: [{
        label: 'Estimated Cost',
        data: daily.map(row => Number(row.cost_usd || 0)),
        borderColor: '#34a853',
        backgroundColor: 'rgba(52,168,83,0.18)',
        fill: true,
        tension: 0.25,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: {
          ticks: { callback: value => fmtEventUSD(value) },
        },
      },
    },
  });

  eventAnalyticsCharts.auth = new Chart(document.getElementById('ea-auth-chart'), {
    type: 'doughnut',
    data: {
      labels: Object.keys(authSplit),
      datasets: [{
        data: Object.values(authSplit).map(bucket => Number(bucket.events || 0)),
        backgroundColor: Object.keys(authSplit).map(key => EVENT_AUTH_COLORS[key] || EVENT_AUTH_COLORS.unknown),
        borderWidth: 0,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
    },
  });

  eventAnalyticsCharts.ocr = new Chart(document.getElementById('ea-ocr-chart'), {
    type: 'bar',
    data: {
      labels: ocrRows.map(([name]) => name),
      datasets: [{
        label: 'Cost',
        data: ocrRows.map(([, bucket]) => Number(bucket.cost_usd || 0)),
        backgroundColor: '#8b5cf6',
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          ticks: { callback: value => fmtEventUSD(value) },
        },
      },
    },
  });

  eventAnalyticsCharts.parsing = new Chart(document.getElementById('ea-parsing-chart'), {
    type: 'bar',
    data: {
      labels: parsingRows.map(([name]) => name),
      datasets: [{
        label: 'Cost',
        data: parsingRows.map(([, bucket]) => Number(bucket.cost_usd || 0)),
        backgroundColor: '#f59e0b',
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          ticks: { callback: value => fmtEventUSD(value) },
        },
      },
    },
  });
}

async function refreshEventAnalyticsOverview() {
  const summary = document.getElementById('ea-summary');
  if (!summary) return;
  if (eventAnalyticsState.mode === 'user' && !eventAnalyticsState.selectedUser) {
    summary.innerHTML = '<div class="ea-panel">No tracked users yet. Event analytics will populate as new requests are recorded.</div>';
    return;
  }
  if (eventAnalyticsState.mode === 'dimension' && !eventAnalyticsState.selectedValue) {
    summary.innerHTML = '<div class="ea-panel">No values are available for this metadata dimension yet.</div>';
    return;
  }
  summary.innerHTML = '<div class="loading">Loading event overview…</div>';

  const idToken = await firebase.auth().currentUser.getIdToken();
  const baseParams = eventAnalyticsState.mode === 'user'
    ? { scope: 'user', user_email: eventAnalyticsState.selectedUser }
    : {
        scope: 'dimension',
        dimension: eventAnalyticsState.dimension,
        value: eventAnalyticsState.selectedValue,
      };
  const params = buildEventAnalyticsQuery(baseParams);

  const response = await fetch(`/admin/usage-events/overview?${params.toString()}`, {
    headers: { 'Authorization': `Bearer ${idToken}` },
  });

  if (!response.ok) {
    throw new Error(`Server returned ${response.status}: ${response.statusText}`);
  }

  const data = await response.json();
  if (data.status !== 'success') {
    throw new Error(data.error || 'Failed to load event overview');
  }

  renderEventAnalyticsSummary(data);
}

async function loadEventAnalytics() {
  const container = document.getElementById('event-analytics-container');
  if (!container) return;

  try {
    await ensureEventChartJs();
    const idToken = await firebase.auth().currentUser.getIdToken();

    if (!eventAnalyticsState.facets) {
      const response = await fetch('/admin/usage-events/facets', {
        headers: { 'Authorization': `Bearer ${idToken}` },
      });
      if (!response.ok) {
        throw new Error(`Server returned ${response.status}: ${response.statusText}`);
      }
      const data = await response.json();
      if (data.status !== 'success') {
        throw new Error(data.error || 'Failed to load usage event facets');
      }
      eventAnalyticsState.facets = data;
    }

    renderEventAnalyticsShell();
    await refreshEventAnalyticsOverview();
    eventAnalyticsState.loaded = true;
  } catch (error) {
    console.error('Error loading event analytics:', error);
    container.innerHTML = `<div class="alert alert-danger">Error loading event analytics: ${escapeEventHtml(error.message)}</div>`;
  }
}

window.loadEventAnalytics = loadEventAnalytics;
