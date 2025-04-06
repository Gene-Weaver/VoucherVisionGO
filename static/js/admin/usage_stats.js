// Function to load usage statistics
async function loadUsageStatistics() {
    const usageContainer = document.getElementById('usage-table-container');
    const loadingElem = document.getElementById('usage-loading');
    const tableElem = document.getElementById('usage-table');
    const listElem = document.getElementById('usage-list');
    
    try {
      // Get the Firebase ID token for authentication
      const idToken = await firebase.auth().currentUser.getIdToken();
      
      // Fetch usage statistics from server
      const response = await fetch('/admin/usage-statistics', {
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
          // No usage data found
          usageContainer.innerHTML = '<p>No usage statistics found.</p>';
        } else {
          // Display usage statistics
          tableElem.style.display = 'table';
          
          // Clear existing list
          listElem.innerHTML = '';
          
          // Current and previous month
          const now = new Date();
          const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
          
          // Previous month calculation
          let prevMonth;
          if (now.getMonth() === 0) {
            // January, go to previous year's December
            prevMonth = `${now.getFullYear() - 1}-12`;
          } else {
            prevMonth = `${now.getFullYear()}-${String(now.getMonth()).padStart(2, '0')}`;
          }
          
          // Add each statistic to the table
          data.usage_statistics.forEach(stat => {
            const row = document.createElement('tr');
            
            // Get monthly usage numbers
            const monthlyUsage = stat.monthly_usage || {};
            const currentMonthUsage = monthlyUsage[currentMonth] || 0;
            const prevMonthUsage = monthlyUsage[prevMonth] || 0;
            
            // Format timestamps correctly
            const formatTimestamp = (timestamp) => {
              if (!timestamp) return 'N/A';
              
              // Handle different timestamp formats
              if (timestamp._seconds) {
                // Firestore timestamp from server
                return new Date(timestamp._seconds * 1000).toLocaleString();
              } else if (timestamp._formatted) {
                // Pre-formatted timestamp 
                return timestamp._formatted;
              } else if (timestamp instanceof Date) {
                // JavaScript Date object
                return timestamp.toLocaleString();
              } else if (typeof timestamp === 'string') {
                // ISO string or other string format
                try {
                  return new Date(timestamp).toLocaleString();
                } catch (e) {
                  return timestamp;
                }
              }
              
              return 'N/A';
            };
            
            const firstUsed = formatTimestamp(stat.first_processed_at);
            const lastUsed = formatTimestamp(stat.last_processed_at);
            
            row.innerHTML = `
              <td>${stat.user_email || 'Unknown'}</td>
              <td>${stat.total_images_processed || 0}</td>
              <td>${currentMonthUsage}</td>
              <td>${prevMonthUsage}</td>
              <td>${firstUsed}</td>
              <td>${lastUsed}</td>
              <td>
                <button class="btn-view-details" data-email="${stat.user_email}">View Details</button>
              </td>
            `;
            
            listElem.appendChild(row);
          });
          
          // Add event listeners to details buttons
          document.querySelectorAll('.btn-view-details').forEach(btn => {
            btn.addEventListener('click', (e) => {
              const email = e.target.getAttribute('data-email');
              showUserUsageDetails(email, data.usage_statistics);
            });
          });
          
          // Initialize search functionality
          initializeUsageSearch(data.usage_statistics);
        }
      } else {
        throw new Error(data.error || 'Failed to load usage statistics');
      }
    } catch (error) {
      console.error('Error loading usage statistics:', error);
      loadingElem.style.display = 'none';
      usageContainer.innerHTML = `<p class="error">Error: ${error.message}</p>`;
    }
  }
  
  // Function to show user usage details modal
  function showUserUsageDetails(email, allStats) {
    const userStat = allStats.find(stat => stat.user_email === email);
    
    if (!userStat) {
      alert('User statistics not found');
      return;
    }
    
    // Create and show a modal with detailed statistics
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.style.display = 'block';
    
    // Get engine usage
    const engineUsage = userStat.ocr_info || {};
    let engineHtml = '';
    for (const [engine, count] of Object.entries(engineUsage)) {
      engineHtml += `<tr><td>${engine}</td><td>${count}</td></tr>`;
    }
    
    // Get monthly usage
    const monthlyUsage = userStat.monthly_usage || {};
    const sortedMonths = Object.keys(monthlyUsage).sort().reverse();
    let monthlyHtml = '';
    for (const month of sortedMonths) {
      monthlyHtml += `<tr><td>${month}</td><td>${monthlyUsage[month]}</td></tr>`;
    }
    
    // Format timestamps correctly
    const formatTimestamp = (timestamp) => {
      if (!timestamp) return 'N/A';
      
      // Handle different timestamp formats
      if (timestamp._seconds) {
        // Firestore timestamp from server
        return new Date(timestamp._seconds * 1000).toLocaleString();
      } else if (timestamp._formatted) {
        // Pre-formatted timestamp 
        return timestamp._formatted;
      } else if (timestamp instanceof Date) {
        // JavaScript Date object
        return timestamp.toLocaleString();
      } else if (typeof timestamp === 'string') {
        // ISO string or other string format
        try {
          return new Date(timestamp).toLocaleString();
        } catch (e) {
          return timestamp;
        }
      }
      
      return 'N/A';
    };
    
    const firstUsed = formatTimestamp(userStat.first_processed_at);
    const lastUsed = formatTimestamp(userStat.last_processed_at);
    
    modal.innerHTML = `
      <div class="modal-content">
        <span class="close">&times;</span>
        <h3>Usage Details: ${email}</h3>
        
        <div class="details-section">
          <h4>Summary</h4>
          <p>Total Images Processed: ${userStat.total_images_processed || 0}</p>
          <p>First Used: ${firstUsed}</p>
          <p>Last Used: ${lastUsed}</p>
        </div>
        
        <div class="details-section">
          <h4>Engine Usage</h4>
          <table class="details-table">
            <thead>
              <tr>
                <th>Engine</th>
                <th>Count</th>
              </tr>
            </thead>
            <tbody>
              ${engineHtml || '<tr><td colspan="2">No engine data available</td></tr>'}
            </tbody>
          </table>
        </div>
        
        <div class="details-section">
          <h4>Monthly Usage</h4>
          <table class="details-table">
            <thead>
              <tr>
                <th>Month</th>
                <th>Images Processed</th>
              </tr>
            </thead>
            <tbody>
              ${monthlyHtml || '<tr><td colspan="2">No monthly data available</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    `;
    
    document.body.appendChild(modal);
    
    // Add close button functionality
    const closeBtn = modal.querySelector('.close');
    closeBtn.addEventListener('click', () => {
      document.body.removeChild(modal);
    });
    
    // Close when clicking outside the modal content
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        document.body.removeChild(modal);
      }
    });
  }
  
  // Function to initialize search functionality
  function initializeUsageSearch(allStats) {
    const searchInput = document.getElementById('usage-search');
    
    searchInput.addEventListener('input', () => {
      const searchTerm = searchInput.value.toLowerCase();
      
      // Filter statistics based on search term
      const filteredStats = allStats.filter(stat => 
        stat.user_email && stat.user_email.toLowerCase().includes(searchTerm)
      );
      
      // Update the table
      updateUsageTable(filteredStats);
    });
  }
  
  // Function to update the usage table with filtered data
  function updateUsageTable(filteredStats) {
    const listElem = document.getElementById('usage-list');
    
    // Clear existing list
    listElem.innerHTML = '';
    
    // Current and previous month
    const now = new Date();
    const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
    
    // Previous month calculation
    let prevMonth;
    if (now.getMonth() === 0) {
      // January, go to previous year's December
      prevMonth = `${now.getFullYear() - 1}-12`;
    } else {
      prevMonth = `${now.getFullYear()}-${String(now.getMonth()).padStart(2, '0')}`;
    }
    
    // Add each statistic to the table
    filteredStats.forEach(stat => {
      const row = document.createElement('tr');
      
      // Get monthly usage numbers
      const monthlyUsage = stat.monthly_usage || {};
      const currentMonthUsage = monthlyUsage[currentMonth] || 0;
      const prevMonthUsage = monthlyUsage[prevMonth] || 0;
      
      // Format timestamps
      const lastUsed = stat.last_processed_at && stat.last_processed_at._formatted 
        ? stat.last_processed_at._formatted 
        : 'N/A';
        
      const firstUsed = stat.first_processed_at && stat.first_processed_at._formatted 
        ? stat.first_processed_at._formatted 
        : 'N/A';
      
      row.innerHTML = `
        <td>${stat.user_email || 'Unknown'}</td>
        <td>${stat.total_images_processed || 0}</td>
        <td>${currentMonthUsage}</td>
        <td>${prevMonthUsage}</td>
        <td>${firstUsed}</td>
        <td>${lastUsed}</td>
        <td>
          <button class="btn-view-details" data-email="${stat.user_email}">View Details</button>
        </td>
      `;
      
      listElem.appendChild(row);
    });
    
    // Add event listeners to details buttons
    document.querySelectorAll('.btn-view-details').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const email = e.target.getAttribute('data-email');
        showUserUsageDetails(email, filteredStats);
      });
    });
  }
  
  // Initialize usage statistics tab when selected
  document.addEventListener('DOMContentLoaded', function() {
    // When the usage statistics tab is selected
    const usageStatsTab = document.querySelector('.tab-button[data-tab="usage-stats"]');
    if (usageStatsTab) {
      usageStatsTab.addEventListener('click', function() {
        loadUsageStatistics();
      });
    }
  });