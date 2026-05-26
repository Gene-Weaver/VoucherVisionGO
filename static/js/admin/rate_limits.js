// Rate Limits tab — manages per-user, per-model usage limits.
// Reuses the /admin/usage-statistics endpoint (raw Firestore docs include
// every {prefix}_usage_count / {prefix}_usage_limit field).

const GEMINI_PRO_DEFAULT_LIMIT = 100;
const GEMINI_3_5_FLASH_DEFAULT_LIMIT = 100;

// Per-model display config. Keep field names in sync with app.py's
// RATE_LIMITED_MODELS / RATE_LIMIT_FIELD_PREFIX.
const RATE_LIMIT_MODELS = [
  {
    key: 'pro',
    label: 'Gemini Pro',
    countField: 'gemini_pro_usage_count',
    limitField: 'gemini_pro_usage_limit',
    defaultLimit: GEMINI_PRO_DEFAULT_LIMIT,
  },
  {
    key: 'flash35',
    label: 'Gemini 3.5 Flash',
    countField: 'gemini_3_5_flash_usage_count',
    limitField: 'gemini_3_5_flash_usage_limit',
    defaultLimit: GEMINI_3_5_FLASH_DEFAULT_LIMIT,
  },
];

let allRateLimits = [];
let filteredRateLimits = [];
let currentRateLimitsPage = 1;

async function loadRateLimits() {
  const loadingElem = document.getElementById('rate-limits-loading');
  const tableElem = document.getElementById('rate-limits-table');

  loadingElem.style.display = 'block';
  tableElem.style.display = 'none';

  try {
    const idToken = await firebase.auth().currentUser.getIdToken();

    const response = await fetch('/admin/usage-statistics', {
      headers: { 'Authorization': `Bearer ${idToken}` }
    });

    if (!response.ok) {
      throw new Error(`Server returned ${response.status}: ${response.statusText}`);
    }

    const data = await response.json();
    loadingElem.style.display = 'none';

    if (data.status !== 'success') {
      throw new Error(data.error || 'Failed to load rate limits');
    }

    // Map each user's stats into a row with per-model {count, limit}.
    allRateLimits = data.usage_statistics.map(stat => {
      const row = { email: stat.user_email || 'Unknown', models: {} };
      RATE_LIMIT_MODELS.forEach(m => {
        row.models[m.key] = {
          count: stat[m.countField] || 0,
          limit: stat[m.limitField] != null ? stat[m.limitField] : m.defaultLimit,
        };
      });
      return row;
    });

    // Sort: highest utilization across *any* model first.
    allRateLimits.sort((a, b) => {
      const pctA = Math.max(...RATE_LIMIT_MODELS.map(m => {
        const s = a.models[m.key];
        return s.limit > 0 ? s.count / s.limit : 0;
      }));
      const pctB = Math.max(...RATE_LIMIT_MODELS.map(m => {
        const s = b.models[m.key];
        return s.limit > 0 ? s.count / s.limit : 0;
      }));
      return pctB - pctA;
    });

    filteredRateLimits = [...allRateLimits];
    renderRateLimitsPage(1);
  } catch (error) {
    console.error('Error loading rate limits:', error);
    loadingElem.style.display = 'none';
    document.getElementById('rate-limits-table-container').innerHTML =
      `<p class="error">Error: ${error.message}</p>`;
  }
}

function statusBadge(maxPct) {
  if (maxPct >= 100) return { cls: 'status-rejected', text: 'Exceeded' };
  if (maxPct >= 80) return { cls: 'status-pending', text: 'Near limit' };
  return { cls: 'status-approved', text: 'OK' };
}

function renderRateLimitsPage(page) {
  currentRateLimitsPage = page;
  const perPage = window.itemsPerPage || 10;
  const tableElem = document.getElementById('rate-limits-table');
  const listElem = document.getElementById('rate-limits-list');

  listElem.innerHTML = '';

  if (filteredRateLimits.length === 0) {
    tableElem.style.display = 'none';
    document.getElementById('rate-limits-loading').textContent = 'No users found.';
    document.getElementById('rate-limits-loading').style.display = 'block';
    document.getElementById('rate-limits-pagination').innerHTML = '';
    return;
  }

  document.getElementById('rate-limits-loading').style.display = 'none';
  tableElem.style.display = 'table';

  const start = (page - 1) * perPage;
  const pageItems = filteredRateLimits.slice(start, start + perPage);

  pageItems.forEach(user => {
    // Per-model state
    const cells = {};
    let maxPct = 0;
    RATE_LIMIT_MODELS.forEach(m => {
      const s = user.models[m.key];
      const remaining = Math.max(0, s.limit - s.count);
      const pct = s.limit > 0 ? (s.count / s.limit) * 100 : 0;
      if (pct > maxPct) maxPct = pct;
      cells[m.key] = { ...s, remaining, pct };
    });

    const status = statusBadge(maxPct);

    // Build per-model summary cell content + edit button
    const buildModelCell = (m) => {
      const c = cells[m.key];
      return `${c.count} / ${c.limit} / ${c.remaining}`;
    };

    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${user.email}</td>
      <td>${buildModelCell(RATE_LIMIT_MODELS[0])}</td>
      <td>${buildModelCell(RATE_LIMIT_MODELS[1])}</td>
      <td><span class="${status.cls}">${status.text}</span></td>
      <td>
        <button class="btn-primary btn-edit-limit"
                data-email="${user.email}"
                data-model-key="${RATE_LIMIT_MODELS[0].key}"
                data-model-label="${RATE_LIMIT_MODELS[0].label}"
                data-field="${RATE_LIMIT_MODELS[0].limitField}"
                data-limit="${cells.pro.limit}">Edit Pro</button>
        <button class="btn-primary btn-edit-limit"
                data-email="${user.email}"
                data-model-key="${RATE_LIMIT_MODELS[1].key}"
                data-model-label="${RATE_LIMIT_MODELS[1].label}"
                data-field="${RATE_LIMIT_MODELS[1].limitField}"
                data-limit="${cells.flash35.limit}">Edit 3.5-Flash</button>
      </td>
    `;
    listElem.appendChild(row);
  });

  if (typeof window.generatePagination === 'function') {
    window.generatePagination(filteredRateLimits.length, page, 'rate-limits-pagination', renderRateLimitsPage);
  }

  document.querySelectorAll('.btn-edit-limit').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const t = e.target;
      const email = t.getAttribute('data-email');
      const modelKey = t.getAttribute('data-model-key');
      const modelLabel = t.getAttribute('data-model-label');
      const field = t.getAttribute('data-field');
      const currentLimit = t.getAttribute('data-limit');
      showEditLimitPrompt(email, modelKey, modelLabel, field, currentLimit);
    });
  });
}

async function showEditLimitPrompt(email, modelKey, modelLabel, field, currentLimit) {
  const newLimit = prompt(
    `Set new ${modelLabel} request limit for:\n${email}\n\nCurrent limit: ${currentLimit}`,
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
    body[field] = parsed;

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
      const updateLocal = (collection) => {
        const entry = collection.find(u => u.email === email);
        if (entry && entry.models[modelKey]) entry.models[modelKey].limit = parsed;
      };
      updateLocal(allRateLimits);
      updateLocal(filteredRateLimits);
      renderRateLimitsPage(currentRateLimitsPage);
    } else {
      alert('Error: ' + (data.error || data.message || 'Unknown error'));
    }
  } catch (error) {
    console.error('Error updating rate limit:', error);
    alert('Failed to update rate limit: ' + error.message);
  }
}

// Search filtering
document.addEventListener('DOMContentLoaded', () => {
  const searchInput = document.getElementById('rate-limits-search');
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      const term = searchInput.value.toLowerCase();
      filteredRateLimits = allRateLimits.filter(u =>
        u.email.toLowerCase().includes(term)
      );
      renderRateLimitsPage(1);
    });
  }
});
