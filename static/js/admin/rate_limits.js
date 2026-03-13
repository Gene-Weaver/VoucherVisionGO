// Rate Limits tab — manages per-user Gemini Pro usage limits
// Reuses the /admin/usage-statistics endpoint (which already returns
// gemini_pro_usage_count and gemini_pro_usage_limit fields).

const GEMINI_PRO_DEFAULT_LIMIT = 100;

let allRateLimits = [];
let filteredRateLimits = [];
let currentRateLimitsPage = 1;

async function loadRateLimits() {
  const loadingElem = document.getElementById('rate-limits-loading');
  const tableElem = document.getElementById('rate-limits-table');
  const listElem = document.getElementById('rate-limits-list');

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

    if (data.status === 'success') {
      // Map to rate-limit-centric objects
      allRateLimits = data.usage_statistics.map(stat => ({
        email: stat.user_email || 'Unknown',
        count: stat.gemini_pro_usage_count || 0,
        limit: stat.gemini_pro_usage_limit != null ? stat.gemini_pro_usage_limit : GEMINI_PRO_DEFAULT_LIMIT,
      }));

      // Sort: users closest to (or over) their limit first
      allRateLimits.sort((a, b) => {
        const pctA = a.limit > 0 ? a.count / a.limit : 0;
        const pctB = b.limit > 0 ? b.count / b.limit : 0;
        return pctB - pctA;
      });

      filteredRateLimits = [...allRateLimits];
      renderRateLimitsPage(1);
    } else {
      throw new Error(data.error || 'Failed to load rate limits');
    }
  } catch (error) {
    console.error('Error loading rate limits:', error);
    loadingElem.style.display = 'none';
    document.getElementById('rate-limits-table-container').innerHTML =
      `<p class="error">Error: ${error.message}</p>`;
  }
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
    const remaining = Math.max(0, user.limit - user.count);
    const pct = user.limit > 0 ? (user.count / user.limit) * 100 : 0;

    let statusClass, statusText;
    if (pct >= 100) {
      statusClass = 'status-rejected';
      statusText = 'Exceeded';
    } else if (pct >= 80) {
      statusClass = 'status-pending';
      statusText = 'Near limit';
    } else {
      statusClass = 'status-approved';
      statusText = 'OK';
    }

    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${user.email}</td>
      <td>${user.count}</td>
      <td>${user.limit}</td>
      <td>${remaining}</td>
      <td><span class="${statusClass}">${statusText}</span></td>
      <td>
        <button class="btn-primary btn-edit-limit" data-email="${user.email}" data-limit="${user.limit}">Edit Limit</button>
      </td>
    `;
    listElem.appendChild(row);
  });

  // Pagination
  if (typeof window.generatePagination === 'function') {
    window.generatePagination(filteredRateLimits.length, page, 'rate-limits-pagination', renderRateLimitsPage);
  }

  // Attach edit handlers
  document.querySelectorAll('.btn-edit-limit').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const email = e.target.getAttribute('data-email');
      const currentLimit = e.target.getAttribute('data-limit');
      showEditLimitPrompt(email, currentLimit);
    });
  });
}

async function showEditLimitPrompt(email, currentLimit) {
  const newLimit = prompt(`Set new Gemini Pro request limit for:\n${email}\n\nCurrent limit: ${currentLimit}`, currentLimit);

  if (newLimit === null) return; // cancelled

  const parsed = parseInt(newLimit, 10);
  if (isNaN(parsed) || parsed < 0) {
    alert('Please enter a valid non-negative integer.');
    return;
  }

  try {
    const idToken = await firebase.auth().currentUser.getIdToken();

    const response = await fetch(`/admin/rate-limits/${encodeURIComponent(email)}`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${idToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ gemini_pro_usage_limit: parsed }),
    });

    const data = await response.json();

    if (response.ok && data.status === 'success') {
      // Update local data
      const entry = allRateLimits.find(u => u.email === email);
      if (entry) entry.limit = parsed;
      const filtered = filteredRateLimits.find(u => u.email === email);
      if (filtered) filtered.limit = parsed;
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
