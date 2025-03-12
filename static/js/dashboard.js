// Initialize Firebase
firebase.initializeApp(firebaseConfig);

// Variables to store pagination settings
const itemsPerPage = 10;
let currentApplicationsPage = 1;
let currentApiKeysPage = 1;
let filteredApplications = [];
let filteredApiKeys = [];
let allApplications = [];
let allApiKeys = [];
let currentStatusFilter = 'all';

// Variables to store current application or API key being viewed
let currentApplicationEmail = null;
let currentKeyId = null;

// Initialize the page
function initPage() {
  // Check if user is authenticated
  firebase.auth().onAuthStateChanged(function(user) {
    if (user) {
      // User is signed in, display their email
      document.getElementById('user-email').textContent = user.email;
      
      // Load initial data
      loadApplications(user);
      
      // Set up tab buttons
      const tabButtons = document.querySelectorAll('.tab-button');
      const tabContents = document.querySelectorAll('.tab-content');
      
      tabButtons.forEach(button => {
        button.addEventListener('click', () => {
          // Remove active class from all buttons and contents
          tabButtons.forEach(btn => btn.classList.remove('active'));
          tabContents.forEach(content => content.classList.remove('active'));
          
          // Add active class to clicked button and corresponding content
          button.classList.add('active');
          const tabId = button.getAttribute('data-tab');
          document.getElementById(tabId).classList.add('active');
          
          // Load data for the selected tab
          loadDataForTab(tabId, user);
        });
      });
      
      // Set up status filters
      const filterButtons = document.querySelectorAll('.filter-btn');
      filterButtons.forEach(button => {
        button.addEventListener('click', () => {
          // Remove active class from all filter buttons
          filterButtons.forEach(btn => btn.classList.remove('active'));
          
          // Add active class to clicked button
          button.classList.add('active');
          
          // Update filter and apply
          currentStatusFilter = button.getAttribute('data-status');
          applyFiltersToApplications();
        });
      });
      
      // Setup search functionality
      setupSearch();
      
      // Setup modal event listeners
      setupModalEventListeners(user);
      
    } else {
      // Not signed in, redirect to login page
      window.location.href = '/login';
    }
  });
}

// Load data based on the selected tab
function loadDataForTab(tabId, user) {
  switch (tabId) {
    case 'user-applications':
      loadApplications(user);
      break;
    case 'api-keys':
      loadApiKeys(user);
      break;
    case 'admins':
      loadAdmins(user);
      break;
  }
}

// Setup search functionality
function setupSearch() {
  const applicationSearch = document.getElementById('application-search');
  applicationSearch.addEventListener('input', () => {
    applyFiltersToApplications();
  });
  
  const apiKeySearch = document.getElementById('api-key-search');
  apiKeySearch.addEventListener('input', () => {
    const searchTerm = apiKeySearch.value.toLowerCase();
    filteredApiKeys = allApiKeys.filter(key => {
      return key.owner.toLowerCase().includes(searchTerm) || 
              (key.name && key.name.toLowerCase().includes(searchTerm));
    });
    renderApiKeysPage(1);
  });
}

// Generate pagination buttons
function generatePagination(totalItems, currentPage, containerId, clickHandler) {
  const totalPages = Math.ceil(totalItems / itemsPerPage);
  const container = document.getElementById(containerId);
  
  if (totalPages <= 1) {
    container.innerHTML = '';
    return;
  }
  
  let html = '';
  
  // Previous button
  html += `<button ${currentPage === 1 ? 'disabled' : ''} data-page="${currentPage - 1}">Prev</button>`;
  
  // Page buttons
  const maxButtons = 5;
  const startPage = Math.max(1, currentPage - Math.floor(maxButtons / 2));
  const endPage = Math.min(totalPages, startPage + maxButtons - 1);
  
  for (let i = startPage; i <= endPage; i++) {
    html += `<button class="${i === currentPage ? 'active' : ''}" data-page="${i}">${i}</button>`;
  }
  
  // Next button
  html += `<button ${currentPage === totalPages ? 'disabled' : ''} data-page="${currentPage + 1}">Next</button>`;
  
  container.innerHTML = html;
  
  // Add event listeners
  container.querySelectorAll('button:not([disabled])').forEach(btn => {
    btn.addEventListener('click', () => {
      const page = parseInt(btn.getAttribute('data-page'));
      clickHandler(page);
    });
  });
}

// Setup modal event listeners
function setupModalEventListeners(user) {
  // Close buttons for modals
  document.querySelectorAll('.close').forEach(closeBtn => {
    closeBtn.addEventListener('click', function() {
      // Find the parent modal and hide it
      let modal = this.closest('.modal');
      if (modal) {
        modal.style.display = 'none';
      }
    });
  });
  
  // Close modals when clicking outside
  window.addEventListener('click', function(event) {
    document.querySelectorAll('.modal').forEach(modal => {
      if (event.target === modal) {
        modal.style.display = 'none';
      }
    });
  });
  
  // Add admin button
  const addAdminBtn = document.getElementById('add-admin-btn');
  if (addAdminBtn) {
    addAdminBtn.addEventListener('click', function() {
      document.getElementById('add-admin-modal').style.display = 'block';
    });
  }
  
  // Confirm add admin button
  const confirmAddAdminBtn = document.getElementById('confirm-add-admin-btn');
  if (confirmAddAdminBtn) {
    confirmAddAdminBtn.addEventListener('click', function() {
      addAdmin();
    });
  }
  
  // Approve button
  const approveBtn = document.getElementById('approve-btn');
  if (approveBtn) {
    approveBtn.addEventListener('click', function() {
      approveApplication();
    });
  }
  
  // Reject button
  const rejectBtn = document.getElementById('reject-btn');
  if (rejectBtn) {
    rejectBtn.addEventListener('click', function() {
      // Show rejection form
      document.getElementById('rejection-form').style.display = 'block';
      document.getElementById('rejection-reason').focus();
    });
  }
  
  // Confirm reject button
  const confirmRejectBtn = document.getElementById('confirm-reject-btn');
  if (confirmRejectBtn) {
    confirmRejectBtn.addEventListener('click', function() {
      rejectApplication();
    });
  }
  
  // Cancel reject button
  const cancelRejectBtn = document.getElementById('cancel-reject-btn');
  if (cancelRejectBtn) {
    cancelRejectBtn.addEventListener('click', function() {
      // Hide rejection form
      document.getElementById('rejection-form').style.display = 'none';
    });
  }

  // Update API access button
  const updateApiAccessBtn = document.getElementById('update-api-access-btn');
  if (updateApiAccessBtn) {
    updateApiAccessBtn.addEventListener('click', function() {
      updateApiKeyAccess();
    });
  }
  
  // Confirm revoke key button
  const confirmRevokeKeyBtn = document.getElementById('confirm-revoke-key-btn');
  if (confirmRevokeKeyBtn) {
    confirmRevokeKeyBtn.addEventListener('click', function() {
      revokeApiKey();
    });
  }
  
  // Cancel revoke key button
  const cancelRevokeKeyBtn = document.getElementById('cancel-revoke-key-btn');
  if (cancelRevokeKeyBtn) {
    cancelRevokeKeyBtn.addEventListener('click', function() {
      document.getElementById('revoke-key-modal').style.display = 'none';
    });
  }
  
  // Logout button
  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', function() {
      firebase.auth().signOut().then(function() {
        window.location.href = '/login';
      }).catch(function(error) {
        console.error('Error signing out:', error);
      });
    });
  }
}

// Apply filters to applications
function applyFiltersToApplications() {
  const searchTerm = document.getElementById('application-search').value.toLowerCase();
  
  filteredApplications = allApplications.filter(app => {
    // Status filter
    if (currentStatusFilter !== 'all' && app.status !== currentStatusFilter) {
      return false;
    }
    
    // Search term filter
    if (searchTerm) {
      return app.email.toLowerCase().includes(searchTerm) || 
              (app.organization && app.organization.toLowerCase().includes(searchTerm));
    }
    
    return true;
  });
  
  renderApplicationsPage(1);
}

// Start the page initialization when the DOM is ready
document.addEventListener('DOMContentLoaded', initPage);