// New Users tab — user acquisition chart
// Uses data from /admin/applications (user_applications collection)

let newUsersChart = null;
let newUsersData = null;
let currentBin = 'week';
let currentTimeframe = '6m';

async function loadNewUsers() {
  const container = document.getElementById('new-users-container');
  const loading = document.getElementById('new-users-loading');

  try {
    if (!newUsersData) {
      const idToken = await firebase.auth().currentUser.getIdToken();
      const response = await fetch('/admin/applications', {
        headers: { 'Authorization': `Bearer ${idToken}` }
      });
      if (!response.ok) throw new Error(`Server returned ${response.status}`);
      const data = await response.json();
      if (data.status !== 'success') throw new Error(data.error || 'Failed to load');
      newUsersData = data.applications;
    }

    loading.style.display = 'none';
    document.getElementById('new-users-controls').style.display = 'flex';
    document.getElementById('new-users-chart-wrap').style.display = 'block';
    renderNewUsersChart();
  } catch (error) {
    console.error('Error loading new users:', error);
    loading.style.display = 'none';
    container.innerHTML = `<p class="error">Error: ${error.message}</p>`;
  }
}

function renderNewUsersChart() {
  if (!newUsersData) return;

  // Parse signup dates from user_applications
  const signupDates = [];
  newUsersData.forEach(app => {
    let ts = null;
    const ca = app.created_at;
    if (ca) {
      if (ca._seconds) ts = ca._seconds * 1000;
      else if (ca.seconds) ts = ca.seconds * 1000;
      else if (typeof ca === 'string') ts = new Date(ca).getTime();
    }
    if (ts && !isNaN(ts)) signupDates.push(new Date(ts));
  });

  signupDates.sort((a, b) => a - b);
  if (signupDates.length === 0) {
    document.getElementById('new-users-chart-wrap').innerHTML =
      '<p style="color:#888;">No user signup data available.</p>';
    return;
  }

  // Determine time range
  const now = new Date();
  let rangeStart;
  switch (currentTimeframe) {
    case '30d': rangeStart = new Date(now); rangeStart.setDate(now.getDate() - 30); break;
    case '90d': rangeStart = new Date(now); rangeStart.setDate(now.getDate() - 90); break;
    case '6m':  rangeStart = new Date(now); rangeStart.setMonth(now.getMonth() - 6); break;
    case '1y':  rangeStart = new Date(now); rangeStart.setFullYear(now.getFullYear() - 1); break;
    case 'all': rangeStart = signupDates[0]; break;
    default:    rangeStart = new Date(now); rangeStart.setMonth(now.getMonth() - 6);
  }

  // Build bins
  const bins = buildBins(rangeStart, now, currentBin);
  const newCounts = new Array(bins.length).fill(0);
  const cumulativeCounts = new Array(bins.length).fill(0);

  // Count users before rangeStart for cumulative baseline
  let baseline = 0;
  signupDates.forEach(d => { if (d < rangeStart) baseline++; });

  // Assign signups to bins
  signupDates.forEach(d => {
    if (d < rangeStart) return;
    for (let i = bins.length - 1; i >= 0; i--) {
      if (d >= bins[i].start) {
        newCounts[i]++;
        break;
      }
    }
  });

  // Build cumulative
  let running = baseline;
  for (let i = 0; i < bins.length; i++) {
    running += newCounts[i];
    cumulativeCounts[i] = running;
  }

  const labels = bins.map(b => b.label);

  // Destroy previous chart
  if (newUsersChart) {
    newUsersChart.destroy();
    newUsersChart = null;
  }

  const canvas = document.getElementById('newUsersCanvas');
  const ctx = canvas.getContext('2d');

  newUsersChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'New Users',
          data: newCounts,
          backgroundColor: '#4285f4',
          borderWidth: 0,
          yAxisID: 'y1',
          order: 2
        },
        {
          label: 'Total Users',
          data: cumulativeCounts,
          type: 'line',
          borderColor: '#34a853',
          backgroundColor: 'rgba(52, 168, 83, 0.1)',
          fill: true,
          tension: 0.3,
          pointRadius: 2,
          borderWidth: 2,
          yAxisID: 'y',
          order: 1
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, position: 'top' },
        tooltip: { mode: 'index', intersect: false }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 15 }
        },
        y: {
          type: 'linear',
          position: 'left',
          title: { display: true, text: 'Total Users' },
          beginAtZero: true,
          grid: { color: 'rgba(0,0,0,0.08)' }
        },
        y1: {
          type: 'linear',
          position: 'right',
          title: { display: true, text: 'New Users' },
          beginAtZero: true,
          grid: { drawOnChartArea: false }
        }
      }
    }
  });
}

function buildBins(start, end, binType) {
  const bins = [];
  const cur = new Date(start);

  // Align to bin boundary
  switch (binType) {
    case 'day':
      cur.setHours(0, 0, 0, 0);
      break;
    case 'week':
      cur.setHours(0, 0, 0, 0);
      cur.setDate(cur.getDate() - cur.getDay()); // Sunday
      break;
    case 'month':
      cur.setDate(1); cur.setHours(0, 0, 0, 0);
      break;
    case 'year':
      cur.setMonth(0, 1); cur.setHours(0, 0, 0, 0);
      break;
  }

  while (cur <= end) {
    const binStart = new Date(cur);
    let label;

    switch (binType) {
      case 'day':
        label = cur.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
        cur.setDate(cur.getDate() + 1);
        break;
      case 'week':
        label = 'W' + getWeekLabel(cur);
        cur.setDate(cur.getDate() + 7);
        break;
      case 'month':
        label = cur.toLocaleDateString(undefined, { month: 'short', year: '2-digit' });
        cur.setMonth(cur.getMonth() + 1);
        break;
      case 'year':
        label = cur.getFullYear().toString();
        cur.setFullYear(cur.getFullYear() + 1);
        break;
    }

    bins.push({ start: binStart, label: label });
  }

  return bins;
}

function getWeekLabel(date) {
  const d = new Date(date);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

// Event listeners for controls
function setupNewUsersControls() {
  document.querySelectorAll('.nu-bin-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.nu-bin-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentBin = btn.dataset.bin;
      renderNewUsersChart();
    });
  });

  document.querySelectorAll('.nu-tf-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.nu-tf-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentTimeframe = btn.dataset.tf;
      renderNewUsersChart();
    });
  });
}

// Initialize when DOM ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setupNewUsersControls);
} else {
  setupNewUsersControls();
}

// Expose globally
window.loadNewUsers = loadNewUsers;
