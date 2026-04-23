// Cost Analytics tab renderer.
// Fetches /admin/cost-analytics and renders headline KPIs, monthly trend,
// per-model cost, daily token bars, top-users table, overhead breakdown.

let costAnalyticsState = {
  report: null,
  selectedMonth: null,
  dailyTimeframe: 'month', // 'month' | '90d' | 'all'
};

let costCharts = {
  monthly: null,
  perModel: null,
  rate: null,
  daily: null,
};

async function loadCostAnalytics() {
  const container = document.getElementById('cost-analytics-container');
  const loading = document.getElementById('cost-analytics-loading');
  if (loading) loading.style.display = 'block';

  try {
    const idToken = await firebase.auth().currentUser.getIdToken();
    const response = await fetch('/admin/cost-analytics', {
      headers: { 'Authorization': `Bearer ${idToken}` },
    });
    if (!response.ok) {
      throw new Error(`Server returned ${response.status}: ${response.statusText}`);
    }
    const data = await response.json();
    if (data.status !== 'success') {
      throw new Error(data.error || 'Unknown error');
    }

    costAnalyticsState.report = data;
    const months = data.months || [];
    costAnalyticsState.selectedMonth = months.length ? months[months.length - 1] : null;

    // Ensure Chart.js is loaded (reuse the loader pattern from usage_stats.js).
    if (typeof Chart === 'undefined') {
      await loadChartJs();
    }

    renderCostAnalytics();
  } catch (err) {
    console.error('Cost analytics load failed:', err);
    container.innerHTML = `<div class="alert alert-danger">
      <strong>Error loading cost analytics:</strong> ${escapeHtml(err.message)}
    </div>`;
  }
}

function loadChartJs() {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.3.0/dist/chart.umd.min.js';
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Failed to load Chart.js'));
    document.head.appendChild(script);
  });
}

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function fmtUSD(n) {
  if (n == null || isNaN(n)) return '—';
  const abs = Math.abs(n);
  if (abs < 0.01 && n !== 0) return `$${n.toFixed(4)}`;
  return `$${Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtCents(n) {
  if (n == null || isNaN(n)) return '—';
  return `$${Number(n).toFixed(4)}`;
}

function fmtInt(n) {
  if (n == null || isNaN(n)) return '—';
  return Number(n).toLocaleString('en-US');
}

function renderCostAnalytics() {
  const container = document.getElementById('cost-analytics-container');
  const r = costAnalyticsState.report;
  if (!r) return;

  const months = r.months || [];
  if (!months.length) {
    container.innerHTML = `<p>No invoices found in the bucket yet.
      Drop monthly CSVs in <code>gs://vouchervision-cop90-rasters/invoices/</code> and reload.</p>`;
    return;
  }

  const sel = costAnalyticsState.selectedMonth;
  const m = r.per_month[sel] || {};
  const all = r.all_time || {};

  container.innerHTML = `
    <style>
      .cost-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 20px; }
      .cost-kpi { background: #f7f9fc; border: 1px solid #e3e8ef; border-radius: 6px; padding: 14px; }
      .cost-kpi .label { font-size: 12px; color: #5a6475; text-transform: uppercase; letter-spacing: .03em; }
      .cost-kpi .value { font-size: 22px; font-weight: 600; margin-top: 4px; color: #1f2937; }
      .cost-kpi .sub { font-size: 12px; color: #6b7280; margin-top: 2px; }
      .cost-section { margin-bottom: 30px; }
      .cost-section h4 { margin: 0 0 10px 0; color: #1f2937; }
      .cost-month-select { margin-bottom: 14px; }
      .cost-two-col { display: grid; grid-template-columns: 1.4fr 1fr; gap: 20px; }
      .cost-table { width: 100%; border-collapse: collapse; font-size: 13px; }
      .cost-table th, .cost-table td { padding: 6px 10px; text-align: left; border-bottom: 1px solid #eef1f5; }
      .cost-table th { background: #f3f5f8; font-weight: 600; }
      .cost-table td.num, .cost-table th.num { text-align: right; font-variant-numeric: tabular-nums; }
      .cost-timeframe { display: inline-flex; gap: 6px; margin-left: 10px; }
      .cost-timeframe button { padding: 4px 10px; border: 1px solid #ced4da; background: #fff; cursor: pointer; border-radius: 4px; }
      .cost-timeframe button.active { background: #1f6feb; color: #fff; border-color: #1f6feb; }
      .cost-warning { background: #fff7ed; border: 1px solid #fed7aa; color: #7c2d12; padding: 10px 14px; border-radius: 6px; margin-bottom: 14px; }
      .cost-note { color: #6b7280; font-size: 12px; font-style: italic; margin-top: 6px; }
      canvas.cost-chart { max-height: 320px; }
    </style>

    <div class="cost-kpis">
      <div class="cost-kpi">
        <div class="label">Break-even price / specimen</div>
        <div class="value">${fmtCents(all.break_even_price_per_specimen)}</div>
        <div class="sub">All-time blended (LLM + overhead ÷ specimens)</div>
      </div>
      <div class="cost-kpi">
        <div class="label">$/specimen (${sel})</div>
        <div class="value">${fmtCents(m.cost_per_specimen && m.cost_per_specimen.total)}</div>
        <div class="sub">LLM ${fmtCents(m.cost_per_specimen && m.cost_per_specimen.llm)} + overhead ${fmtCents(m.cost_per_specimen && m.cost_per_specimen.overhead)}</div>
      </div>
      <div class="cost-kpi">
        <div class="label">Total spent (all-time)</div>
        <div class="value">${fmtUSD(all.total_cost)}</div>
        <div class="sub">LLM ${fmtUSD(all.llm_cost)} · overhead ${fmtUSD(all.overhead_cost)}</div>
      </div>
      <div class="cost-kpi">
        <div class="label">Total specimens (all-time)</div>
        <div class="value">${fmtInt(all.total_specimens)}</div>
        <div class="sub">${months.length} month${months.length === 1 ? '' : 's'} of invoices</div>
      </div>
    </div>

    <div class="cost-month-select">
      <label for="cost-month">Month: </label>
      <select id="cost-month">
        ${months.map(mo => `<option value="${mo}" ${mo === sel ? 'selected' : ''}>${mo}</option>`).join('')}
      </select>
    </div>

    ${(m.unclassified_skus && m.unclassified_skus.length) ? `
      <div class="cost-warning">
        <strong>${m.unclassified_skus.length} LLM SKU(s) had no model extracted</strong> — extend
        <code>_MODEL_PATTERNS</code> in <code>cost_analytics.py</code>. Affected SKUs:
        <ul>${m.unclassified_skus.map(u => `<li>${escapeHtml(u.sku)} (${fmtUSD(u.cost)})</li>`).join('')}</ul>
      </div>
    ` : ''}

    <div class="cost-section">
      <h4>Monthly trend</h4>
      <canvas id="cost-monthly-chart" class="cost-chart"></canvas>
      <div class="cost-note">Stacked bars = LLM vs overhead per month. Line = $/specimen.</div>
    </div>

    <div class="cost-section cost-two-col">
      <div>
        <h4>Cost per model (${sel})</h4>
        <canvas id="cost-per-model-chart" class="cost-chart"></canvas>
      </div>
      <div>
        <h4>Blended $/Mtok by model (${sel})</h4>
        <canvas id="cost-rate-chart" class="cost-chart"></canvas>
      </div>
    </div>

    <div class="cost-section">
      <h4>Daily tokens
        <span class="cost-timeframe">
          <button data-tf="month" class="${costAnalyticsState.dailyTimeframe === 'month' ? 'active' : ''}">${sel}</button>
          <button data-tf="90d" class="${costAnalyticsState.dailyTimeframe === '90d' ? 'active' : ''}">Last 90d</button>
          <button data-tf="all" class="${costAnalyticsState.dailyTimeframe === 'all' ? 'active' : ''}">All months</button>
        </span>
      </h4>
      <canvas id="cost-daily-chart" class="cost-chart"></canvas>
      <div class="cost-note">Reconstructed from daily image counts × each user's lifetime tokens-per-image, scaled so the month sums match the invoice's token totals.</div>
    </div>

    <div class="cost-section cost-two-col">
      <div>
        <h4>Top users by estimated cost (${sel})</h4>
        <table class="cost-table">
          <thead><tr><th>Email</th><th class="num">Specimens</th><th class="num">Est. $</th><th class="num">$/specimen</th><th>Top model</th></tr></thead>
          <tbody>
            ${(m.per_user_top20 || []).map(u => `
              <tr>
                <td>${escapeHtml(u.email)}</td>
                <td class="num">${fmtInt(u.specimens)}</td>
                <td class="num">${fmtUSD(u.est_total_cost)}</td>
                <td class="num">${fmtCents(u.cost_per_specimen)}</td>
                <td>${escapeHtml(u.top_model || '—')}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
        <div class="cost-note">${fmtInt(m.per_user_count || 0)} total users active this month. Per-user attribution uses each user's lifetime model-mix as a proxy; add forward per-model tracking for exact attribution.</div>
      </div>
      <div>
        <h4>Overhead breakdown (${sel})</h4>
        <table class="cost-table">
          <thead><tr><th>SKU</th><th class="num">$</th><th class="num">%</th></tr></thead>
          <tbody>
            ${(m.overhead_breakdown || []).map(o => `
              <tr>
                <td>${escapeHtml(o.sku)}</td>
                <td class="num">${fmtUSD(o.cost)}</td>
                <td class="num">${m.overhead_cost ? ((o.cost / m.overhead_cost) * 100).toFixed(1) : '0.0'}%</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;

  // Wire up month selector.
  const monthSelect = document.getElementById('cost-month');
  if (monthSelect) {
    monthSelect.addEventListener('change', e => {
      costAnalyticsState.selectedMonth = e.target.value;
      renderCostAnalytics();
    });
  }

  // Wire up timeframe buttons.
  document.querySelectorAll('.cost-timeframe button').forEach(btn => {
    btn.addEventListener('click', () => {
      costAnalyticsState.dailyTimeframe = btn.dataset.tf;
      renderDailyChart();
      document.querySelectorAll('.cost-timeframe button').forEach(b => b.classList.toggle('active', b === btn));
    });
  });

  // Render charts after DOM is in place.
  renderMonthlyChart();
  renderPerModelChart();
  renderRateChart();
  renderDailyChart();
}

function destroyChart(key) {
  if (costCharts[key]) {
    costCharts[key].destroy();
    costCharts[key] = null;
  }
}

function renderMonthlyChart() {
  const r = costAnalyticsState.report;
  const ctx = document.getElementById('cost-monthly-chart');
  if (!ctx || !r) return;
  destroyChart('monthly');
  const months = r.months;
  const llm = months.map(mo => r.per_month[mo].llm_cost);
  const ovh = months.map(mo => r.per_month[mo].overhead_cost);
  const perSpec = months.map(mo => r.per_month[mo].cost_per_specimen.total);
  costCharts.monthly = new Chart(ctx, {
    data: {
      labels: months,
      datasets: [
        { type: 'bar', label: 'LLM', data: llm, backgroundColor: '#3b82f6', stack: 'cost', yAxisID: 'y' },
        { type: 'bar', label: 'Overhead', data: ovh, backgroundColor: '#f59e0b', stack: 'cost', yAxisID: 'y' },
        { type: 'line', label: '$/specimen', data: perSpec, borderColor: '#10b981', backgroundColor: '#10b981',
          yAxisID: 'y1', borderDash: [4, 4], tension: 0.2, pointRadius: 4 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        y: { stacked: true, position: 'left', title: { display: true, text: 'USD' } },
        y1: { position: 'right', title: { display: true, text: '$ / specimen' }, grid: { drawOnChartArea: false } },
      },
      plugins: { tooltip: { callbacks: {
        label: c => c.dataset.yAxisID === 'y1'
          ? `${c.dataset.label}: ${fmtCents(c.parsed.y)}`
          : `${c.dataset.label}: ${fmtUSD(c.parsed.y)}`,
      }}},
    },
  });
}

function renderPerModelChart() {
  const r = costAnalyticsState.report;
  const sel = costAnalyticsState.selectedMonth;
  const ctx = document.getElementById('cost-per-model-chart');
  if (!ctx || !r || !sel) return;
  destroyChart('perModel');
  const m = r.per_month[sel] || {};
  const models = Object.keys(m.per_model || {}).sort((a, b) => m.per_model[b].cost - m.per_model[a].cost);
  const costs = models.map(k => m.per_model[k].cost);
  costCharts.perModel = new Chart(ctx, {
    type: 'bar',
    data: { labels: models, datasets: [{ label: 'Cost (USD)', data: costs, backgroundColor: '#6366f1' }] },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      scales: { x: { title: { display: true, text: 'USD' } } },
      plugins: { tooltip: { callbacks: {
        label: c => `${fmtUSD(c.parsed.x)} · ${fmtInt(m.per_model[c.label].tokens)} tokens`,
      }}},
    },
  });
}

function renderRateChart() {
  const r = costAnalyticsState.report;
  const sel = costAnalyticsState.selectedMonth;
  const ctx = document.getElementById('cost-rate-chart');
  if (!ctx || !r || !sel) return;
  destroyChart('rate');
  const m = r.per_month[sel] || {};
  const models = Object.keys(m.per_model || {}).filter(k => m.per_model[k].rate_per_mtok != null);
  models.sort((a, b) => m.per_model[b].rate_per_mtok - m.per_model[a].rate_per_mtok);
  const rates = models.map(k => m.per_model[k].rate_per_mtok);
  costCharts.rate = new Chart(ctx, {
    type: 'bar',
    data: { labels: models, datasets: [{ label: '$/Mtok', data: rates, backgroundColor: '#8b5cf6' }] },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      scales: { x: { title: { display: true, text: '$ per million tokens' } } },
    },
  });
}

function renderDailyChart() {
  const r = costAnalyticsState.report;
  const sel = costAnalyticsState.selectedMonth;
  const ctx = document.getElementById('cost-daily-chart');
  if (!ctx || !r) return;
  destroyChart('daily');

  // Collect dates according to timeframe.
  const tf = costAnalyticsState.dailyTimeframe;
  const monthsToUse = tf === 'month' ? [sel] : (tf === '90d' ? r.months.slice(-3) : r.months);
  const byDate = {}; // date -> {email: tokens}
  monthsToUse.forEach(mo => {
    const d = (r.per_month[mo] || {}).daily_tokens_by_date || {};
    Object.entries(d).forEach(([date, userMap]) => { byDate[date] = userMap; });
  });
  const dates = Object.keys(byDate).sort();
  if (!dates.length) {
    ctx.getContext('2d').clearRect(0, 0, ctx.width, ctx.height);
    return;
  }

  // Pick top users by total tokens across shown window.
  const userTotals = {};
  dates.forEach(d => Object.entries(byDate[d]).forEach(([e, t]) => { userTotals[e] = (userTotals[e] || 0) + t; }));
  const topUsers = Object.keys(userTotals).sort((a, b) => userTotals[b] - userTotals[a]).slice(0, 15);
  const palette = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#14b8a6',
                   '#f97316', '#6366f1', '#84cc16', '#06b6d4', '#a855f7', '#eab308', '#22c55e', '#64748b'];
  const datasets = topUsers.map((email, i) => ({
    label: email,
    data: dates.map(d => byDate[d][email] || 0),
    backgroundColor: palette[i % palette.length],
    stack: 'tokens',
  }));

  costCharts.daily = new Chart(ctx, {
    type: 'bar',
    data: { labels: dates, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x: { stacked: true },
        y: { stacked: true, title: { display: true, text: 'Estimated tokens' } },
      },
      plugins: {
        legend: { display: topUsers.length <= 8 },
        tooltip: { callbacks: { label: c => `${c.dataset.label}: ${fmtInt(c.parsed.y)} tokens` } },
      },
    },
  });
}
