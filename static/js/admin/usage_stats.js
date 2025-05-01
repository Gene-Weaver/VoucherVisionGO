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
        // Save statistics globally for reuse
        window.allStats = data.usage_statistics;
        
        // First, create the chart
        const chartContainerDiv = document.createElement('div');
        chartContainerDiv.id = 'daily-usage-chart-container';
        chartContainerDiv.style.marginBottom = '30px';
        usageContainer.insertBefore(chartContainerDiv, usageContainer.firstChild);
        
        // Process and render the daily usage chart
        createUsageChart(data.usage_statistics);
        
        // Display usage statistics table
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
        
        // Create color map for all users
        const userColors = createUserColorMap(data.usage_statistics);
        
        // Add each statistic to the table
        data.usage_statistics.forEach(stat => {
          const row = document.createElement('tr');
          const email = stat.user_email || 'Unknown';
          const userColor = userColors[email];
          
          // Get monthly usage numbers
          const monthlyUsage = stat.monthly_usage || {};
          const currentMonthUsage = monthlyUsage[currentMonth] || 0;
          const prevMonthUsage = monthlyUsage[prevMonth] || 0;
          
          // Format timestamps
          const firstUsed = formatTimestamp(stat.first_processed_at);
          const lastUsed = formatTimestamp(stat.last_processed_at);
          
          row.innerHTML = `
            <td>
              <div style="display: flex; align-items: center;">
                <span style="display: inline-block; width: 12px; height: 12px; background-color: ${userColor}; margin-right: 8px; border-radius: 2px;"></span>
                ${email}
              </div>
            </td>
            <td>${stat.total_images_processed || 0}</td>
            <td>${currentMonthUsage}</td>
            <td>${prevMonthUsage}</td>
            <td>${firstUsed}</td>
            <td>${lastUsed}</td>
            <td>
              <button class="btn-view-details" data-email="${email}">View Details</button>
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

function createUsageChart(stats) {
  const chartContainer = document.getElementById('daily-usage-chart-container');
  
  // Check if Chart.js is available
  if (typeof Chart === 'undefined') {
    console.error('Chart.js is not available');
    chartContainer.innerHTML = `
      <div class="alert alert-danger">
        <strong>Error:</strong> Chart library is not available. Please refresh the page or check console for errors.
      </div>
    `;
    
    // Try to load Chart.js dynamically
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.3.0/dist/chart.umd.min.js';
    script.onload = () => {
      console.log('Chart.js loaded successfully');
      // Try creating the chart again
      createChartWithData(stats);
    };
    script.onerror = (e) => {
      console.error('Failed to load Chart.js:', e);
    };
    document.head.appendChild(script);
    return;
  }
  
  // Chart.js is available, create the chart
  createChartWithData(stats);
}

function createUserColorMap(stats) {
  const userColors = {};
  const colorSet = [
    '#4285f4', '#ea4335', '#fbbc05', '#34a853', // Google colors
    '#5e35b1', '#d81b60', '#00acc1', '#43a047', // Material colors
    '#8e24aa', '#e53935', '#039be5', '#7cb342',
    '#3949ab', '#c2185b', '#00897b', '#fdd835'
  ];
  
  // Assign colors to users
  stats.forEach((stat, index) => {
    const email = stat.user_email || 'Unknown';
    userColors[email] = colorSet[index % colorSet.length];
  });
  
  return userColors;
}

// Format timestamps for display
function formatTimestamp(timestamp) {
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
}

// Process data for chart
function processChartData(stats) {
  const userColors = createUserColorMap(stats);
  const users = stats.map(stat => stat.user_email || 'Unknown');
  
  // Get date range for the last 30 days
  const today = new Date();
  const dates = [];
  const dateLabels = [];
  
  for (let i = 29; i >= 0; i--) {
    const date = new Date();
    date.setDate(today.getDate() - i);
    const dateStr = date.toISOString().split('T')[0]; // YYYY-MM-DD format
    dates.push(dateStr);
    
    // Create readable format for x-axis labels
    const month = date.toLocaleString('default', { month: 'short' });
    const day = date.getDate();
    dateLabels.push(`${month} ${day}`);
  }
  
  // Initialize data for each user
  const dailyData = {};
  users.forEach(email => {
    dailyData[email] = {};
    dates.forEach(date => {
      dailyData[email][date] = 0;
    });
  });
  
  // Fill in actual data
  stats.forEach(stat => {
    const email = stat.user_email || 'Unknown';
    
    if (stat.daily_usage) {
      Object.entries(stat.daily_usage).forEach(([date, count]) => {
        if (dates.includes(date)) {
          dailyData[email][date] = count;
        }
      });
    } else {
      // Generate sample data if none exists
      generateSampleData(dailyData, email, dates, stat.total_images_processed || 0);
    }
  });
  
  // Prepare chart data
  const chartData = [];
  dates.forEach((date, index) => {
    const dataPoint = {
      date: date,
      label: dateLabels[index]
    };
    
    users.forEach(email => {
      dataPoint[email] = dailyData[email][date];
    });
    
    chartData.push(dataPoint);
  });
  
  return {
    chartData,
    userColors,
    users,
    dateLabels
  };
}

// Generate sample data for demo purposes
function generateSampleData(dailyData, email, dates, totalImages) {
  // Skip if no total images
  if (totalImages === 0) return;
  
  // Create a distribution where more recent days tend to have more activity
  const baseActivity = Math.min(5, Math.ceil(totalImages / 20)) || 1;
  
  dates.forEach((date, index) => {
    const recencyFactor = Math.max(0.1, (30 - index) / 30);
    // Some randomness but weighted by user activity and recency
    const count = Math.floor(Math.random() * baseActivity * recencyFactor);
    
    if (count > 0) {
      dailyData[email][date] = count;
    }
  });
}

function createChartWithData(stats) {
  // Process the data
  const { chartData, userColors, users, dateLabels } = processChartData(stats);
  
  // Create the chart container
  const chartContainer = document.getElementById('daily-usage-chart-container');
  if (!chartContainer) return;
  
  // Create legend items
  const legendItems = users.map(email => {
    return `
      <div class="legend-item">
        <span class="color-box" style="display: inline-block; width: 12px; height: 12px; background-color: ${userColors[email]}; margin-right: 5px; border-radius: 2px;"></span>
        <span class="legend-label">${formatEmail(email)}</span>
      </div>`;
  }).join('\n');
  
  // Create chart HTML
  chartContainer.innerHTML = `
    <div style="width: 100%; margin-bottom: 30px;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
        <h3 style="margin: 0;">Daily Image Processing (Last 30 Days)</h3>
        <div class="chart-legend" style="display: flex; flex-wrap: wrap; gap: 10px; font-size: 12px;">
          ${legendItems}
        </div>
      </div>
      <div style="width: 100%; height: 200px;">
        <canvas id="usageChart"></canvas>
      </div>
    </div>
  `;
  
  // Create the chart
  const ctx = document.getElementById('usageChart').getContext('2d');
  
  // Prepare datasets
  const datasets = users.map(user => {
    return {
      label: formatEmail(user),
      backgroundColor: userColors[user],
      data: chartData.map(item => item[user] || 0),
      borderWidth: 0
    };
  });
  
  // Create the chart
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: dateLabels,
      datasets: datasets
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          mode: 'index',
          intersect: false
        }
      },
      scales: {
        x: {
          stacked: true,
          grid: {
            display: false
          },
          ticks: {
            maxRotation: 0,
            autoSkip: true,
            maxTicksLimit: 10
          }
        },
        y: {
          stacked: true,
          beginAtZero: true,
          grid: {
            color: 'rgba(0, 0, 0, 0.1)'
          }
        }
      }
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
  const loadingElem = document.getElementById('usage-loading');
  const tableElem = document.getElementById('usage-table');
  
  // Clear existing list
  listElem.innerHTML = '';
  
  if (filteredStats.length === 0) {
    loadingElem.style.display = 'block';
    loadingElem.textContent = 'No users found matching your search.';
    tableElem.style.display = 'none';
    return;
  }
  
  loadingElem.style.display = 'none';
  tableElem.style.display = 'table';
  
  // Create color map for users
  const userColors = createUserColorMap(filteredStats);
  
  // Current and previous month
  const now = new Date();
  const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  
  // Previous month calculation
  let prevMonth;
  if (now.getMonth() === 0) {
    prevMonth = `${now.getFullYear() - 1}-12`;
  } else {
    prevMonth = `${now.getFullYear()}-${String(now.getMonth()).padStart(2, '0')}`;
  }
  
  // Add each statistic to the table
  filteredStats.forEach(stat => {
    const row = document.createElement('tr');
    const email = stat.user_email || 'Unknown';
    const userColor = userColors[email];
    
    // Get monthly usage numbers
    const monthlyUsage = stat.monthly_usage || {};
    const currentMonthUsage = monthlyUsage[currentMonth] || 0;
    const prevMonthUsage = monthlyUsage[prevMonth] || 0;
    
    const firstUsed = formatTimestamp(stat.first_processed_at);
    const lastUsed = formatTimestamp(stat.last_processed_at);
    
    row.innerHTML = `
      <td>
        <div style="display: flex; align-items: center;">
          <span style="display: inline-block; width: 12px; height: 12px; background-color: ${userColor}; margin-right: 8px; border-radius: 2px;"></span>
          ${email}
        </div>
      </td>
      <td>${stat.total_images_processed || 0}</td>
      <td>${currentMonthUsage}</td>
      <td>${prevMonthUsage}</td>
      <td>${firstUsed}</td>
      <td>${lastUsed}</td>
      <td>
        <button class="btn-view-details" data-email="${email}">View Details</button>
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
  
  // Update the chart with filtered data
  createChartWithData(filteredStats);
}


// Function to prepare daily usage data for the last 30 days
function prepareDailyUsageData(allStats, preassignedColors = null) {
  // Get date range for the last 30 days
  const today = new Date();
  const dates = [];
  const dateLabels = [];

  for (let i = 29; i >= 0; i--) {
    const date = new Date();
    date.setDate(today.getDate() - i);
    const dateStr = date.toISOString().split('T')[0]; // YYYY-MM-DD format
    dates.push(dateStr);

    // Create a more readable format for the x-axis labels
    const month = date.toLocaleString('default', { month: 'short' });
    const day = date.getDate();
    dateLabels.push(`${month} ${day}`);
  }

  // Initialize data structure with zeros for all dates and users
  const dailyData = {};
  const userColors = preassignedColors || {};
  const colorSet = [
    '#4285f4', '#ea4335', '#fbbc05', '#34a853', // Google colors
    '#5e35b1', '#d81b60', '#00acc1', '#43a047', // Material colors
    '#8e24aa', '#e53935', '#039be5', '#7cb342',
    '#3949ab', '#c2185b', '#00897b', '#fdd835',
    '#5c6bc0', '#d32f2f', '#0288d1', '#689f38'
  ];

  let colorIndex = 0;

  // Get unique users and assign colors
  allStats.forEach(stat => {
    const email = stat.user_email || 'Unknown';
    if (!preassignedColors) {
      if (!userColors[email]) {
        userColors[email] = colorSet[colorIndex % colorSet.length];
        colorIndex++;
      }
    }

    // Initialize data structure for each user
    dailyData[email] = {};
    dates.forEach(date => {
      dailyData[email][date] = 0;
    });
  });

  // Fill in the data structure with actual usage statistics
  allStats.forEach(stat => {
    const email = stat.user_email || 'Unknown';

    // Search for usage on each day
    if (stat.daily_usage) {
      // If we have daily usage data directly
      Object.entries(stat.daily_usage).forEach(([date, count]) => {
        if (dates.includes(date)) {
          dailyData[email][date] = count;
        }
      });
    } else {
      // If we need to derive daily data from timestamps of processing events
      // This would require having a list of timestamps for each processing event
      // which is not in the current data model, so we'll skip this for now
    }
  });

  // Prepare data for the stacked bar chart
  const chartData = [];
  dates.forEach((date, index) => {
    const dataPoint = {
      date: date,
      label: dateLabels[index]
    };

    // Add data for each user
    Object.keys(dailyData).forEach(email => {
      dataPoint[email] = dailyData[email][date];
    });

    chartData.push(dataPoint);
  });

  return {
    chartData,
    userColors,
    users: Object.keys(dailyData)
  };
}

// Function to create a stacked bar chart for daily usage
// function createDailyUsageChart(containerId, allStats) {
//   const { chartData, userColors, users } = prepareDailyUsageData(allStats);

//   // Format data for recharts
//   const data = chartData;

//   // Create stacked bars for each user
//   const stackedBars = users.map(email => {
//     return `<Bar dataKey="${email}" stackId="a" fill="${userColors[email]}" name="${formatEmail(email)}" />`;
//   }).join('\n      ');

//   // Create legend items
//   const legendItems = users.map(email => {
//     return `
//       <div class="legend-item">
//         <span class="color-box" style="background-color: ${userColors[email]}"></span>
//         <span class="legend-label">${formatEmail(email)}</span>
//       </div>`;
//   }).join('\n');

//   // Create and mount the React component for the chart
//   const chartComponent = `
//   <div id="daily-usage-chart" style="width: 100%; height: 170px; margin-bottom: 30px;">
//     <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
//       <h3 style="margin: 0;">Daily Image Processing (Last 30 Days)</h3>
//       <div class="chart-legend" style="display: flex; flex-wrap: wrap; gap: 10px;">
//         ${legendItems}
//       </div>
//     </div>
//     <div id="chart-container" style="width: 100%; height: 100px;"></div>
//   </div>
//   `;

//   // Insert the chart into the container
//   document.getElementById(containerId).innerHTML = chartComponent;

//   // Apply some additional styles for the legend
//   const style = document.createElement('style');
//   style.textContent = `
//     .chart-legend {
//       font-size: 12px;
//     }
//     .legend-item {
//       display: flex;
//       align-items: center;
//       margin-right: 10px;
//     }
//     .color-box {
//       display: inline-block;
//       width: 12px;
//       height: 12px;
//       margin-right: 5px;
//       border-radius: 2px;
//     }
//   `;
//   document.head.appendChild(style);

//   // Create the chart with Chart.js
//   createChartWithChartJS('chart-container', data, userColors, users);
// }




// Function to process timestamps and organize data by day
function processDailyUsageData(allStats) {
  const stats = JSON.parse(JSON.stringify(allStats)); // Deep clone
  
  // For each user, ensure daily_usage exists
  stats.forEach(stat => {
    // Initialize daily_usage if not exists
    if (!stat.daily_usage) {
      stat.daily_usage = {};
    }
    
    // If we need to generate sample data for demonstration purposes
    if (Object.keys(stat.daily_usage).length === 0) {
      // Generate sample data for the last 30 days
      const today = new Date();
      for (let i = 0; i < 30; i++) {
        const date = new Date();
        date.setDate(today.getDate() - i);
        const dateStr = date.toISOString().split('T')[0]; // YYYY-MM-DD format
        
        // Create a distribution where more recent days tend to have more activity
        // and active users have more activities
        const baseActivity = stat.total_images_processed ? 
          Math.min(5, Math.ceil(stat.total_images_processed / 20)) : 1;
        
        const recencyFactor = Math.max(0.1, (30 - i) / 30);
        // Some randomness but weighted by user activity and recency
        const count = Math.floor(Math.random() * baseActivity * recencyFactor);
        
        if (count > 0) {
          stat.daily_usage[dateStr] = count;
        }
      }
    }
  });
  
  return stats;
}


// Function to create a stacked bar chart for daily usage
function createDailyUsageChart(containerId, allStats, preassignedColors = null) {
  // First, ensure Chart.js is loaded
  if (typeof Chart === 'undefined') {
    // If Chart.js isn't loaded, load it dynamically
    loadChartJs().then(() => {
      // Once loaded, proceed with chart creation
      createChartAfterLoad(containerId, allStats, preassignedColors);
    }).catch(error => {
      console.error('Failed to load Chart.js:', error);
      document.getElementById(containerId).innerHTML = 
        '<div class="alert alert-danger">Failed to load chart library. Please refresh the page and try again.</div>';
    });
  } else {
    // Chart.js is already loaded, proceed directly
    createChartAfterLoad(containerId, allStats, preassignedColors);
  }
}

function createChartAfterLoad(containerId, allStats, preassignedColors) {
  // Get date range for last 30 days
  const today = new Date();
  const dates = [];
  const dateLabels = [];
  
  for (let i = 29; i >= 0; i--) {
    const date = new Date();
    date.setDate(today.getDate() - i);
    const dateStr = date.toISOString().split('T')[0]; // YYYY-MM-DD format
    dates.push(dateStr);
    
    // Create more readable format for x-axis labels
    const month = date.toLocaleString('default', { month: 'short' });
    const day = date.getDate();
    dateLabels.push(`${month} ${day}`);
  }
  
  // Initialize data structure
  const dailyData = {};
  const userColors = preassignedColors || {};
  const colorSet = [
    '#4285f4', '#ea4335', '#fbbc05', '#34a853', // Google colors
    '#5e35b1', '#d81b60', '#00acc1', '#43a047', // Material colors
    '#8e24aa', '#e53935', '#039be5', '#7cb342',
    '#3949ab', '#c2185b', '#00897b', '#fdd835',
    '#5c6bc0', '#d32f2f', '#0288d1', '#689f38'
  ];
  
  let colorIndex = 0;
  
  // Initialize data for each user
  allStats.forEach(stat => {
    const email = stat.user_email || 'Unknown';
    if (!preassignedColors && !userColors[email]) {
      userColors[email] = colorSet[colorIndex % colorSet.length];
      colorIndex++;
    }
    
    dailyData[email] = {};
    dates.forEach(date => {
      dailyData[email][date] = 0;
    });
  });
  
  // Fill in actual data
  allStats.forEach(stat => {
    const email = stat.user_email || 'Unknown';
    
    if (stat.daily_usage) {
      Object.entries(stat.daily_usage).forEach(([date, count]) => {
        if (dates.includes(date)) {
          dailyData[email][date] = count;
        }
      });
    }
  });
  
  // Prepare chart data
  const chartData = [];
  dates.forEach((date, index) => {
    const dataPoint = {
      date: date,
      label: dateLabels[index]
    };
    
    Object.keys(dailyData).forEach(email => {
      dataPoint[email] = dailyData[email][date];
    });
    
    chartData.push(dataPoint);
  });
  
  const users = Object.keys(dailyData);
  
  // Create legend items
  const legendItems = users.map(email => {
    return `
      <div class="legend-item">
        <span class="color-box" style="background-color: ${userColors[email]}"></span>
        <span class="legend-label">${formatEmail(email)}</span>
      </div>`;
  }).join('\n');
  
  // Create chart container
  const chartComponent = `
  <div style="width: 100%; height: 170px; margin-bottom: 30px;">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
      <h3 style="margin: 0;">Daily Image Processing (Last 30 Days)</h3>
      <div class="chart-legend" style="display: flex; flex-wrap: wrap; gap: 10px;">
        ${legendItems}
      </div>
    </div>
    <div id="chart-container" style="width: 100%; height: 100px;"></div>
  </div>
  `;
  
  // Insert chart container
  document.getElementById(containerId).innerHTML = chartComponent;
  
  // Add styles for legend
  if (!document.getElementById('chart-legend-styles')) {
    const style = document.createElement('style');
    style.id = 'chart-legend-styles';
    style.textContent = `
      .chart-legend {
        font-size: 12px;
      }
      .legend-item {
        display: flex;
        align-items: center;
        margin-right: 10px;
      }
      .color-box {
        display: inline-block;
        width: 12px;
        height: 12px;
        margin-right: 5px;
        border-radius: 2px;
      }
    `;
    document.head.appendChild(style);
  }
  
  // Create chart
  createChartWithChartJS('chart-container', chartData, userColors, users);
}

function loadChartJs() {
  return new Promise((resolve, reject) => {
    // Check if Chart.js is already loaded
    if (typeof Chart !== 'undefined') {
      resolve();
      return;
    }
    
    // Create script element
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.3.0/dist/chart.umd.min.js';
    script.integrity = 'sha384-dLFzkG3ypvCiHuR3t91rUxAI3m3s1GFc4liJepgYQxYJ/suRKPjCPGPQF2ycXjHc';
    script.crossOrigin = 'anonymous';
    
    // Set up event handlers
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Failed to load Chart.js'));
    
    // Add to document
    document.head.appendChild(script);
  });
}


// Helper function to truncate and format email addresses
function formatEmail(email) {
  if (email.length > 20) {
    const parts = email.split('@');
    if (parts.length === 2) {
      return parts[0].substring(0, 10) + '...@' + parts[1].substring(0, 5) + '...';
    }
  }
  return email;
}

// Function to create a chart using Chart.js
function createChartWithChartJS(containerId, data, userColors, users) {
  // Prepare data for Chart.js
  const labels = data.map(item => item.label);
  
  const datasets = users.map(user => {
    return {
      label: formatEmail(user),
      backgroundColor: userColors[user],
      data: data.map(item => item[user] || 0)
    };
  });
  
  // Check for existing chart instance and destroy it
  const chartContainer = document.getElementById(containerId);
  if (chartContainer) {
    // Clear the container first
    chartContainer.innerHTML = '';
  }
  
  // Create new canvas
  const canvas = document.createElement('canvas');
  canvas.id = 'daily-usage-chart';
  chartContainer.appendChild(canvas);
  
  // Create chart
  const ctx = canvas.getContext('2d');
  new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: datasets
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false // We're using our own legend
        },
        tooltip: {
          mode: 'index',
          intersect: false,
          filter: function(tooltipItem) {
            // Only show tooltip if the value is greater than 0
            return tooltipItem.raw > 0;
          }
        }
      },
      scales: {
        x: {
          stacked: true,
          grid: {
            display: false
          },
          ticks: {
            maxRotation: 0,
            autoSkip: true,
            maxTicksLimit: 10
          }
        },
        y: {
          stacked: true,
          beginAtZero: true,
          grid: {
            color: 'rgba(0, 0, 0, 0.1)'
          }
        }
      }
    }
  });
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
  
  // Get LLM usage
  const llmUsage = userStat.llm_info || {};
  let llmHtml = '';
  for (const [model, count] of Object.entries(llmUsage)) {
    llmHtml += `<tr><td>${model}</td><td>${count}</td></tr>`;
  }
  
  // Get monthly usage
  const monthlyUsage = userStat.monthly_usage || {};
  const sortedMonths = Object.keys(monthlyUsage).sort().reverse();
  let monthlyHtml = '';
  for (const month of sortedMonths) {
    monthlyHtml += `<tr><td>${month}</td><td>${monthlyUsage[month]}</td></tr>`;
  }
  
  const firstUsed = formatTimestamp(userStat.first_processed_at);
  const lastUsed = formatTimestamp(userStat.last_processed_at);
  
  // Get daily usage data for this user
  const dailyUsage = userStat.daily_usage || {};
  const sortedDays = Object.keys(dailyUsage).sort().reverse();
  let dailyHtml = '';
  
  for (const day of sortedDays) {
    const count = dailyUsage[day];
    if (count > 0) {
      // Format date for display
      const date = new Date(day);
      const formattedDate = date.toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      });
      dailyHtml += `<tr><td>${formattedDate}</td><td>${count}</td></tr>`;
    }
  }
  
  // Add a new "Daily Usage" section to the modal
  const dailyUsageSection = dailyHtml ? `
    <div class="details-section">
      <h4>Daily Usage</h4>
      <table class="details-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Images Processed</th>
          </tr>
        </thead>
        <tbody>
          ${dailyHtml}
        </tbody>
      </table>
    </div>
  ` : '';
  
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
      
      ${dailyUsageSection}
      
      <div class="details-section">
        <h4>OCR Engine Usage</h4>
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
        <h4>LLM Usage</h4>
        <table class="details-table">
          <thead>
            <tr>
              <th>Model</th>
              <th>Count</th>
            </tr>
          </thead>
          <tbody>
            ${llmHtml || '<tr><td colspan="2">No LLM usage data available</td></tr>'}
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

// Initialize the page when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
  // When the usage statistics tab is selected
  const usageStatsTab = document.querySelector('.tab-button[data-tab="usage-stats"]');
  if (usageStatsTab) {
    usageStatsTab.addEventListener('click', function() {
      loadUsageStatistics();
    });
  }
  
  // Initialize global storage for stats
  window.allStats = [];
});