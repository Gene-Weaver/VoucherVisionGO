// Clipboard helper with multiple fallbacks for cross-origin iframes
function copyToClipboard(text) {
  if (navigator.clipboard) {
    return navigator.clipboard.writeText(text).catch(function() {
      return _execCommandCopy(text);
    });
  }
  return _execCommandCopy(text);
}

function _execCommandCopy(text) {
  return new Promise(function(resolve, reject) {
    var textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.left = '0';
    textarea.style.top = '0';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    var ok = false;
    try { ok = document.execCommand('copy'); } catch(e) { /* blocked */ }
    document.body.removeChild(textarea);
    if (ok) {
      resolve();
    } else {
      var keyEl = document.getElementById('api-key-display');
      if (keyEl) {
        var range = document.createRange();
        range.selectNodeContents(keyEl);
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
      reject(new Error('Clipboard blocked by browser policy. The key text has been selected — press Ctrl+C to copy.'));
    }
  });
}

// Initialize Firebase
firebase.initializeApp(firebaseConfig);

// Helper function for formatting Firestore timestamps
function formatFirestoreDate(firestoreTimestamp) {
  if (!firestoreTimestamp) return 'N/A';
  
  // Check if it's a Firestore timestamp object
  if (firestoreTimestamp._seconds) {
    // Convert seconds to milliseconds and create a JavaScript Date
    return new Date(firestoreTimestamp._seconds * 1000).toLocaleDateString();
  } 
  // If it's already a JavaScript Date object
  else if (firestoreTimestamp instanceof Date) {
    return firestoreTimestamp.toLocaleDateString();
  }
  // If it's an ISO string
  else if (typeof firestoreTimestamp === 'string') {
    return new Date(firestoreTimestamp).toLocaleDateString();
  }
  
  return 'Invalid Date';
}

// Initialize the page
function initPage() {
  console.log("Initializing API key management page");
  // Check if user is authenticated
  firebase.auth().onAuthStateChanged(function(user) {
    if (user) {
      // User is signed in, display their email
      document.getElementById('user-email').textContent = user.email;
      console.log("User authenticated:", user.email);

      // Always wire up listeners for the controls that exist; section visibility
      // is driven independently by the consolidated capabilities check below.
      initializeCreateKeyListeners();
      initializeUserPromptListeners();

      fetchAccountCapabilities(user)
        .then(capabilities => {
          applyCapabilitiesToUI(user, capabilities);
        })
        .catch(error => {
          console.error('Error fetching account capabilities:', error);
          document.getElementById('error-message').textContent = 'Error: ' + error.message;
          document.getElementById('error-message').style.display = 'block';
        });

      // Attach logout button handler
      document.getElementById('logout-btn').addEventListener('click', () => {
        firebase.auth().signOut().then(() => {
          window.location.href = '/login';
        });
      });
    } else {
      // Not signed in, redirect to login page
      window.location.href = '/login';
    }
  });
}

// Fetch consolidated capability flags for the authenticated user.
async function fetchAccountCapabilities(user) {
  const idToken = await user.getIdToken();
  const response = await fetch('/account-capabilities', {
    headers: { 'Authorization': `Bearer ${idToken}` }
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Server returned ${response.status}: ${text}`);
  }
  return await response.json();
}

// Independently show/hide each section based on capability flags.
function applyCapabilitiesToUI(user, capabilities) {
  const hasApiKey = !!capabilities.api_key_access;
  const hasPromptUpload = !!capabilities.prompt_upload_access;

  // API keys + linked projects: gated on api_key_access (existing behavior).
  if (hasApiKey) {
    document.getElementById('no-permission').style.display = 'none';
    document.getElementById('create-key-btn').style.display = 'inline-block';
    document.getElementById('keys-container').style.display = 'block';
    document.getElementById('projects-section').style.display = 'block';
    loadApiKeys(user);
    loadVertexProjects(user);
  } else {
    document.getElementById('no-permission').style.display = 'block';
    document.getElementById('create-key-btn').style.display = 'none';
    document.getElementById('keys-container').style.display = 'none';
    document.getElementById('projects-section').style.display = 'none';
  }

  // User-generated prompts: section is visible whenever the user either has
  // the privilege OR owns existing prompts (so revoked users can still see
  // their records, though the backend will reject any management actions).
  loadUserPrompts(user, hasPromptUpload);
}

// Set up all event listeners for the key management interface
function initializeCreateKeyListeners() {
  console.log("Setting up event listeners for API key management");
  
  // Create Key button
  const createKeyBtn = document.getElementById('create-key-btn');
  if (createKeyBtn) {
    createKeyBtn.addEventListener('click', () => {
      document.getElementById('create-key-modal').style.display = 'block';
    });
  }

  const linkProjectBtn = document.getElementById('link-project-btn');
  if (linkProjectBtn) {
    linkProjectBtn.addEventListener('click', () => {
      document.getElementById('link-project-error').style.display = 'none';
      document.getElementById('link-project-success').style.display = 'none';
      document.getElementById('link-project-modal').style.display = 'block';
    });
  }
  
  // Close buttons
  document.querySelectorAll('.close').forEach(btn => {
    btn.addEventListener('click', () => {
      document.getElementById('create-key-modal').style.display = 'none';
      document.getElementById('display-key-modal').style.display = 'none';
      document.getElementById('link-project-modal').style.display = 'none';
      const uploadModal = document.getElementById('upload-prompt-modal');
      if (uploadModal) uploadModal.style.display = 'none';
    });
  });

  // Close modals when clicking outside
  window.addEventListener('click', (event) => {
    if (event.target === document.getElementById('create-key-modal')) {
      document.getElementById('create-key-modal').style.display = 'none';
    }
    if (event.target === document.getElementById('display-key-modal')) {
      document.getElementById('display-key-modal').style.display = 'none';
    }
    if (event.target === document.getElementById('link-project-modal')) {
      document.getElementById('link-project-modal').style.display = 'none';
    }
    const uploadModal = document.getElementById('upload-prompt-modal');
    if (uploadModal && event.target === uploadModal) {
      uploadModal.style.display = 'none';
    }
  });
  
  // Create key form submission
  const createKeyForm = document.getElementById('create-key-form');
  if (createKeyForm) {
    createKeyForm.addEventListener('submit', (e) => {
      e.preventDefault();
      createApiKey();
    });
  }

  const linkProjectForm = document.getElementById('link-project-form');
  if (linkProjectForm) {
    linkProjectForm.addEventListener('submit', (e) => {
      e.preventDefault();
      linkVertexProject();
    });
  }
  
  // Copy key button
  const copyKeyBtn = document.getElementById('copy-key-btn');
  if (copyKeyBtn) {
    copyKeyBtn.addEventListener('click', () => {
      const keyText = document.getElementById('api-key-display').textContent;
      copyToClipboard(keyText)
        .then(() => {
          document.getElementById('copy-success').style.display = 'block';
          setTimeout(() => {
            document.getElementById('copy-success').style.display = 'none';
          }, 3000);
        })
        .catch(err => {
          console.error('Could not copy text: ', err);
        });
    });
  }
}

// Improved checkApiKeyPermission function with better error handling
async function checkApiKeyPermission(user) {
  try {
    // Get ID token for authentication
    const idToken = await user.getIdToken();
    
    // Check permission
    const response = await fetch('/check-api-key-permission', {
      headers: {
        'Authorization': `Bearer ${idToken}`
      }
    });
    
    // Log the raw response for debugging
    console.log("API key permission check response status:", response.status);
    
    if (!response.ok) {
      const errorText = await response.text();
      console.error("API key permission check error:", errorText);
      try {
        const errorData = JSON.parse(errorText);
        throw new Error(errorData.error || `Server returned ${response.status}`);
      } catch (jsonError) {
        throw new Error(`Server returned ${response.status}: ${errorText}`);
      }
    }
    
    const data = await response.json();
    console.log("API key permission data:", data);
    
    // Be explicit about checking the value to avoid falsy values
    return data.has_api_key_permission === true;
  } catch (error) {
    console.error('Error checking API key permission:', error);
    return false;
  }
}

// Modified createApiKey function with better error handling
async function createApiKey() {
  const formError = document.getElementById('form-error');
  try {
    formError.style.display = 'none';
    
    // Get form values
    const name = document.getElementById('key-name').value;
    const description = document.getElementById('key-description').value;
    const expiryDays = document.getElementById('key-expiry').value;
    
    if (!name) {
      throw new Error('Please provide a name for your API key');
    }
    
    // Get current user
    const user = firebase.auth().currentUser;
    if (!user) {
      throw new Error('You must be logged in to create an API key');
    }
    
    // Get ID token for authentication
    const idToken = await user.getIdToken();
    
    console.log("Creating API key...");
    
    // Create the API key
    const response = await fetch('/api-keys/create', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${idToken}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        name: name,
        description: description,
        expires_days: parseInt(expiryDays, 10)
      })
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      console.error("API key creation error response:", errorText);
      try {
        const errorData = JSON.parse(errorText);
        if (response.status === 403 && errorData.code === 'no_api_key_permission') {
          throw new Error('You do not have permission to create API keys. Please contact an administrator to request this access.');
        } else {
          throw new Error(errorData.error || `Server returned ${response.status}`);
        }
      } catch (jsonError) {
        throw new Error(`Server error: ${errorText}`);
      }
    }
    
    const data = await response.json();
    console.log("API key created successfully");
    
    if (data.status === 'success') {
      // Close create modal
      document.getElementById('create-key-modal').style.display = 'none';
      
      // Update usage example with the new key
      const usageExample = document.getElementById('usage-example');
      usageExample.textContent = usageExample.textContent.replace(/YOUR_API_KEY/g, data.api_key);
      
      // Display the API key
      document.getElementById('api-key-display').textContent = data.api_key;
      document.getElementById('display-key-modal').style.display = 'block';
      
      // Reset form
      document.getElementById('create-key-form').reset();
      
      // Reload the API keys list
      loadApiKeys(user);
    } else {
      throw new Error(data.error || 'Failed to create API key');
    }
  } catch (error) {
    console.error('Error creating API key:', error);
    formError.textContent = error.message;
    formError.style.display = 'block';
  }
}

// Load API keys
async function loadApiKeys(user) {
  const keysContainer = document.getElementById('keys-container');
  const loadingElem = document.getElementById('loading');
  const errorMessageElem = document.getElementById('error-message');
  const noKeysElem = document.getElementById('no-keys');
  const keysTableElem = document.getElementById('keys-table');
  const keysListElem = document.getElementById('keys-list');
  
  try {
    // Get ID token for authentication
    const idToken = await user.getIdToken();
    
    // Fetch API keys from server
    const response = await fetch('/api-keys', {
      headers: {
        'Authorization': `Bearer ${idToken}`
      }
    });
    
    if (!response.ok) {
      throw new Error(`Server returned ${response.status}: ${response.statusText}`);
    }
    
    const data = await response.json();
    
    // Hide loading indicator
    loadingElem.style.display = 'none';
    
    if (data.status === 'success') {
      if (data.count === 0) {
        // No keys found
        noKeysElem.style.display = 'block';
        keysTableElem.style.display = 'none';
      } else {
        // Display keys
        noKeysElem.style.display = 'none';
        keysTableElem.style.display = 'table';
        
        // Clear existing list
        keysListElem.innerHTML = '';
        
        // Add each key to the table
        data.api_keys.forEach(key => {
          const row = document.createElement('tr');
          
          // Format dates using the helper function
          const createdDate = formatFirestoreDate(key.created_at);
          const expiresDate = formatFirestoreDate(key.expires_at);
          
          // Status badge
          const statusBadge = key.active 
            ? '<span class="badge-active">Active</span>'
            : '<span class="badge-inactive">Inactive</span>';
          
          row.innerHTML = `
            <td>${key.name || 'Unnamed Key'}</td>
            <td>${createdDate}</td>
            <td>${expiresDate}</td>
            <td>${statusBadge}</td>
            <td>
              ${key.active ? `<button class="btn-revoke" data-key-id="${key.key_id}">Revoke</button>` : ''}
            </td>
          `;
          
          keysListElem.appendChild(row);
        });
        
        // Add event listeners to revoke buttons
        document.querySelectorAll('.btn-revoke').forEach(btn => {
          btn.addEventListener('click', (e) => {
            const keyId = e.target.getAttribute('data-key-id');
            if (confirm('Are you sure you want to revoke this API key? This action cannot be undone.')) {
              revokeApiKey(keyId);
            }
          });
        });
      }
    } else {
      throw new Error(data.error || 'Failed to load API keys');
    }
  } catch (error) {
    console.error('Error loading API keys:', error);
    loadingElem.style.display = 'none';
    errorMessageElem.textContent = `Error: ${error.message}`;
    errorMessageElem.style.display = 'block';
  }
}

// Revoke API key
async function revokeApiKey(keyId) {
  try {
    // Get current user
    const user = firebase.auth().currentUser;
    if (!user) {
      throw new Error('You must be logged in to revoke an API key');
    }
    
    // Get ID token for authentication
    const idToken = await user.getIdToken();
    
    // Revoke the API key
    const response = await fetch(`/api-keys/${keyId}/revoke`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${idToken}`
      }
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.error || `Server returned ${response.status}`);
    }
    
    const data = await response.json();
    
    if (data.status === 'success') {
      // Reload the API keys list
      loadApiKeys(user);
    } else {
      throw new Error(data.error || 'Failed to revoke API key');
    }
  } catch (error) {
    console.error('Error revoking API key:', error);
    alert(`Error: ${error.message}`);
  }
}

async function loadVertexProjects(user) {
  const loadingElem = document.getElementById('projects-loading');
  const errorElem = document.getElementById('projects-error-message');
  const noProjectsElem = document.getElementById('no-projects');
  const tableElem = document.getElementById('projects-table');
  const listElem = document.getElementById('projects-list');

  try {
    const idToken = await user.getIdToken();
    const response = await fetch('/vertex-projects', {
      headers: {
        'Authorization': `Bearer ${idToken}`
      }
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.error || `Server returned ${response.status}`);
    }

    const data = await response.json();
    loadingElem.style.display = 'none';
    errorElem.style.display = 'none';

    if (data.status !== 'success') {
      throw new Error(data.error || 'Failed to load Vertex projects');
    }

    listElem.innerHTML = '';
    if (!data.count) {
      noProjectsElem.style.display = 'block';
      tableElem.style.display = 'none';
      return;
    }

    noProjectsElem.style.display = 'none';
    tableElem.style.display = 'table';

    data.vertex_projects.forEach(project => {
      const row = document.createElement('tr');

      const nicknameCell = document.createElement('td');
      nicknameCell.textContent = project.nickname || '-';
      row.appendChild(nicknameCell);

      const projectIdCell = document.createElement('td');
      const projectIdCode = document.createElement('code');
      projectIdCode.textContent = project.project_id || '';
      projectIdCell.appendChild(projectIdCode);
      row.appendChild(projectIdCell);

      const createdCell = document.createElement('td');
      createdCell.textContent = formatFirestoreDate(project.created_at);
      row.appendChild(createdCell);

      const statusCell = document.createElement('td');
      const statusBadge = document.createElement('span');
      statusBadge.className = project.active ? 'badge-active' : 'badge-inactive';
      statusBadge.textContent = project.active ? 'Active' : 'Revoked';
      statusCell.appendChild(statusBadge);
      row.appendChild(statusCell);

      const actionsCell = document.createElement('td');
      if (project.active) {
        const revokeBtn = document.createElement('button');
        revokeBtn.className = 'btn-revoke btn-revoke-project';
        revokeBtn.textContent = 'Revoke';
        const projectId = project.project_id;
        revokeBtn.addEventListener('click', async () => {
          if (confirm(`Revoke linked project "${projectId}"? Requests using this vertex_project will be blocked.`)) {
            await revokeVertexProject(projectId);
          }
        });
        actionsCell.appendChild(revokeBtn);
      }
      row.appendChild(actionsCell);

      listElem.appendChild(row);
    });
  } catch (error) {
    console.error('Error loading Vertex projects:', error);
    loadingElem.style.display = 'none';
    tableElem.style.display = 'none';
    errorElem.textContent = `Error: ${error.message}`;
    errorElem.style.display = 'block';
  }
}

async function linkVertexProject() {
  const errorElem = document.getElementById('link-project-error');
  const successElem = document.getElementById('link-project-success');
  const projectId = document.getElementById('vertex-project-id').value.trim();
  const nickname = document.getElementById('vertex-project-nickname').value.trim();

  try {
    errorElem.style.display = 'none';
    successElem.style.display = 'none';

    const user = firebase.auth().currentUser;
    if (!user) {
      throw new Error('You must be logged in to link a project');
    }

    const idToken = await user.getIdToken();
    const response = await fetch('/vertex-projects/link', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${idToken}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        project_id: projectId,
        nickname: nickname
      })
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || `Server returned ${response.status}`);
    }

    successElem.textContent = data.message || 'Project linked successfully.';
    successElem.style.display = 'block';
    document.getElementById('link-project-form').reset();
    await loadVertexProjects(user);
    setTimeout(() => {
      document.getElementById('link-project-modal').style.display = 'none';
      successElem.style.display = 'none';
    }, 1200);
  } catch (error) {
    console.error('Error linking Vertex project:', error);
    errorElem.textContent = error.message;
    errorElem.style.display = 'block';
  }
}

async function revokeVertexProject(projectId) {
  try {
    const user = firebase.auth().currentUser;
    if (!user) {
      throw new Error('You must be logged in to revoke a project');
    }

    const idToken = await user.getIdToken();
    const response = await fetch(`/vertex-projects/${encodeURIComponent(projectId)}/revoke`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${idToken}`
      }
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || `Server returned ${response.status}`);
    }

    await loadVertexProjects(user);
  } catch (error) {
    console.error('Error revoking Vertex project:', error);
    alert(`Error: ${error.message}`);
  }
}

// ============================================================================
// User-generated prompts
// ============================================================================

function initializeUserPromptListeners() {
  const uploadBtn = document.getElementById('upload-prompt-btn');
  if (uploadBtn) {
    uploadBtn.addEventListener('click', () => {
      const errEl = document.getElementById('upload-prompt-error');
      const okEl = document.getElementById('upload-prompt-success');
      if (errEl) { errEl.textContent = ''; errEl.style.display = 'none'; }
      if (okEl) { okEl.textContent = ''; okEl.style.display = 'none'; }
      document.getElementById('upload-prompt-modal').style.display = 'block';
    });
  }

  const uploadForm = document.getElementById('upload-prompt-form');
  if (uploadForm) {
    uploadForm.addEventListener('submit', (e) => {
      e.preventDefault();
      handlePromptUpload();
    });
  }
}

async function loadUserPrompts(user, hasPromptUpload) {
  const section = document.getElementById('user-prompts-section');
  const loadingElem = document.getElementById('user-prompts-loading');
  const errorElem = document.getElementById('user-prompts-error-message');
  const noPromptsElem = document.getElementById('no-user-prompts');
  const tableElem = document.getElementById('user-prompts-table');
  const listElem = document.getElementById('user-prompts-list');
  const noPermNotice = document.getElementById('no-upload-permission');
  const revokedNotice = document.getElementById('upload-revoked-notice');
  const uploadBtn = document.getElementById('upload-prompt-btn');

  try {
    const idToken = await user.getIdToken();
    const response = await fetch('/user-prompts', {
      headers: { 'Authorization': `Bearer ${idToken}` }
    });
    if (!response.ok) {
      const text = await response.text();
      throw new Error(`Server returned ${response.status}: ${text}`);
    }
    const data = await response.json();
    const prompts = data.prompts || [];
    const totalPromptCount = Number.isFinite(data.total_prompt_count) ? data.total_prompt_count : prompts.length;

    // Decide section visibility:
    //   - has flag => always show section (even empty), with upload button
    //   - lacks flag but owns prompts => show section read-only + revoked notice
    //   - lacks flag and no prompts => hide section, show "no permission" notice
    if (hasPromptUpload) {
      section.style.display = 'block';
      noPermNotice.style.display = 'none';
      revokedNotice.style.display = 'none';
      if (uploadBtn) uploadBtn.style.display = 'inline-block';
    } else if (totalPromptCount > 0) {
      section.style.display = 'block';
      noPermNotice.style.display = 'none';
      revokedNotice.style.display = 'block';
      if (uploadBtn) uploadBtn.style.display = 'none';
    } else {
      section.style.display = 'none';
      noPermNotice.style.display = 'block';
      revokedNotice.style.display = 'none';
      loadingElem.style.display = 'none';
      return;
    }

    loadingElem.style.display = 'none';
    errorElem.style.display = 'none';
    listElem.innerHTML = '';

    if (prompts.length === 0) {
      noPromptsElem.style.display = 'block';
      tableElem.style.display = 'none';
      return;
    }

    noPromptsElem.style.display = 'none';
    tableElem.style.display = 'table';

    prompts.forEach(prompt => renderUserPromptRow(listElem, prompt, hasPromptUpload));
  } catch (error) {
    console.error('Error loading user prompts:', error);
    loadingElem.style.display = 'none';
    errorElem.textContent = `Error: ${error.message}`;
    errorElem.style.display = 'block';
  }
}

function renderUserPromptRow(listElem, prompt, canManage) {
  const row = document.createElement('tr');
  const promptId = prompt.prompt_id;

  const filenameCell = document.createElement('td');
  const filenameCode = document.createElement('code');
  filenameCode.textContent = prompt.filename || '';
  filenameCell.appendChild(filenameCode);
  row.appendChild(filenameCell);

  const displayNameCell = document.createElement('td');
  displayNameCell.textContent = prompt.display_name || '-';
  row.appendChild(displayNameCell);

  const statusCell = document.createElement('td');
  if (canManage) {
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
      handleStatusToggle(promptId, select.value);
    });
    statusCell.appendChild(select);
  } else {
    const badge = document.createElement('span');
    badge.className = prompt.status === 'production' ? 'badge-active' : 'badge-inactive';
    badge.textContent = prompt.status || '-';
    statusCell.appendChild(badge);
  }
  row.appendChild(statusCell);

  const uploadedCell = document.createElement('td');
  uploadedCell.textContent = formatFirestoreDate(prompt.created_at);
  row.appendChild(uploadedCell);

  const actionsCell = document.createElement('td');
  if (canManage) {
    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'btn-revoke';
    deleteBtn.textContent = 'Delete';
    deleteBtn.addEventListener('click', () => {
      if (confirm(`Delete prompt "${prompt.filename}"? This cannot be undone.`)) {
        handlePromptDelete(promptId);
      }
    });
    actionsCell.appendChild(deleteBtn);
  } else {
    actionsCell.textContent = '-';
  }
  row.appendChild(actionsCell);

  listElem.appendChild(row);
}

async function handlePromptUpload() {
  const errEl = document.getElementById('upload-prompt-error');
  const okEl = document.getElementById('upload-prompt-success');
  errEl.style.display = 'none';
  okEl.style.display = 'none';
  try {
    const fileInput = document.getElementById('prompt-file');
    if (!fileInput.files || fileInput.files.length === 0) {
      throw new Error('Please select a YAML file.');
    }
    const file = fileInput.files[0];
    const status = document.querySelector('input[name="prompt-status"]:checked').value;

    const user = firebase.auth().currentUser;
    if (!user) throw new Error('You must be logged in to upload a prompt.');
    const idToken = await user.getIdToken();

    const formData = new FormData();
    formData.append('file', file);
    formData.append('status', status);

    const response = await fetch('/user-prompts/upload', {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${idToken}` },
      body: formData
    });

    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || `Server returned ${response.status}`);
    }

    okEl.textContent = 'Prompt uploaded successfully.';
    okEl.style.display = 'block';
    document.getElementById('upload-prompt-form').reset();
    setTimeout(() => {
      document.getElementById('upload-prompt-modal').style.display = 'none';
      okEl.style.display = 'none';
    }, 1200);

    await loadUserPrompts(user, true);
  } catch (error) {
    console.error('Error uploading prompt:', error);
    errEl.textContent = error.message;
    errEl.style.display = 'block';
  }
}

async function handleStatusToggle(promptId, newStatus) {
  try {
    const user = firebase.auth().currentUser;
    if (!user) throw new Error('Not authenticated.');
    const idToken = await user.getIdToken();
    const response = await fetch(`/user-prompts/${encodeURIComponent(promptId)}/status`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${idToken}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ status: newStatus })
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || `Server returned ${response.status}`);
    }
  } catch (error) {
    console.error('Error updating prompt status:', error);
    alert(`Error: ${error.message}`);
    // Refresh to revert the select to the actual server state
    const user = firebase.auth().currentUser;
    if (user) await loadUserPrompts(user, true);
  }
}

async function handlePromptDelete(promptId) {
  try {
    const user = firebase.auth().currentUser;
    if (!user) throw new Error('Not authenticated.');
    const idToken = await user.getIdToken();
    const response = await fetch(`/user-prompts/${encodeURIComponent(promptId)}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${idToken}` }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || `Server returned ${response.status}`);
    }
    await loadUserPrompts(user, true);
  } catch (error) {
    console.error('Error deleting prompt:', error);
    alert(`Error: ${error.message}`);
  }
}

// Start the page initialization when the DOM is ready
document.addEventListener('DOMContentLoaded', function() {
  console.log("DOM content loaded, initializing page");
  initPage();
});
