// Variables to store current key being viewed
let currentKeyId = null;

// Load API keys from the API
function loadApiKeys() {
  document.getElementById('api-keys-loading').style.display = 'block';
  document.getElementById('api-keys-table').style.display = 'none';

  // Get Firebase auth token
  firebase.auth().currentUser.getIdToken(true).then(function(idToken) {
    fetch('/admin/api-keys', {
      headers: {
        'Authorization': 'Bearer ' + idToken
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.status === 'success') {
        window.allApiKeys = data.api_keys;
        window.filteredApiKeys = [...allApiKeys];
        renderApiKeysPage(1);
      } else {
        console.error('Failed to load API keys:', data.error);
        document.getElementById('api-keys-loading').textContent = 'Error loading API keys: ' + data.error;
      }
    })
    .catch(error => {
      console.error('Error loading API keys:', error);
      document.getElementById('api-keys-loading').textContent = 'Error loading API keys. Please try again.';
    });
  }).catch(function(error) {
    console.error('Error getting auth token:', error);
    document.getElementById('api-keys-loading').textContent = 'Authentication error. Please try logging in again.';
  });
}

// Render a page of API keys
function renderApiKeysPage(page) {
  window.currentApiKeysPage = page;
  
  const start = (page - 1) * window.itemsPerPage;
  const end = start + window.itemsPerPage;
  const pageItems = window.filteredApiKeys.slice(start, end);
  
  const tableBody = document.getElementById('api-keys-list');
  tableBody.innerHTML = '';
  
  if (pageItems.length === 0) {
    document.getElementById('api-keys-loading').style.display = 'block';
    document.getElementById('api-keys-loading').textContent = 'No API keys found matching your search.';
    document.getElementById('api-keys-table').style.display = 'none';
    document.getElementById('api-keys-pagination').innerHTML = '';
    return;
  }
  
  document.getElementById('api-keys-loading').style.display = 'none';
  document.getElementById('api-keys-table').style.display = 'table';
  
  pageItems.forEach(key => {
    const createdDate = key.created_at && (key.created_at._seconds || key.created_at._formatted) ? 
      (key.created_at._formatted || new Date(key.created_at._seconds * 1000).toLocaleDateString()) : 'Unknown';
    
    const expiresDate = key.expires_at && (key.expires_at._seconds || key.expires_at._formatted) ? 
      (key.expires_at._formatted || new Date(key.expires_at._seconds * 1000).toLocaleDateString()) : 'Never';
    
    const isActive = key.active !== false; // Default to active if not specified
    
    const row = document.createElement('tr');
    
    // User column
    const userCell = document.createElement('td');
    userCell.textContent = key.owner || 'Unknown';
    row.appendChild(userCell);
    
    // Key name column
    const nameCell = document.createElement('td');
    nameCell.textContent = key.name || key.key_id.substring(0, 8) + '...';
    row.appendChild(nameCell);
    
    // Created column
    const createdCell = document.createElement('td');
    createdCell.textContent = createdDate;
    row.appendChild(createdCell);
    
    // Expires column
    const expiresCell = document.createElement('td');
    expiresCell.textContent = expiresDate;
    row.appendChild(expiresCell);
    
    // Status column
    const statusCell = document.createElement('td');
    const statusBadge = document.createElement('span');
    statusBadge.className = 'badge ' + (isActive ? 'badge-approved' : 'badge-rejected');
    statusBadge.textContent = isActive ? 'Active' : 'Revoked';
    statusCell.appendChild(statusBadge);
    row.appendChild(statusCell);
    
    // Actions column
    const actionsCell = document.createElement('td');
    
    if (isActive) {
      const revokeButton = document.createElement('button');
      revokeButton.className = 'btn-danger';
      revokeButton.textContent = 'Revoke';
      revokeButton.addEventListener('click', () => showRevokeKeyModal(key));
      actionsCell.appendChild(revokeButton);
    } else {
      const inactiveText = document.createElement('span');
      inactiveText.textContent = 'Revoked';
      inactiveText.className = 'text-muted';
      actionsCell.appendChild(inactiveText);
    }
    
    row.appendChild(actionsCell);
    
    tableBody.appendChild(row);
  });
  
  // Generate pagination
  window.generatePagination(
    window.filteredApiKeys.length, 
    page, 
    'api-keys-pagination', 
    renderApiKeysPage
  );
}

// Show revoke key modal
function showRevokeKeyModal(key) {
  currentKeyId = key.key_id;
  
  // Set modal content
  document.getElementById('key-user-email').textContent = key.owner || 'Unknown';
  document.getElementById('key-name').textContent = key.name || key.key_id.substring(0, 8) + '...';
  
  const createdDate = key.created_at && (key.created_at._seconds || key.created_at._formatted) ? 
    (key.created_at._formatted || new Date(key.created_at._seconds * 1000).toLocaleString()) : 'Unknown';
  
  document.getElementById('key-created').textContent = createdDate;
  
  // Clear previous messages
  document.getElementById('revoke-key-error').style.display = 'none';
  document.getElementById('revoke-key-success').style.display = 'none';
  document.getElementById('revocation-reason').value = '';
  
  // Show the modal
  document.getElementById('revoke-key-modal').style.display = 'block';
}

// Revoke an API key
function revokeApiKey() {
  if (!currentKeyId) return;
  
  const reason = document.getElementById('revocation-reason').value.trim();
  const errorDiv = document.getElementById('revoke-key-error');
  const successDiv = document.getElementById('revoke-key-success');
  
  // Clear previous messages
  errorDiv.style.display = 'none';
  successDiv.style.display = 'none';
  
  // Get Firebase auth token
  firebase.auth().currentUser.getIdToken(true).then(function(idToken) {
    fetch(`/admin/api-keys/${currentKeyId}/revoke`, {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + idToken,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        reason: reason
      })
    })
    .then(response => response.json())
    .then(data => {
      if (data.status === 'success') {
        successDiv.textContent = 'API key revoked successfully!';
        successDiv.style.display = 'block';
        
        // Reload API keys after a short delay
        setTimeout(() => {
          document.getElementById('revoke-key-modal').style.display = 'none';
          loadApiKeys();
        }, 1500);
      } else {
        errorDiv.textContent = 'Error: ' + (data.error || 'Failed to revoke API key');
        errorDiv.style.display = 'block';
      }
    })
    .catch(error => {
      console.error('Error revoking API key:', error);
      errorDiv.textContent = 'Error revoking API key. Please try again.';
      errorDiv.style.display = 'block';
    });
  }).catch(function(error) {
    console.error('Error getting auth token:', error);
    errorDiv.textContent = 'Authentication error. Please try logging in again.';
    errorDiv.style.display = 'block';
  });
}

// Set up event listeners when the document is ready
document.addEventListener('DOMContentLoaded', function() {
  // Confirm revoke key button
  const confirmRevokeKeyBtn = document.getElementById('confirm-revoke-key-btn');
  if (confirmRevokeKeyBtn) {
    confirmRevokeKeyBtn.addEventListener('click', revokeApiKey);
  }
  
  // Cancel revoke key button
  const cancelRevokeKeyBtn = document.getElementById('cancel-revoke-key-btn');
  if (cancelRevokeKeyBtn) {
    cancelRevokeKeyBtn.addEventListener('click', function() {
      document.getElementById('revoke-key-modal').style.display = 'none';
    });
  }
});

// Expose functions to global scope
window.loadApiKeys = loadApiKeys;
window.renderApiKeysPage = renderApiKeysPage;
window.showRevokeKeyModal = showRevokeKeyModal;
window.revokeApiKey = revokeApiKey;