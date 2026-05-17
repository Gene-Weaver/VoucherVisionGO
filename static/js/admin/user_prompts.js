// Admin: User-Generated Prompts tab
// - Top section: dropdown of approved users + grant/revoke prompt_upload_access
// - Bottom section: table of every uploaded prompt with status toggle + delete

(function () {
  let allAdminPrompts = [];
  let filteredAdminPrompts = [];
  let approvedUsers = []; // [{ email, status, api_key_access, prompt_upload_access, is_admin }]

  function getAuthToken() {
    return firebase.auth().currentUser.getIdToken(true);
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatDate(ts) {
    if (!ts) return 'N/A';
    if (typeof ts === 'string') return new Date(ts).toLocaleString();
    if (ts._seconds) return new Date(ts._seconds * 1000).toLocaleString();
    return 'N/A';
  }

  // ---------------------------------------------------------------------------
  // Top section: user dropdown + grant/revoke
  // ---------------------------------------------------------------------------

  async function loadApprovedUsersForDropdown() {
    const select = document.getElementById('up-user-select');
    if (!select) return;
    select.innerHTML = '<option value="">Loading approved users...</option>';
    select.disabled = true;

    try {
      const idToken = await getAuthToken();
      // Pull approved users from /admin/applications (already used elsewhere).
      // Admins are always allowed, but we include them in the dropdown so admins
      // can see/confirm their own flag too.
      const [appsResp, adminsResp] = await Promise.all([
        fetch('/admin/applications', { headers: { Authorization: 'Bearer ' + idToken } }),
        fetch('/admin/list-admins', { headers: { Authorization: 'Bearer ' + idToken } }),
      ]);
      const appsData = await appsResp.json();
      const adminsData = await adminsResp.json();

      const adminEmails = new Set(
        (adminsData.admins || []).map(a => (a.email || '').toLowerCase())
      );

      const usersByEmail = new Map();
      (appsData.applications || [])
        .filter(a => a.status === 'approved')
        .forEach(a => {
          const email = (a.email || '').toLowerCase();
          if (!email) return;
          usersByEmail.set(email, {
            email,
            prompt_upload_access: !!a.prompt_upload_access,
            api_key_access: !!a.api_key_access,
            is_admin: adminEmails.has(email),
          });
        });
      // Make sure all admins show up even if they have no user_application doc
      adminEmails.forEach(email => {
        if (!usersByEmail.has(email)) {
          usersByEmail.set(email, {
            email,
            prompt_upload_access: true, // admins are implicitly allowed
            api_key_access: true,
            is_admin: true,
          });
        }
      });

      approvedUsers = Array.from(usersByEmail.values()).sort((a, b) =>
        a.email.localeCompare(b.email)
      );

      select.innerHTML = '<option value="">— Select a user —</option>';
      approvedUsers.forEach(u => {
        const opt = document.createElement('option');
        opt.value = u.email;
        const badges = [];
        if (u.is_admin) badges.push('admin');
        badges.push(u.prompt_upload_access ? 'prompt:on' : 'prompt:off');
        opt.textContent = `${u.email}  [${badges.join(', ')}]`;
        select.appendChild(opt);
      });
      select.disabled = false;
      updateAccessControlsForSelection();
    } catch (err) {
      console.error('Failed to load approved users:', err);
      select.innerHTML = '<option value="">Error loading users</option>';
      setStatusMessage('Failed to load users: ' + err.message, true);
    }
  }

  function updateAccessControlsForSelection() {
    const select = document.getElementById('up-user-select');
    const grantBtn = document.getElementById('up-grant-btn');
    const revokeBtn = document.getElementById('up-revoke-btn');
    const stateBadge = document.getElementById('up-current-state');

    if (!select || !grantBtn || !revokeBtn || !stateBadge) return;

    const email = (select.value || '').toLowerCase();
    const user = approvedUsers.find(u => u.email === email);

    if (!user) {
      stateBadge.textContent = '—';
      stateBadge.className = 'badge badge-no-api-access';
      grantBtn.disabled = true;
      revokeBtn.disabled = true;
      return;
    }

    if (user.is_admin) {
      stateBadge.textContent = 'Admin (always granted)';
      stateBadge.className = 'badge badge-api-access';
      grantBtn.disabled = true;
      revokeBtn.disabled = true;
      setStatusMessage(
        'Admins always have prompt-upload access. Remove them from the admins list to change this.',
        false,
        '#666'
      );
      return;
    }

    if (user.prompt_upload_access) {
      stateBadge.textContent = 'Granted';
      stateBadge.className = 'badge badge-api-access';
      grantBtn.disabled = true;
      revokeBtn.disabled = false;
    } else {
      stateBadge.textContent = 'Not granted';
      stateBadge.className = 'badge badge-no-api-access';
      grantBtn.disabled = false;
      revokeBtn.disabled = true;
    }
    setStatusMessage('');
  }

  function setStatusMessage(msg, isError = false, color = null) {
    const el = document.getElementById('up-access-status');
    if (!el) return;
    el.textContent = msg || '';
    el.style.color = color || (isError ? '#c62828' : '#2e7d32');
  }

  async function setPromptUploadAccess(email, allow) {
    try {
      const idToken = await getAuthToken();
      const resp = await fetch(
        `/admin/applications/${encodeURIComponent(email)}/update-prompt-upload-access`,
        {
          method: 'POST',
          headers: {
            Authorization: 'Bearer ' + idToken,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ allow_prompt_upload: !!allow }),
        }
      );
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || data.status !== 'success') {
        throw new Error(data.error || `Server returned ${resp.status}`);
      }
      // Update local cache so the badge reflects new state immediately
      const u = approvedUsers.find(x => x.email === email);
      if (u) u.prompt_upload_access = !!allow;
      // Re-render the dropdown so the inline badge updates
      const select = document.getElementById('up-user-select');
      const keepSelected = select.value;
      select.innerHTML = '<option value="">— Select a user —</option>';
      approvedUsers.forEach(uu => {
        const opt = document.createElement('option');
        opt.value = uu.email;
        const badges = [];
        if (uu.is_admin) badges.push('admin');
        badges.push(uu.prompt_upload_access ? 'prompt:on' : 'prompt:off');
        opt.textContent = `${uu.email}  [${badges.join(', ')}]`;
        if (uu.email === keepSelected) opt.selected = true;
        select.appendChild(opt);
      });
      updateAccessControlsForSelection();
      setStatusMessage(
        `Prompt upload access ${allow ? 'granted to' : 'revoked from'} ${email}.`,
        false
      );
    } catch (err) {
      console.error('setPromptUploadAccess failed:', err);
      setStatusMessage(err.message, true);
    }
  }

  // ---------------------------------------------------------------------------
  // Bottom section: all-prompts table
  // ---------------------------------------------------------------------------

  async function loadAllUserPrompts() {
    const loadingEl = document.getElementById('user-prompts-admin-loading');
    const tableEl = document.getElementById('user-prompts-admin-table');
    if (!loadingEl || !tableEl) return;

    loadingEl.style.display = 'block';
    loadingEl.textContent = 'Loading prompts...';
    tableEl.style.display = 'none';

    const includeInactive = document.getElementById('up-include-inactive')?.checked;
    const qs = includeInactive ? '?include_inactive=true' : '';

    try {
      const idToken = await getAuthToken();
      const resp = await fetch('/admin/user-prompts' + qs, {
        headers: { Authorization: 'Bearer ' + idToken },
      });
      const data = await resp.json();
      if (!resp.ok || data.status !== 'success') {
        throw new Error(data.error || `Server returned ${resp.status}`);
      }
      allAdminPrompts = data.prompts || [];
      applyPromptSearchFilter();
    } catch (err) {
      console.error('Failed to load all user prompts:', err);
      loadingEl.style.display = 'block';
      loadingEl.textContent = 'Error loading prompts: ' + err.message;
    }
  }

  function applyPromptSearchFilter() {
    const term = (document.getElementById('up-prompt-search')?.value || '')
      .trim()
      .toLowerCase();
    if (!term) {
      filteredAdminPrompts = allAdminPrompts.slice();
    } else {
      filteredAdminPrompts = allAdminPrompts.filter(p => {
        return (
          (p.owner_email || '').toLowerCase().includes(term) ||
          (p.filename || '').toLowerCase().includes(term) ||
          (p.display_name || '').toLowerCase().includes(term)
        );
      });
    }
    renderPromptsTable();
  }

  function renderPromptsTable() {
    const loadingEl = document.getElementById('user-prompts-admin-loading');
    const tableEl = document.getElementById('user-prompts-admin-table');
    const tbody = document.getElementById('user-prompts-admin-list');
    if (!tbody) return;

    tbody.innerHTML = '';

    if (filteredAdminPrompts.length === 0) {
      loadingEl.style.display = 'block';
      loadingEl.textContent = 'No prompts found.';
      tableEl.style.display = 'none';
      return;
    }

    loadingEl.style.display = 'none';
    tableEl.style.display = 'table';

    filteredAdminPrompts.forEach(prompt => {
      const row = document.createElement('tr');

      const ownerCell = document.createElement('td');
      ownerCell.textContent = prompt.owner_email || '-';
      row.appendChild(ownerCell);

      const filenameCell = document.createElement('td');
      const code = document.createElement('code');
      code.textContent = prompt.filename || '';
      filenameCell.appendChild(code);
      row.appendChild(filenameCell);

      const displayCell = document.createElement('td');
      displayCell.textContent = prompt.display_name || '-';
      row.appendChild(displayCell);

      const versionCell = document.createElement('td');
      versionCell.textContent = prompt.version || '-';
      row.appendChild(versionCell);

      const statusCell = document.createElement('td');
      if (prompt.active) {
        const select = document.createElement('select');
        select.className = 'form-control form-control-sm';
        ['test', 'production'].forEach(value => {
          const opt = document.createElement('option');
          opt.value = value;
          opt.textContent = value;
          if (value === prompt.status) opt.selected = true;
          select.appendChild(opt);
        });
        select.addEventListener('change', () => {
          adminTogglePromptStatus(prompt.prompt_id, select.value, prompt);
        });
        statusCell.appendChild(select);
      } else {
        const badge = document.createElement('span');
        badge.className = 'badge badge-no-api-access';
        badge.textContent = prompt.status || '-';
        statusCell.appendChild(badge);
      }
      row.appendChild(statusCell);

      const uploadedCell = document.createElement('td');
      uploadedCell.textContent = formatDate(prompt.created_at);
      row.appendChild(uploadedCell);

      const activeCell = document.createElement('td');
      const activeBadge = document.createElement('span');
      activeBadge.className = prompt.active
        ? 'badge badge-api-access'
        : 'badge badge-no-api-access';
      activeBadge.textContent = prompt.active ? 'active' : 'deleted';
      activeCell.appendChild(activeBadge);
      row.appendChild(activeCell);

      const actionsCell = document.createElement('td');
      if (prompt.active) {
        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'btn-danger';
        deleteBtn.textContent = 'Delete';
        deleteBtn.addEventListener('click', () => {
          const label = `${prompt.filename} (owner: ${prompt.owner_email})`;
          if (confirm(`Delete prompt "${label}"? This cannot be undone.`)) {
            adminDeletePrompt(prompt.prompt_id);
          }
        });
        actionsCell.appendChild(deleteBtn);
      } else {
        actionsCell.textContent = '—';
      }
      row.appendChild(actionsCell);

      tbody.appendChild(row);
    });
  }

  async function adminTogglePromptStatus(promptId, newStatus, originalPrompt) {
    try {
      const idToken = await getAuthToken();
      const resp = await fetch(
        `/user-prompts/${encodeURIComponent(promptId)}/status`,
        {
          method: 'POST',
          headers: {
            Authorization: 'Bearer ' + idToken,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ status: newStatus }),
        }
      );
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || data.status !== 'success') {
        throw new Error(data.error || `Server returned ${resp.status}`);
      }
      // Update local cache
      const idx = allAdminPrompts.findIndex(p => p.prompt_id === promptId);
      if (idx >= 0) allAdminPrompts[idx].status = newStatus;
    } catch (err) {
      console.error('Status toggle failed:', err);
      alert('Failed to update prompt status: ' + err.message);
      // Revert by reloading
      loadAllUserPrompts();
    }
  }

  async function adminDeletePrompt(promptId) {
    try {
      const idToken = await getAuthToken();
      const resp = await fetch(`/user-prompts/${encodeURIComponent(promptId)}`, {
        method: 'DELETE',
        headers: { Authorization: 'Bearer ' + idToken },
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok || data.status !== 'success') {
        throw new Error(data.error || `Server returned ${resp.status}`);
      }
      // Refresh table to show updated state
      loadAllUserPrompts();
    } catch (err) {
      console.error('Delete failed:', err);
      alert('Failed to delete prompt: ' + err.message);
    }
  }

  // ---------------------------------------------------------------------------
  // Entry point: invoked by dashboard.js when the tab is activated
  // ---------------------------------------------------------------------------

  function loadAdminUserPrompts() {
    loadApprovedUsersForDropdown();
    loadAllUserPrompts();
  }

  document.addEventListener('DOMContentLoaded', () => {
    const select = document.getElementById('up-user-select');
    if (select) {
      select.addEventListener('change', updateAccessControlsForSelection);
    }
    const grantBtn = document.getElementById('up-grant-btn');
    if (grantBtn) {
      grantBtn.addEventListener('click', () => {
        const email = document.getElementById('up-user-select').value;
        if (email) setPromptUploadAccess(email, true);
      });
    }
    const revokeBtn = document.getElementById('up-revoke-btn');
    if (revokeBtn) {
      revokeBtn.addEventListener('click', () => {
        const email = document.getElementById('up-user-select').value;
        if (email) setPromptUploadAccess(email, false);
      });
    }
    const refreshBtn = document.getElementById('up-refresh-btn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', loadAllUserPrompts);
    }
    const includeChk = document.getElementById('up-include-inactive');
    if (includeChk) {
      includeChk.addEventListener('change', loadAllUserPrompts);
    }
    const search = document.getElementById('up-prompt-search');
    if (search) {
      search.addEventListener('input', applyPromptSearchFilter);
    }
  });

  // Expose so dashboard.js can call it from loadDataForTab
  window.loadAdminUserPrompts = loadAdminUserPrompts;
})();
