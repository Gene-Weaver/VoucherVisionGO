// Rate Limits tab — per-counter sub-tabs.
//
// The active sub-tab corresponds to one Firestore counter (e.g. `gemini_pro`
// or `gemini_3_5_flash`). The table shows only that counter's data. Adding a
// new entry to RATE_LIMITED_MODELS server-side automatically produces a new
// sub-tab via /admin/rate-limit-config — no JS changes required.

let counters = [];        // [{key, label, count_field, limit_field, default_limit, model_names}]
let rawStats = [];        // raw user_statistics rows from /admin/usage-statistics
let currentCounterKey = null;
let filteredViewRows = [];
let currentRateLimitsPage = 1;

async function loadRateLimits() {
  const loadingElem = document.getElementById('rate-limits-loading');
  const tableElem = document.getElementById('rate-limits-table');

  loadingElem.style.display = 'block';
  loadingElem.textContent = 'Loading rate limits...';
  tableElem.style.display = 'none';

  try {
    const idToken = await firebase.auth().currentUser.getIdToken();

    // Fetch the counter registry on first load (or whenever it's empty so a
    // server-side change is picked up by clicking the tab again).
    if (counters.length === 0) {
      const cfgResp = await fetch('/admin/rate-limit-config', {
        headers: { 'Authorization': `Bearer ${idToken}` }
      });
      if (!cfgResp.ok) {
        throw new Error(`rate-limit-config returned ${cfgResp.status}`);
      }
      const cfgData = await cfgResp.json();
      if (cfgData.status !== 'success' || !Array.isArray(cfgData.counters)) {
        throw new Error(cfgData.error || 'Invalid rate-limit-config response');
      }
      counters = cfgData.counters;
      if (counters.length === 0) {
        loadingElem.textContent = 'No rate-limited models are configured.';
        return;
      }
      currentCounterKey = counters[0].key;
      renderCounterTabs();
    }

    const statsResp = await fetch('/admin/usage-statistics', {
      headers: { 'Authorization': `Bearer ${idToken}` }
    });
    if (!statsResp.ok) {
      throw new Error(`usage-statistics returned ${statsResp.status}`);
    }
    const statsData = await statsResp.json();
    if (statsData.status !== 'success') {
      throw new Error(statsData.error || 'Failed to load usage statistics');
    }

    rawStats = statsData.usage_statistics || [];
    renderForActiveCounter();
  } catch (error) {
    console.error('Error loading rate limits:', error);
    loadingElem.style.display = 'block';
    loadingElem.textContent = 'Error loading rate limits: ' + error.message;
    tableElem.style.display = 'none';
  }
}

function renderCounterTabs() {
  const stripElem = document.getElementById('rl-counter-tabs');
  if (!stripElem) return;
  stripElem.innerHTML = '';
  counters.forEach(counter => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'nu-bin-btn' + (counter.key === currentCounterKey ? ' active' : '');
    btn.textContent = counter.label;
    btn.setAttribute('data-counter-key', counter.key);
    btn.addEventListener('click', () => {
      if (currentCounterKey === counter.key) return;
      currentCounterKey = counter.key;
      // Re-paint the strip's active state
      stripElem.querySelectorAll('.nu-bin-btn').forEach(el => {
        el.classList.toggle('active', el.getAttribute('data-counter-key') === currentCounterKey);
      });
      currentRateLimitsPage = 1;
      renderForActiveCounter();
    });
    stripElem.appendChild(btn);
  });
  stripElem.style.display = counters.length > 1 ? 'flex' : 'none';
}

function activeCounter() {
  return counters.find(c => c.key === currentCounterKey) || counters[0];
}

function renderForActiveCounter() {
  const counter = activeCounter();
  if (!counter) return;

  const descElem = document.getElementById('rl-counter-description');
  if (descElem) {
    if (counter.model_names && counter.model_names.length) {
      descElem.textContent = `${counter.label} — covers: ${counter.model_names.join(', ')}`;
    } else {
      descElem.textContent = counter.label;
    }
  }

  // Project rawStats through the active counter into per-user rows.
  const projected = rawStats.map(stat => {
    const count = stat[counter.count_field] || 0;
    const limit = stat[counter.limit_field] != null ? stat[counter.limit_field] : counter.default_limit;
    const remaining = Math.max(0, limit - count);
    const pct = limit > 0 ? (count / limit) * 100 : 0;
    return {
      email: stat.user_email || 'Unknown',
      count,
      limit,
      remaining,
      pct,
    };
  });

  // Sort: highest utilization first.
  projected.sort((a, b) => b.pct - a.pct);

  // Apply search filter
  const searchTerm = (document.getElementById('rate-limits-search')?.value || '').toLowerCase();
  filteredViewRows = searchTerm
    ? projected.filter(r => r.email.toLowerCase().includes(searchTerm))
    : projected;

  renderRateLimitsPage(currentRateLimitsPage || 1);
}

function statusBadge(pct) {
  if (pct >= 100) return { cls: 'status-rejected', text: 'Exceeded' };
  if (pct >= 80) return { cls: 'status-pending', text: 'Near limit' };
  return { cls: 'status-approved', text: 'OK' };
}

function renderRateLimitsPage(page) {
  currentRateLimitsPage = page;
  const perPage = window.itemsPerPage || 10;
  const tableElem = document.getElementById('rate-limits-table');
  const listElem = document.getElementById('rate-limits-list');
  const loadingElem = document.getElementById('rate-limits-loading');

  listElem.innerHTML = '';

  if (filteredViewRows.length === 0) {
    tableElem.style.display = 'none';
    loadingElem.textContent = 'No users found.';
    loadingElem.style.display = 'block';
    document.getElementById('rate-limits-pagination').innerHTML = '';
    return;
  }

  loadingElem.style.display = 'none';
  tableElem.style.display = 'table';

  const counter = activeCounter();
  const start = (page - 1) * perPage;
  const pageItems = filteredViewRows.slice(start, start + perPage);

  pageItems.forEach(row => {
    const status = statusBadge(row.pct);
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${row.email}</td>
      <td>${row.count}</td>
      <td>${row.limit}</td>
      <td>${row.remaining}</td>
      <td><span class="${status.cls}">${status.text}</span></td>
      <td>
        <button class="btn-primary btn-edit-limit"
                data-email="${row.email}"
                data-limit="${row.limit}">Edit Limit</button>
      </td>
    `;
    listElem.appendChild(tr);
  });

  if (typeof window.generatePagination === 'function') {
    window.generatePagination(filteredViewRows.length, page, 'rate-limits-pagination', renderRateLimitsPage);
  }

  document.querySelectorAll('.btn-edit-limit').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const t = e.target;
      const email = t.getAttribute('data-email');
      const currentLimit = t.getAttribute('data-limit');
      showEditLimitPrompt(email, currentLimit, counter);
    });
  });
}

async function showEditLimitPrompt(email, currentLimit, counter) {
  const newLimit = prompt(
    `Set new ${counter.label} request limit for:\n${email}\n\nCurrent limit: ${currentLimit}`,
    currentLimit
  );

  if (newLimit === null) return; // cancelled

  const parsed = parseInt(newLimit, 10);
  if (isNaN(parsed) || parsed < 0) {
    alert('Please enter a valid non-negative integer.');
    return;
  }

  try {
    const idToken = await firebase.auth().currentUser.getIdToken();

    const body = {};
    body[counter.limit_field] = parsed;

    const response = await fetch(`/admin/rate-limits/${encodeURIComponent(email)}`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${idToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    const data = await response.json();

    if (response.ok && data.status === 'success') {
      // Patch the cached raw stats so the active counter immediately reflects
      // the new limit; other counters' fields stay untouched.
      const entry = rawStats.find(s => s.user_email === email);
      if (entry) {
        entry[counter.limit_field] = parsed;
      }
      renderForActiveCounter();
    } else {
      alert('Error: ' + (data.error || data.message || 'Unknown error'));
    }
  } catch (error) {
    console.error('Error updating rate limit:', error);
    alert('Failed to update rate limit: ' + error.message);
  }
}

// Search filtering — operates within the active sub-tab's view.
document.addEventListener('DOMContentLoaded', () => {
  const searchInput = document.getElementById('rate-limits-search');
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      currentRateLimitsPage = 1;
      renderForActiveCounter();
    });
  }
});
