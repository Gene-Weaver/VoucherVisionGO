let eventAnalyticsState = {
  loaded: false,
  shellRendered: false,
  running: false,
  requestController: null,
};

let eventAnalyticsCharts = {
  volume: null,
  cost: null,
  auth: null,
  ocr: null,
  parsing: null,
};

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
  const ocrModel = document.getElementById('ea-ocr-model')?.value.trim();
  const parsingModel = document.getElementById('ea-parsing-model')?.value.trim();
  const endpoint = document.getElementById('ea-endpoint')?.value.trim();
  const prompt = document.getElementById('ea-prompt')?.value.trim();
  const success = document.getElementById('ea-success')?.value;

  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  if (authMethod) params.set('auth_method', authMethod);
  if (sourceType) params.set('source_type', sourceType);
  if (ocrModel) params.set('ocr_model', ocrModel);
  if (parsingModel) params.set('parsing_model', parsingModel);
  if (endpoint) params.set('endpoint', endpoint);
  if (prompt) params.set('prompt', prompt);
  if (success) params.set('success', success);

  return params;
}

function eventAnalyticsDefaultDates() {
  const dateTo = new Date();
  const dateFrom = new Date(dateTo);
  dateFrom.setDate(dateFrom.getDate() - 29);
  const format = value => value.toISOString().slice(0, 10);
  return { dateFrom: format(dateFrom), dateTo: format(dateTo) };
}

function renderEventAnalyticsShell() {
  const container = document.getElementById('event-analytics-container');
  const defaults = eventAnalyticsDefaultDates();

  container.innerHTML = `
    <div class="ea-banner">
      Opening this tab does not query Firestore. Choose a user and date range, then explicitly
      press <strong>Perform analytics</strong>.
    </div>

    <div class="ea-controls">
      <div class="ea-control-grid">
        <label class="ea-control">
          <span>User email *</span>
          <input type="email" id="ea-user-email" placeholder="user@example.org" autocomplete="off">
        </label>
        <label class="ea-control">
          <span>Date From</span>
          <input type="date" id="ea-date-from" value="${defaults.dateFrom}">
        </label>
        <label class="ea-control">
          <span>Date To</span>
          <input type="date" id="ea-date-to" value="${defaults.dateTo}">
        </label>
        <label class="ea-control">
          <span>Secondary Auth Filter</span>
          <select id="ea-secondary-auth">
            <option value="">All auth methods</option>
            <option value="server">Server</option>
            <option value="user_gemini">User Gemini</option>
            <option value="user_vertex">User Vertex</option>
          </select>
        </label>
        <label class="ea-control">
          <span>Secondary Source Filter</span>
          <select id="ea-secondary-source">
            <option value="">All source types</option>
            <option value="upload">Upload</option>
            <option value="url">URL</option>
            <option value="pdf_page">PDF page</option>
          </select>
        </label>
        <label class="ea-control">
          <span>OCR Model (optional)</span>
          <input type="text" id="ea-ocr-model" placeholder="Exact model name">
        </label>
        <label class="ea-control">
          <span>Parsing Model (optional)</span>
          <input type="text" id="ea-parsing-model" placeholder="Exact model name">
        </label>
        <label class="ea-control">
          <span>Endpoint (optional)</span>
          <input type="text" id="ea-endpoint" placeholder="/process-url">
        </label>
        <label class="ea-control">
          <span>Prompt (optional)</span>
          <input type="text" id="ea-prompt" placeholder="Exact prompt name">
        </label>
        <label class="ea-control">
          <span>Success</span>
          <select id="ea-success">
            <option value="">Success and failure</option>
            <option value="true">Success only</option>
            <option value="false">Failure only</option>
          </select>
        </label>
      </div>

      <label class="ea-full-scan-option">
        <input type="checkbox" id="ea-full-scan">
        <span><strong>Full database scan</strong> — ignores the user and date fields. This reads every
        usage event, can be slow and costly, and may temporarily consume Cloud Run resources.</span>
      </label>

      <div class="ea-actions">
        <button type="button" id="ea-perform-btn" class="btn btn-primary">Perform analytics</button>
        <span id="ea-validation-message"></span>
      </div>
    </div>

    <div id="ea-summary" class="ea-panel">No analytics query has been performed.</div>

    <div class="ea-panel ea-maintenance-panel">
      <h4>Analytics rollup index</h4>
      <p>New events update compact daily per-user rollups automatically. Use this maintenance action
      once after deployment to build historical rollups. It scans all existing usage events and may
      incur Firestore read charges.</p>
      <button type="button" id="ea-ensure-index-btn" class="btn btn-secondary">Create / verify Firestore query index</button>
      <span id="ea-ensure-index-status"></span>
      <br><br>
      <button type="button" id="ea-rebuild-rollups-btn" class="btn btn-secondary">Build / refresh analytics rollups</button>
      <span id="ea-rebuild-rollups-status"></span>
    </div>
  `;

  bindEventAnalyticsControls();
}

function markEventAnalyticsDirty() {
  const message = document.getElementById('ea-validation-message');
  if (eventAnalyticsState.loaded && message) {
    message.textContent = 'Filters changed. Press Perform analytics to update the results.';
  }
}

function bindEventAnalyticsControls() {
  const filterIds = [
    'ea-user-email', 'ea-date-from', 'ea-date-to', 'ea-secondary-auth',
    'ea-secondary-source', 'ea-ocr-model', 'ea-parsing-model', 'ea-endpoint',
    'ea-prompt', 'ea-success',
  ];
  filterIds.forEach(id => {
    document.getElementById(id)?.addEventListener('change', markEventAnalyticsDirty);
  });

  document.getElementById('ea-full-scan')?.addEventListener('change', event => {
    const disabled = event.target.checked;
    filterIds.forEach(id => { document.getElementById(id).disabled = disabled; });
    markEventAnalyticsDirty();
  });
  document.getElementById('ea-perform-btn')?.addEventListener('click', performEventAnalytics);
  document.getElementById('ea-ensure-index-btn')?.addEventListener('click', ensureEventAnalyticsIndex);
  document.getElementById('ea-rebuild-rollups-btn')?.addEventListener('click', rebuildEventAnalyticsRollups);
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
            `).join('') || `<tr><td colspan="9">${data.analysis_source === 'daily_rollups'
              ? 'Raw recent-event rows are omitted in the rollup-optimized view.'
              : 'No matching events found.'}</td></tr>`}
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

async function performEventAnalytics() {
  const summary = document.getElementById('ea-summary');
  if (!summary) return;
  if (eventAnalyticsState.running) return;

  const fullScan = document.getElementById('ea-full-scan')?.checked === true;
  const userEmail = document.getElementById('ea-user-email')?.value.trim();
  const dateFrom = document.getElementById('ea-date-from')?.value;
  const dateTo = document.getElementById('ea-date-to')?.value;
  const message = document.getElementById('ea-validation-message');
  const button = document.getElementById('ea-perform-btn');

  if (!fullScan && !userEmail) {
    message.textContent = 'Enter a user email before performing analytics.';
    return;
  }
  if (!fullScan && (!dateFrom || !dateTo)) {
    message.textContent = 'Select both a start date and an end date.';
    return;
  }
  if (!fullScan && dateFrom > dateTo) {
    message.textContent = 'Date From must be on or before Date To.';
    return;
  }
  if (fullScan && !confirm(
    'This will read the entire usage_events collection. It can be slow, costly, and resource intensive. Continue?'
  )) return;

  eventAnalyticsState.running = true;
  if (button) {
    button.disabled = true;
    button.textContent = 'Performing analytics…';
  }
  if (message) message.textContent = fullScan ? 'Running costly full scan…' : 'Querying selected user and dates…';
  summary.innerHTML = '<div class="loading">Loading event overview…</div>';

  try {
    if (eventAnalyticsState.requestController) eventAnalyticsState.requestController.abort();
    eventAnalyticsState.requestController = new AbortController();
    const idToken = await firebase.auth().currentUser.getIdToken();
    const params = fullScan
      ? new URLSearchParams({ scope: 'user', full_scan: 'true' })
      : buildEventAnalyticsQuery({ scope: 'user', user_email: userEmail });

    const response = await fetch(`/admin/usage-events/overview?${params.toString()}`, {
      headers: { 'Authorization': `Bearer ${idToken}` },
      signal: eventAnalyticsState.requestController.signal,
    });
    const data = await response.json();
    if (!response.ok || data.status !== 'success') {
      throw new Error(data.error || `Server returned ${response.status}`);
    }

    await ensureEventChartJs();
    renderEventAnalyticsSummary(data);
    eventAnalyticsState.loaded = true;
    if (message) {
      const sourceLabel = data.analysis_source === 'daily_rollups' ? 'daily rollups' : 'raw events';
      message.textContent = `Complete from ${sourceLabel}: ${fmtEventCount(data.headline?.total_events)} events in ${fmtEventCount(data.elapsed_ms)} ms.`;
    }
  } catch (error) {
    console.error('Error loading event analytics:', error);
    summary.innerHTML = `<div class="alert alert-danger">Error loading event analytics: ${escapeEventHtml(error.message)}</div>`;
    if (message) message.textContent = 'Analytics failed.';
  } finally {
    eventAnalyticsState.running = false;
    if (button) {
      button.disabled = false;
      button.textContent = 'Perform analytics';
    }
  }
}

async function rebuildEventAnalyticsRollups() {
  const button = document.getElementById('ea-rebuild-rollups-btn');
  const status = document.getElementById('ea-rebuild-rollups-status');
  if (!button) return;
  if (!confirm(
    'Build or refresh daily analytics rollups by scanning every existing usage event? This is costly but safe to re-run.'
  )) return;

  button.disabled = true;
  if (status) status.textContent = 'Building rollups… keep this page open.';
  try {
    const idToken = await firebase.auth().currentUser.getIdToken();
    const response = await fetch('/admin/rebuild-event-analytics-rollups', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${idToken}`,
        'Content-Type': 'application/json',
      },
    });
    const data = await response.json();
    if (!response.ok || data.status !== 'success') {
      throw new Error(data.error || `Server returned ${response.status}`);
    }
    if (status) status.textContent =
      `Complete: scanned ${fmtEventCount(data.events_scanned)} events and wrote ` +
      `${fmtEventCount(data.rollup_docs_written)} daily rollups.`;
  } catch (error) {
    console.error('Event analytics rollup rebuild failed:', error);
    if (status) status.textContent = `Failed: ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

async function ensureEventAnalyticsIndex() {
  const button = document.getElementById('ea-ensure-index-btn');
  const status = document.getElementById('ea-ensure-index-status');
  if (!button) return;
  if (!confirm(
    'Create or verify the managed Firestore index used by filtered event analytics? Index creation runs in the background.'
  )) return;

  button.disabled = true;
  if (status) status.textContent = 'Checking Firestore index…';
  try {
    const idToken = await firebase.auth().currentUser.getIdToken();
    const response = await fetch('/admin/ensure-event-analytics-index', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${idToken}`,
        'Content-Type': 'application/json',
      },
    });
    const data = await response.json();
    if (!response.ok || data.status !== 'success') {
      throw new Error(data.error || `Server returned ${response.status}`);
    }
    if (status) status.textContent = `${data.message} State: ${data.index_state}.`;
  } catch (error) {
    console.error('Firestore analytics index setup failed:', error);
    if (status) status.textContent = `Failed: ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

function loadEventAnalytics() {
  const container = document.getElementById('event-analytics-container');
  if (!container || eventAnalyticsState.shellRendered) return;
  renderEventAnalyticsShell();
  eventAnalyticsState.shellRendered = true;
}

window.loadEventAnalytics = loadEventAnalytics;
