// Initialize Firebase
document.addEventListener('DOMContentLoaded', function() {
  // Check if firebaseConfig is defined in the page
  if (typeof firebaseConfig === 'undefined') {
    console.error('Firebase configuration is not defined. The admin dashboard requires a valid Firebase configuration.');
    
    // Display a friendly error message on the page
    const container = document.querySelector('.container');
    if (container) {
      container.innerHTML = `
        <div class="alert alert-danger">
          <h4>Firebase Configuration Error</h4>
          <p>The Firebase configuration is missing. This is likely an issue with how the admin dashboard template is being rendered.</p>
          <p>Please check that the Firebase configuration is being properly passed from app.py to the admin_dashboard.html template.</p>
        </div>
      `;
    }
    return;
  }

  // Initialize Firebase if configuration is available
  try {
    firebase.initializeApp(firebaseConfig);
    console.log('Firebase initialized successfully');
  } catch (error) {
    console.error('Error initializing Firebase:', error);
    return;
  }

  // Variables to store pagination settings
  const itemsPerPage = 10;
  let currentApplicationsPage = 1;
  let currentApiKeysPage = 1;
  let currentAdminsPage = 1;
  let filteredApplications = [];
  let filteredApiKeys = [];
  let allApplications = [];
  let allApiKeys = [];
  let allAdmins = [];
  let currentStatusFilter = 'all';

  // Check if user is authenticated
  firebase.auth().onAuthStateChanged(function(user) {
    if (user) {
      // User is signed in, display their email
      document.getElementById('user-email').textContent = user.email;
      
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
          loadDataForTab(tabId);
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
      const applicationSearch = document.getElementById('application-search');
      if (applicationSearch) {
        applicationSearch.addEventListener('input', () => {
          applyFiltersToApplications();
        });
      }
      
      const apiKeySearch = document.getElementById('api-key-search');
      if (apiKeySearch) {
        apiKeySearch.addEventListener('input', () => {
          const searchTerm = apiKeySearch.value.toLowerCase();
          filteredApiKeys = allApiKeys.filter(key => {
            return key.owner.toLowerCase().includes(searchTerm) || 
                   (key.name && key.name.toLowerCase().includes(searchTerm));
          });
          renderApiKeysPage(1);
        });
      }
      
      // Setup modal event listeners
      setupModals();
      
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
      
      // Load initial data for the active tab
      const activeTab = document.querySelector('.tab-content.active');
      if (activeTab) {
        const tabId = activeTab.id;
        loadDataForTab(tabId);
      }
      
    } else {
      // Not signed in, redirect to login page
      window.location.href = '/login';
    }
  });

  // Load data based on the selected tab
  function loadDataForTab(tabId) {
    switch (tabId) {
      case 'user-applications':
        loadApplications();
        break;
      case 'api-keys':
        loadApiKeys();
        break;
      case 'admins':
        loadAdmins();
        break;
      case 'usage-stats':
        loadUsageStatistics();
        break;
      case 'maintenance':  // Add this case
        loadMaintenanceStatus();
        break;
    }
  }

  // Setup modal event listeners
  function setupModals() {
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
  }

  // Generate pagination buttons
  window.generatePagination = function(totalItems, currentPage, containerId, clickHandler) {
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
  };

  // Apply filters to applications
  window.applyFiltersToApplications = function() {
    const searchTerm = document.getElementById('application-search')?.value.toLowerCase() || '';
    
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
  };

  // Make functions available to other scripts
  window.loadDataForTab = loadDataForTab;
  window.currentStatusFilter = currentStatusFilter;
  window.itemsPerPage = itemsPerPage;
  window.filteredApplications = filteredApplications;
  window.filteredApiKeys = filteredApiKeys;
  window.allApplications = allApplications;
  window.allApiKeys = allApiKeys;
  window.allAdmins = allAdmins;
  window.currentApplicationsPage = currentApplicationsPage;
  window.currentApiKeysPage = currentApiKeysPage;
  window.currentAdminsPage = currentAdminsPage;
});