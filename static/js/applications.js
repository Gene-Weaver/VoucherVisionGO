// Variables to store current application being viewed
let currentApplicationEmail = null;

// Load applications from the API
function loadApplications() {
  document.getElementById('applications-loading').style.display = 'block';
  document.getElementById('applications-table').style.display = 'none';

  // Get Firebase auth token
  firebase.auth().currentUser.getIdToken(true).then(function(idToken) {
    fetch('/admin/applications', {
      headers: {
        'Authorization': 'Bearer ' + idToken
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.status === 'success') {
        window.allApplications = data.applications;
        window.filteredApplications = [...allApplications];
        applyFiltersToApplications();
      } else {
        console.error('Failed to load applications:', data.error);
        document.getElementById('applications-loading').textContent = 'Error loading applications: ' + data.error;
      }
    })
    .catch(error => {
      console.error('Error loading applications:', error);
      document.getElementById('applications-loading').textContent = 'Error loading applications. Please try again.';
    });
  }).catch(function(error) {
    console.error('Error getting auth token:', error);
    document.getElementById('applications-loading').textContent = 'Authentication error. Please try logging in again.';
  });
}

// Render a page of applications
function renderApplicationsPage(page) {
  window.currentApplicationsPage = page;
  
  const start = (page - 1) * window.itemsPerPage;
  const end = start + window.itemsPerPage;
  const pageItems = window.filteredApplications.slice(start, end);
  
  const tableBody = document.getElementById('applications-list');
  tableBody.innerHTML = '';
  
  if (pageItems.length === 0) {
    document.getElementById('applications-loading').style.display = 'block';
    document.getElementById('applications-loading').textContent = 'No applications found matching your filters.';
    document.getElementById('applications-table').style.display = 'none';
    document.getElementById('applications-pagination').innerHTML = '';
    return;
  }
  
  document.getElementById('applications-loading').style.display = 'none';
  document.getElementById('applications-table').style.display = 'table';
  
  pageItems.forEach(app => {
    const createdDate = app.created_at && app.created_at._seconds ? 
      new Date(app.created_at._seconds * 1000).toLocaleDateString() : 'Unknown';
    
    const row = document.createElement('tr');
    
    // Email column
    const emailCell = document.createElement('td');
    emailCell.textContent = app.email;
    row.appendChild(emailCell);
    
    // Organization column
    const orgCell = document.createElement('td');
    orgCell.textContent = app.organization || 'Not specified';
    row.appendChild(orgCell);
    
    // Purpose column
    const purposeCell = document.createElement('td');
    purposeCell.textContent = app.purpose ? 
      (app.purpose.length > 50 ? app.purpose.substring(0, 50) + '...' : app.purpose) : 
      'Not specified';
    row.appendChild(purposeCell);
    
    // Status column
    const statusCell = document.createElement('td');
    const statusBadge = document.createElement('span');
    statusBadge.textContent = app.status || 'pending';
    statusBadge.className = 'badge badge-' + (app.status || 'pending');
    statusCell.appendChild(statusBadge);
    row.appendChild(statusCell);
    
    // Created column
    const createdCell = document.createElement('td');
    createdCell.textContent = createdDate;
    row.appendChild(createdCell);
    
    // Actions column
    const actionsCell = document.createElement('td');
    const viewButton = document.createElement('button');
    viewButton.className = 'btn-secondary';
    viewButton.textContent = 'View';
    viewButton.addEventListener('click', () => showApplicationDetails(app));
    actionsCell.appendChild(viewButton);
    row.appendChild(actionsCell);
    
    tableBody.appendChild(row);
  });
  
  // Generate pagination
  window.generatePagination(
    window.filteredApplications.length, 
    page, 
    'applications-pagination', 
    renderApplicationsPage
  );
}

// Show application details in the modal
function showApplicationDetails(application) {
  currentApplicationEmail = application.email;
  
  const detailsDiv = document.getElementById('application-details');
  
  // Format creation date
  const createdDate = application.created_at && application.created_at._seconds ? 
    new Date(application.created_at._seconds * 1000).toLocaleString() : 'Unknown';
  
  // Format status date (approved_at or rejected_at)
  let statusDate = 'N/A';
  if (application.status === 'approved' && application.approved_at && application.approved_at._seconds) {
    statusDate = new Date(application.approved_at._seconds * 1000).toLocaleString();
  } else if (application.status === 'rejected' && application.rejected_at && application.rejected_at._seconds) {
    statusDate = new Date(application.rejected_at._seconds * 1000).toLocaleString();
  }
  
  // Build HTML for details
  let html = `
    <p><strong>Email:</strong> ${application.email}</p>
    <p><strong>Organization:</strong> ${application.organization || 'Not specified'}</p>
    <p><strong>Purpose:</strong> ${application.purpose || 'Not specified'}</p>
    <p><strong>Status:</strong> <span class="badge badge-${application.status || 'pending'}">${application.status || 'pending'}</span></p>
    <p><strong>Submitted:</strong> ${createdDate}</p>
  `;
  
  if (application.status === 'approved') {
    html += `
      <p><strong>Approved By:</strong> ${application.approved_by || 'Unknown'}</p>
      <p><strong>Approved On:</strong> ${statusDate}</p>
      <p><strong>API Key Access:</strong> ${application.api_key_access ? 'Allowed' : 'Not allowed'}</p>
    `;
  } else if (application.status === 'rejected') {
    html += `
      <p><strong>Rejected By:</strong> ${application.rejected_by || 'Unknown'}</p>
      <p><strong>Rejected On:</strong> ${statusDate}</p>
      <p><strong>Rejection Reason:</strong> ${application.rejection_reason || 'No reason provided'}</p>
    `;
  }
  
  if (application.notes && application.notes.length > 0) {
    html += '<p><strong>Notes:</strong></p><ul>';
    application.notes.forEach(note => {
      html += `<li>${note}</li>`;
    });
    html += '</ul>';
  }
  
  detailsDiv.innerHTML = html;
  
  // Show/hide relevant action buttons based on status
  const approveBtn = document.getElementById('approve-btn');
  const rejectBtn = document.getElementById('reject-btn');
  const apiKeyAccessActions = document.getElementById('api-key-access-actions');
  const updateApiKeysCheckbox = document.getElementById('update-api-keys');
  const rejectionForm = document.getElementById('rejection-form');
  const statusMessage = document.getElementById('application-status-message');
  
  // Reset UI elements
  statusMessage.innerHTML = '';
  rejectionForm.style.display = 'none';
  apiKeyAccessActions.style.display = 'none';
  document.getElementById('api-key-permission-group').style.display = 'none';
  
  if (application.status === 'pending') {
    approveBtn.style.display = 'inline-block';
    rejectBtn.style.display = 'inline-block';
    document.getElementById('api-key-permission-group').style.display = 'block';
    document.getElementById('allow-api-keys').checked = false;
  } else if (application.status === 'approved') {
    approveBtn.style.display = 'none';
    rejectBtn.style.display = 'none';
    apiKeyAccessActions.style.display = 'block';
    updateApiKeysCheckbox.checked = application.api_key_access || false;
  } else {
    approveBtn.style.display = 'none';
    rejectBtn.style.display = 'none';
  }
  
  // Show the modal
  document.getElementById('application-modal').style.display = 'block';
}

// Approve an application
function approveApplication() {
  if (!currentApplicationEmail) return;
  
  const allowApiKeys = document.getElementById('allow-api-keys').checked;
  const statusMessage = document.getElementById('application-status-message');
  
  statusMessage.innerHTML = '<div class="loading">Processing...</div>';
  
  // Get Firebase auth token
  firebase.auth().currentUser.getIdToken(true).then(function(idToken) {
    fetch(`/admin/applications/${currentApplicationEmail}/approve`, {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + idToken,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        allow_api_keys: allowApiKeys
      })
    })
    .then(response => response.json())
    .then(data => {
      if (data.status === 'success') {
        statusMessage.innerHTML = '<div class="alert alert-success">Application approved successfully!</div>';
        
        // Reload applications after a short delay
        setTimeout(() => {
          document.getElementById('application-modal').style.display = 'none';
          loadApplications();
        }, 1500);
      } else {
        statusMessage.innerHTML = `<div class="alert alert-danger">Error: ${data.error}</div>`;
      }
    })
    .catch(error => {
      console.error('Error approving application:', error);
      statusMessage.innerHTML = '<div class="alert alert-danger">Error approving application. Please try again.</div>';
    });
  }).catch(function(error) {
    console.error('Error getting auth token:', error);
    statusMessage.innerHTML = '<div class="alert alert-danger">Authentication error. Please try logging in again.</div>';
  });
}

// Reject an application
function rejectApplication() {
  if (!currentApplicationEmail) return;
  
  const reason = document.getElementById('rejection-reason').value.trim();
  
  if (!reason) {
    alert('Please provide a reason for rejection');
    return;
  }
  
  const statusMessage = document.getElementById('application-status-message');
  statusMessage.innerHTML = '<div class="loading">Processing...</div>';
  
  // Get Firebase auth token
  firebase.auth().currentUser.getIdToken(true).then(function(idToken) {
    fetch(`/admin/applications/${currentApplicationEmail}/reject`, {
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
        document.getElementById('rejection-form').style.display = 'none';
        statusMessage.innerHTML = '<div class="alert alert-success">Application rejected successfully!</div>';
        
        // Reload applications after a short delay
        setTimeout(() => {
          document.getElementById('application-modal').style.display = 'none';
          loadApplications();
        }, 1500);
      } else {
        statusMessage.innerHTML = `<div class="alert alert-danger">Error: ${data.error}</div>`;
      }
    })
    .catch(error => {
      console.error('Error rejecting application:', error);
      statusMessage.innerHTML = '<div class="alert alert-danger">Error rejecting application. Please try again.</div>';
    });
  }).catch(function(error) {
    console.error('Error getting auth token:', error);
    statusMessage.innerHTML = '<div class="alert alert-danger">Authentication error. Please try logging in again.</div>';
  });
}

// Update API key access for an approved application
function updateApiKeyAccess() {
  if (!currentApplicationEmail) return;
  
  const allowApiKeys = document.getElementById('update-api-keys').checked;
  const statusMessage = document.getElementById('application-status-message');
  
  statusMessage.innerHTML = '<div class="loading">Processing...</div>';
  
  // Get Firebase auth token
  firebase.auth().currentUser.getIdToken(true).then(function(idToken) {
    fetch(`/admin/applications/${currentApplicationEmail}/update-api-access`, {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + idToken,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        allow_api_keys: allowApiKeys
      })
    })
    .then(response => response.json())
    .then(data => {
      if (data.status === 'success') {
        statusMessage.innerHTML = '<div class="alert alert-success">API key permission updated successfully!</div>';
        
        // Reload applications after a short delay
        setTimeout(() => {
          document.getElementById('application-modal').style.display = 'none';
          loadApplications();
        }, 1500);
      } else {
        statusMessage.innerHTML = `<div class="alert alert-danger">Error: ${data.error}</div>`;
      }
    })
    .catch(error => {
      console.error('Error updating API key access:', error);
      statusMessage.innerHTML = '<div class="alert alert-danger">Error updating API key permission. Please try again.</div>';
    });
  }).catch(function(error) {
    console.error('Error getting auth token:', error);
    statusMessage.innerHTML = '<div class="alert alert-danger">Authentication error. Please try logging in again.</div>';
  });
}

// Set up event listeners when the document is ready
document.addEventListener('DOMContentLoaded', function() {
  // Set up approve button
  const approveBtn = document.getElementById('approve-btn');
  if (approveBtn) {
    approveBtn.addEventListener('click', approveApplication);
  }
  
  // Set up reject button
  const rejectBtn = document.getElementById('reject-btn');
  if (rejectBtn) {
    rejectBtn.addEventListener('click', function() {
      // Show rejection form
      document.getElementById('rejection-form').style.display = 'block';
      document.getElementById('rejection-reason').focus();
    });
  }
  
  // Set up confirm reject button
  const confirmRejectBtn = document.getElementById('confirm-reject-btn');
  if (confirmRejectBtn) {
    confirmRejectBtn.addEventListener('click', rejectApplication);
  }
  
  // Set up cancel reject button
  const cancelRejectBtn = document.getElementById('cancel-reject-btn');
  if (cancelRejectBtn) {
    cancelRejectBtn.addEventListener('click', function() {
      // Hide rejection form
      document.getElementById('rejection-form').style.display = 'none';
    });
  }
  
  // Set up update API access button
  const updateApiAccessBtn = document.getElementById('update-api-access-btn');
  if (updateApiAccessBtn) {
    updateApiAccessBtn.addEventListener('click', updateApiKeyAccess);
  }
});

// Expose functions to global scope
window.loadApplications = loadApplications;
window.renderApplicationsPage = renderApplicationsPage;
window.showApplicationDetails = showApplicationDetails;
window.approveApplication = approveApplication;
window.rejectApplication = rejectApplication;
window.updateApiKeyAccess = updateApiKeyAccess;