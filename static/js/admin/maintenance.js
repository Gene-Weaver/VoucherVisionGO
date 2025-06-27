// Create a new file: static/js/maintenance.js

// Variables to track maintenance state
let maintenanceEnabled = false;

// Load maintenance status from the API
function loadMaintenanceStatus() {
  const loadingElem = document.getElementById('maintenance-loading');
  const errorElem = document.getElementById('maintenance-error');
  const toggleContainer = document.getElementById('maintenance-toggle-container');
  
  if (loadingElem) loadingElem.style.display = 'block';
  if (errorElem) errorElem.style.display = 'none';
  if (toggleContainer) toggleContainer.style.display = 'none';

  // Get Firebase auth token
  firebase.auth().currentUser.getIdToken(true).then(function(idToken) {
    fetch('/admin/maintenance-status', {
      headers: {
        'Authorization': 'Bearer ' + idToken
      }
    })
    .then(response => response.json())
    .then(data => {
      if (loadingElem) loadingElem.style.display = 'none';
      
      if (data.status === 'success') {
        maintenanceEnabled = data.maintenance_enabled;
        updateMaintenanceToggle();
        if (toggleContainer) toggleContainer.style.display = 'block';
      } else {
        console.error('Failed to load maintenance status:', data.error);
        if (errorElem) {
          errorElem.textContent = 'Error loading maintenance status: ' + data.error;
          errorElem.style.display = 'block';
        }
      }
    })
    .catch(error => {
      console.error('Error loading maintenance status:', error);
      if (loadingElem) loadingElem.style.display = 'none';
      if (errorElem) {
        errorElem.textContent = 'Error loading maintenance status. Please try again.';
        errorElem.style.display = 'block';
      }
    });
  }).catch(function(error) {
    console.error('Error getting auth token:', error);
    if (loadingElem) loadingElem.style.display = 'none';
    if (errorElem) {
      errorElem.textContent = 'Authentication error. Please try logging in again.';
      errorElem.style.display = 'block';
    }
  });
}

// Update the maintenance toggle UI
function updateMaintenanceToggle() {
  const toggle = document.getElementById('maintenance-toggle');
  const statusText = document.getElementById('maintenance-status-text');
  const description = document.getElementById('maintenance-description');
  
  if (toggle) {
    toggle.checked = maintenanceEnabled;
    // Update toggle color based on state
    if (maintenanceEnabled) {
      toggle.classList.add('maintenance-enabled');
      toggle.classList.remove('maintenance-disabled');
    } else {
      toggle.classList.add('maintenance-disabled');
      toggle.classList.remove('maintenance-enabled');
    }
  }
  
  if (statusText) {
    statusText.textContent = maintenanceEnabled ? 'Enabled' : 'Disabled';
    statusText.className = maintenanceEnabled ? 'status-enabled' : 'status-disabled';
  }
  
  if (description) {
    description.textContent = maintenanceEnabled 
      ? 'The API is currently in maintenance mode. All API requests will receive a 503 error.'
      : 'The API is currently operational and accepting requests.';
  }
}

// Toggle maintenance mode
function toggleMaintenanceMode() {
  const toggle = document.getElementById('maintenance-toggle');
  const errorElem = document.getElementById('maintenance-error');
  const successElem = document.getElementById('maintenance-success');
  
  if (!toggle) return;
  
  const newState = toggle.checked;
  
  // Clear previous messages
  if (errorElem) errorElem.style.display = 'none';
  if (successElem) successElem.style.display = 'none';
  
  // Disable toggle temporarily
  toggle.disabled = true;
  
  // Get Firebase auth token
  firebase.auth().currentUser.getIdToken(true).then(function(idToken) {
    fetch('/admin/maintenance-mode', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + idToken,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        enabled: newState
      })
    })
    .then(response => response.json())
    .then(data => {
      toggle.disabled = false;
      
      if (data.status === 'success') {
        maintenanceEnabled = data.maintenance_enabled;
        updateMaintenanceToggle();
        
        if (successElem) {
          successElem.textContent = `Maintenance mode ${maintenanceEnabled ? 'enabled' : 'disabled'} successfully!`;
          successElem.style.display = 'block';
          
          // Hide success message after 3 seconds
          setTimeout(() => {
            successElem.style.display = 'none';
          }, 3000);
        }
      } else {
        // Revert toggle state on error
        toggle.checked = !newState;
        if (errorElem) {
          errorElem.textContent = 'Error: ' + (data.error || 'Failed to update maintenance mode');
          errorElem.style.display = 'block';
        }
      }
    })
    .catch(error => {
      console.error('Error updating maintenance mode:', error);
      toggle.disabled = false;
      // Revert toggle state on error
      toggle.checked = !newState;
      if (errorElem) {
        errorElem.textContent = 'Error updating maintenance mode. Please try again.';
        errorElem.style.display = 'block';
      }
    });
  }).catch(function(error) {
    console.error('Error getting auth token:', error);
    toggle.disabled = false;
    // Revert toggle state on error
    toggle.checked = !newState;
    if (errorElem) {
      errorElem.textContent = 'Authentication error. Please try logging in again.';
      errorElem.style.display = 'block';
    }
  });
}

// Set up event listeners when the document is ready
document.addEventListener('DOMContentLoaded', function() {
  // Set up maintenance toggle event listener
  const toggle = document.getElementById('maintenance-toggle');
  if (toggle) {
    toggle.addEventListener('change', toggleMaintenanceMode);
  }
});

// Expose functions to global scope
window.loadMaintenanceStatus = loadMaintenanceStatus;
window.updateMaintenanceToggle = updateMaintenanceToggle;
window.toggleMaintenanceMode = toggleMaintenanceMode;