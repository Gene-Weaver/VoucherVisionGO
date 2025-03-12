// Load admins from the API
function loadAdmins() {
    document.getElementById('admins-loading').style.display = 'block';
    document.getElementById('admins-table').style.display = 'none';
  
    // Get Firebase auth token
    firebase.auth().currentUser.getIdToken(true).then(function(idToken) {
      fetch('/admin/list-admins', {
        headers: {
          'Authorization': 'Bearer ' + idToken
        }
      })
      .then(response => response.json())
      .then(data => {
        if (data.status === 'success') {
          window.allAdmins = data.admins;
          renderAdminsTable();
        } else {
          console.error('Failed to load admins:', data.error);
          document.getElementById('admins-loading').textContent = 'Error loading admins: ' + data.error;
        }
      })
      .catch(error => {
        console.error('Error loading admins:', error);
        document.getElementById('admins-loading').textContent = 'Error loading admins. Please try again.';
      });
    }).catch(function(error) {
      console.error('Error getting auth token:', error);
      document.getElementById('admins-loading').textContent = 'Authentication error. Please try logging in again.';
    });
  }
  
  // Render the admins table
  function renderAdminsTable() {
    const tableBody = document.getElementById('admins-list');
    tableBody.innerHTML = '';
    
    if (window.allAdmins.length === 0) {
      document.getElementById('admins-loading').style.display = 'block';
      document.getElementById('admins-loading').textContent = 'No admins found.';
      document.getElementById('admins-table').style.display = 'none';
      return;
    }
    
    document.getElementById('admins-loading').style.display = 'none';
    document.getElementById('admins-table').style.display = 'table';
    
    // Display the current user's email
    const currentUserEmail = firebase.auth().currentUser.email;
    
    window.allAdmins.forEach(admin => {
      const addedDate = admin.added_at && admin.added_at._seconds ? 
        new Date(admin.added_at._seconds * 1000).toLocaleDateString() : 'Unknown';
      
      const row = document.createElement('tr');
      
      // Email column
      const emailCell = document.createElement('td');
      emailCell.textContent = admin.email;
      row.appendChild(emailCell);
      
      // Added by column
      const addedByCell = document.createElement('td');
      addedByCell.textContent = admin.added_by || 'Unknown';
      row.appendChild(addedByCell);
      
      // Added date column
      const addedDateCell = document.createElement('td');
      addedDateCell.textContent = addedDate;
      row.appendChild(addedDateCell);
      
      // Actions column
      const actionsCell = document.createElement('td');
      
      // Don't allow removing yourself or the initial system admin
      if (admin.email !== currentUserEmail && admin.added_by !== 'System') {
        const removeButton = document.createElement('button');
        removeButton.className = 'btn-danger';
        removeButton.textContent = 'Remove';
        removeButton.addEventListener('click', () => removeAdmin(admin.email));
        actionsCell.appendChild(removeButton);
      } else {
        if (admin.email === currentUserEmail) {
          const selfText = document.createElement('span');
          selfText.textContent = 'Current User';
          selfText.className = 'text-muted';
          actionsCell.appendChild(selfText);
        } else if (admin.added_by === 'System') {
          const systemText = document.createElement('span');
          systemText.textContent = 'System Admin';
          systemText.className = 'text-muted';
          actionsCell.appendChild(systemText);
        }
      }
      
      row.appendChild(actionsCell);
      
      tableBody.appendChild(row);
    });
  }
  
  // Add a new admin
  function addAdmin() {
    const email = document.getElementById('admin-email').value.trim();
    const errorDiv = document.getElementById('add-admin-error');
    const successDiv = document.getElementById('add-admin-success');
    
    // Clear previous messages
    errorDiv.style.display = 'none';
    successDiv.style.display = 'none';
    
    if (!email) {
      errorDiv.textContent = 'Please enter an email address';
      errorDiv.style.display = 'block';
      return;
    }
    
    // Validate email format with a simple regex
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      errorDiv.textContent = 'Please enter a valid email address';
      errorDiv.style.display = 'block';
      return;
    }
    
    // Get Firebase auth token
    firebase.auth().currentUser.getIdToken(true).then(function(idToken) {
      fetch('/admin/add-admin', {
        method: 'POST',
        headers: {
          'Authorization': 'Bearer ' + idToken,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          email: email
        })
      })
      .then(response => response.json())
      .then(data => {
        if (data.status === 'success') {
          successDiv.textContent = 'Admin added successfully!';
          successDiv.style.display = 'block';
          document.getElementById('admin-email').value = '';
          
          // Reload admins after a short delay
          setTimeout(() => {
            loadAdmins();
          }, 1500);
        } else {
          errorDiv.textContent = 'Error: ' + (data.error || 'Failed to add admin');
          errorDiv.style.display = 'block';
        }
      })
      .catch(error => {
        console.error('Error adding admin:', error);
        errorDiv.textContent = 'Error adding admin. Please try again.';
        errorDiv.style.display = 'block';
      });
    }).catch(function(error) {
      console.error('Error getting auth token:', error);
      errorDiv.textContent = 'Authentication error. Please try logging in again.';
      errorDiv.style.display = 'block';
    });
  }
  
  // Remove an admin
  function removeAdmin(email) {
    if (!confirm(`Are you sure you want to remove ${email} as an admin?`)) {
      return;
    }
    
    // Get Firebase auth token
    firebase.auth().currentUser.getIdToken(true).then(function(idToken) {
      fetch('/admin/remove-admin', {
        method: 'POST',
        headers: {
          'Authorization': 'Bearer ' + idToken,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          email: email
        })
      })
      .then(response => response.json())
      .then(data => {
        if (data.status === 'success') {
          alert('Admin removed successfully!');
          // Reload admins
          loadAdmins();
        } else {
          alert('Error: ' + (data.error || 'Failed to remove admin'));
        }
      })
      .catch(error => {
        console.error('Error removing admin:', error);
        alert('Error removing admin. Please try again.');
      });
    }).catch(function(error) {
      console.error('Error getting auth token:', error);
      alert('Authentication error. Please try logging in again.');
    });
  }
  
  // Set up event listeners when the document is ready
  document.addEventListener('DOMContentLoaded', function() {
    // Add admin button
    const addAdminBtn = document.getElementById('add-admin-btn');
    if (addAdminBtn) {
      addAdminBtn.addEventListener('click', function() {
        document.getElementById('add-admin-modal').style.display = 'block';
        document.getElementById('admin-email').value = '';
        document.getElementById('add-admin-error').style.display = 'none';
        document.getElementById('add-admin-success').style.display = 'none';
      });
    }
    
    // Confirm add admin button
    const confirmAddAdminBtn = document.getElementById('confirm-add-admin-btn');
    if (confirmAddAdminBtn) {
      confirmAddAdminBtn.addEventListener('click', addAdmin);
    }
  });
  
  // Expose functions to global scope
  window.loadAdmins = loadAdmins;
  window.renderAdminsTable = renderAdminsTable;
  window.addAdmin = addAdmin;
  window.removeAdmin = removeAdmin;