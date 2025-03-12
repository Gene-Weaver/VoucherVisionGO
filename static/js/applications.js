// Load user applications
async function loadApplications(user) {
    try {
      // Show loading indicator
      document.getElementById('applications-loading').style.display = 'block';
      document.getElementById('applications-table').style.display = 'none';
      
      // Get ID token
      const idToken = await user.getIdToken(true);
      
      // Fetch applications
      const response = await fetch('/admin/applications', {
        headers: {
          'Authorization': `Bearer ${idToken}`
        }
      });
      
      if (!response.ok) {
        throw new Error(`Server returned ${response.status}: ${response.statusText}`);
      }
      
      const data = await response.json();
      
      if (data.status === 'success') {
        // Store all applications
        allApplications = data.applications;
        
        // Apply initial filters
        applyFiltersToApplications();
      } else {
        throw new Error(data.error || 'Failed to load applications');
      }
    } catch (error) {
      console.error('Error loading applications:', error);
      document.getElementById('applications-loading').textContent = 
        'Error loading applications: ' + error.message;
    }
  }
  
  // Render applications page
  function renderApplicationsPage(page) {
    // Update current page
    currentApplicationsPage = page;
    
    // Calculate pagination
    const startIndex = (page - 1) * itemsPerPage;
    const endIndex = startIndex + itemsPerPage;
    const pageApplications = filteredApplications.slice(startIndex, endIndex);
    
    // Hide loading, show table
    document.getElementById('applications-loading').style.display = 'none';
    document.getElementById('applications-table').style.display = 'table';
    
    // Populate table
    const applicationsListElem = document.getElementById('applications-list');
    applicationsListElem.innerHTML = '';
    
    pageApplications.forEach(app => {
      // Format dates
      const createdDate = app.created_at ? new Date(app.created_at._seconds * 1000).toLocaleDateString() : 'N/A';
      
      // Status badge for approval status
      let statusBadge = '';
      switch (app.status) {
        case 'pending':
          statusBadge = '<span class="badge badge-pending">Pending</span>';
          break;
        case 'approved':
          statusBadge = '<span class="badge badge-approved">Approved</span>';
          break;
        case 'rejected':
          statusBadge = '<span class="badge badge-rejected">Rejected</span>';
          break;
        default:
          statusBadge = '<span class="badge">Unknown</span>';
      }
      
      // API access badge (only for approved users)
      let apiAccessBadge = '';
      if (app.status === 'approved') {
        if (app.api_key_access === true) {
          apiAccessBadge = '<span class="badge badge-api-access ms-2" title="Has API key permission">🔑</span>';
        } else {
          apiAccessBadge = '<span class="badge badge-no-api-access ms-2" title="No API key permission">🔒</span>';
        }
      }
      
      const row = document.createElement('tr');
      row.innerHTML = `
        <td>${app.email}</td>
        <td>${app.organization || 'N/A'}</td>
        <td>${app.purpose ? (app.purpose.length > 50 ? app.purpose.substring(0, 50) + '...' : app.purpose) : 'N/A'}</td>
        <td>${statusBadge} ${apiAccessBadge}</td>
        <td>${createdDate}</td>
        <td>
          <button class="btn-primary view-application-btn" data-email="${app.email}">View</button>
        </td>
      `;
      
      applicationsListElem.appendChild(row);
    });
    
    // Setup view buttons
    document.querySelectorAll('.view-application-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const email = btn.getAttribute('data-email');
        viewApplicationDetails(email);
      });
    });
    
    // Generate pagination
    generatePagination(
      filteredApplications.length, 
      currentApplicationsPage, 
      'applications-pagination', 
      renderApplicationsPage
    );
  }
  
  // View application details
  async function viewApplicationDetails(email) {
    try {
      // Set current application email
      currentApplicationEmail = email;
      
      // Find application in the list
      const application = allApplications.find(app => app.email === email);
      
      if (!application) {
        throw new Error('Application not found');
      }
      
      // Format dates
      const createdDate = application.created_at ? 
        new Date(application.created_at._seconds * 1000).toLocaleDateString() : 'N/A';
      const updatedDate = application.updated_at ? 
        new Date(application.updated_at._seconds * 1000).toLocaleDateString() : 'N/A';
      
      // Generate details HTML
      let detailsHtml = `
        <p><strong>Email:</strong> ${application.email}</p>
        <p><strong>Organization:</strong> ${application.organization || 'N/A'}</p>
        <p><strong>Purpose:</strong> ${application.purpose || 'N/A'}</p>
        <p><strong>Status:</strong> ${application.status || 'N/A'}</p>
        <p><strong>Created:</strong> ${createdDate}</p>
        <p><strong>Last Updated:</strong> ${updatedDate}</p>
      `;
      
      // Add API key permission status if approved
      if (application.status === 'approved') {
        const hasApiKeyAccess = application.api_key_access === true;
        detailsHtml += `
          <p><strong>API Key Permission:</strong> 
            <span class="${hasApiKeyAccess ? 'text-success' : 'text-danger'}">
              ${hasApiKeyAccess ? 'Granted' : 'Not Granted'}
            </span>
          </p>
        `;
      }
      
      // Add approval/rejection info if available
      if (application.status === 'approved' && application.approved_by) {
        const approvedDate = application.approved_at ? 
          new Date(application.approved_at._seconds * 1000).toLocaleDateString() : 'N/A';
        detailsHtml += `
          <p><strong>Approved By:</strong> ${application.approved_by}</p>
          <p><strong>Approved Date:</strong> ${approvedDate}</p>
        `;
      } else if (application.status === 'rejected') {
        detailsHtml += `
          <p><strong>Rejected By:</strong> ${application.rejected_by || 'N/A'}</p>
          <p><strong>Rejection Reason:</strong> ${application.rejection_reason || 'No reason provided'}</p>
        `;
      }
      
      // Update modal content
      document.getElementById('application-details').innerHTML = detailsHtml;
      
      // Show/hide action buttons based on status
      if (application.status === 'pending') {
        document.getElementById('application-actions').style.display = 'flex';
        document.getElementById('api-key-permission-group').style.display = 'block';
        document.getElementById('api-key-access-actions').style.display = 'none';
        document.getElementById('rejection-form').style.display = 'none';
        
        // Uncheck the API key permission by default
        document.getElementById('allow-api-keys').checked = false;
      } else if (application.status === 'approved') {
        document.getElementById('application-actions').style.display = 'none';
        document.getElementById('api-key-access-actions').style.display = 'block';
        document.getElementById('rejection-form').style.display = 'none';
        
        // Set the current API key access status
        document.getElementById('update-api-keys').checked = application.api_key_access === true;
      } else {
        document.getElementById('application-actions').style.display = 'none';
        document.getElementById('api-key-access-actions').style.display = 'none';
        document.getElementById('rejection-form').style.display = 'none';
      }
      
      // Clear status message
      document.getElementById('application-status-message').innerHTML = '';
      
      // Show the modal
      document.getElementById('application-modal').style.display = 'block';
      
    } catch (error) {
      console.error('Error viewing application details:', error);
      alert('Error viewing application details: ' + error.message);
    }
  }
  
  // Approve application
  async function approveApplication() {
    if (!currentApplicationEmail) return;
    
    try {
      const user = firebase.auth().currentUser;
      if (!user) throw new Error('Not authenticated');
      
      // Get the API key permission value
      const allowApiKeys = document.getElementById('allow-api-keys').checked;
      
      // Get ID token
      const idToken = await user.getIdToken(true);
      
      // Send approval request with API key permission
      const response = await fetch(`/admin/applications/${currentApplicationEmail}/approve`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${idToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          allow_api_keys: allowApiKeys
        })
      });
      
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || `Server returned ${response.status}`);
      }
      
      const data = await response.json();
      
      if (data.status === 'success') {
        // Show success message
        document.getElementById('application-status-message').innerHTML = `
          <div class="alert alert-success">
            Application approved successfully. The user can now access the API.
            ${allowApiKeys ? 'User has been granted permission to create API keys.' : ''}
          </div>
        `;
        
        // Hide action buttons
        document.getElementById('application-actions').style.display = 'none';
        
        // Show API key access actions now
        document.getElementById('api-key-access-actions').style.display = 'block';
        document.getElementById('update-api-keys').checked = allowApiKeys;
        
        // Update application in the list
        updateApplicationInList(currentApplicationEmail, 'approved', allowApiKeys);
        
        // Reload applications after a short delay
        setTimeout(() => {
          loadApplications(user);
        }, 2000);
      } else {
        throw new Error(data.error || 'Failed to approve application');
      }
    } catch (error) {
      console.error('Error approving application:', error);
      document.getElementById('application-status-message').innerHTML = `
        <div class="alert alert-danger">
          Error approving application: ${error.message}
        </div>
      `;
    }
  }
  
  // Reject application
  async function rejectApplication() {
    if (!currentApplicationEmail) return;
    
    try {
      const user = firebase.auth().currentUser;
      if (!user) throw new Error('Not authenticated');
      
      // Get rejection reason
      const reason = document.getElementById('rejection-reason').value;
      if (!reason) {
        throw new Error('Please provide a reason for rejection');
      }
      
      // Get ID token
      const idToken = await user.getIdToken(true);
      
      // Send rejection request
      const response = await fetch(`/admin/applications/${currentApplicationEmail}/reject`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${idToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          reason: reason
        })
      });
      
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || `Server returned ${response.status}`);
      }
      
      const data = await response.json();
      
      if (data.status === 'success') {
        // Show success message
        document.getElementById('application-status-message').innerHTML = `
          <div class="alert alert-success">
            Application rejected successfully.
          </div>
        `;
        
        // Hide rejection form
        document.getElementById('rejection-form').style.display = 'none';
        
        // Update application in the list
        updateApplicationInList(currentApplicationEmail, 'rejected');
        
        // Reload applications after a short delay
        setTimeout(() => {
          loadApplications(user);
        }, 2000);
      } else {
        throw new Error(data.error || 'Failed to reject application');
      }
    } catch (error) {
      console.error('Error rejecting application:', error);
      document.getElementById('application-status-message').innerHTML = `
        <div class="alert alert-danger">
          Error rejecting application: ${error.message}
        </div>
      `;
    }
  }
  
  // Update API key access for an application
  async function updateApiKeyAccess() {
    if (!currentApplicationEmail) return;
    
    try {
      const user = firebase.auth().currentUser;
      if (!user) throw new Error('Not authenticated');
      
      // Get the updated API key permission
      const allowApiKeys = document.getElementById('update-api-keys').checked;
      
      // Get ID token
      const idToken = await user.getIdToken(true);
      
      // Send the update request
      const response = await fetch(`/admin/applications/${currentApplicationEmail}/update-api-access`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${idToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          allow_api_keys: allowApiKeys
        })
      });
      
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || `Server returned ${response.status}`);
      }
      
      const data = await response.json();
      
      if (data.status === 'success') {
        // Show success message
        document.getElementById('application-status-message').innerHTML = `
          <div class="alert alert-success">
            API key permission ${allowApiKeys ? 'granted' : 'revoked'} successfully.
          </div>
        `;
        
        // Update application in the list
        updateApplicationInList(currentApplicationEmail, 'approved', allowApiKeys);
        
        // Reload applications after a short delay
        setTimeout(() => {
          loadApplications(user);
        }, 2000);
      } else {
        throw new Error(data.error || 'Failed to update API key permission');
      }
    } catch (error) {
      console.error('Error updating API key permission:', error);
      document.getElementById('application-status-message').innerHTML = `
        <div class="alert alert-danger">
          Error updating API key permission: ${error.message}
        </div>
      `;
    }
  }
  
  // Update application in the local list
  function updateApplicationInList(email, newStatus, apiKeyAccess = null) {
    // Find application in the list
    const appIndex = allApplications.findIndex(app => app.email === email);
    
    if (appIndex >= 0) {
      // Update application status
      allApplications[appIndex].status = newStatus;
      
      // Update API key permission if provided
      if (apiKeyAccess !== null) {
        allApplications[appIndex].api_key_access = apiKeyAccess;
      }
      
      // Reapply filters
      applyFiltersToApplications();
    }
  }