let currentVertexProjectId = null;

function formatVertexProjectTimestamp(timestamp) {
  if (!timestamp) return 'N/A';
  if (timestamp._seconds) {
    return new Date(timestamp._seconds * 1000).toLocaleString();
  }
  if (timestamp._formatted) {
    return timestamp._formatted;
  }
  if (timestamp instanceof Date) {
    return timestamp.toLocaleString();
  }
  if (typeof timestamp === 'string') {
    const date = new Date(timestamp);
    if (!Number.isNaN(date.getTime())) {
      return date.toLocaleString();
    }
    return timestamp;
  }
  return 'N/A';
}

function loadVertexProjectsAdmin() {
  document.getElementById('vertex-projects-loading').style.display = 'block';
  document.getElementById('vertex-projects-table').style.display = 'none';

  firebase.auth().currentUser.getIdToken(true).then(function(idToken) {
    fetch('/admin/vertex-projects', {
      headers: {
        'Authorization': 'Bearer ' + idToken
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.status === 'success') {
        window.allVertexProjects = data.vertex_projects;
        window.filteredVertexProjects = [...window.allVertexProjects];
        renderVertexProjectsPage(1);
      } else {
        console.error('Failed to load Vertex projects:', data.error);
        document.getElementById('vertex-projects-loading').textContent = 'Error loading Vertex projects: ' + data.error;
      }
    })
    .catch(error => {
      console.error('Error loading Vertex projects:', error);
      document.getElementById('vertex-projects-loading').textContent = 'Error loading Vertex projects. Please try again.';
    });
  }).catch(function(error) {
    console.error('Error getting auth token:', error);
    document.getElementById('vertex-projects-loading').textContent = 'Authentication error. Please try logging in again.';
  });
}

function renderVertexProjectsPage(page) {
  window.currentVertexProjectsPage = page;

  const start = (page - 1) * window.itemsPerPage;
  const end = start + window.itemsPerPage;
  const pageItems = window.filteredVertexProjects.slice(start, end);

  const tableBody = document.getElementById('vertex-projects-list');
  tableBody.innerHTML = '';

  if (pageItems.length === 0) {
    document.getElementById('vertex-projects-loading').style.display = 'block';
    document.getElementById('vertex-projects-loading').textContent = 'No Vertex project bindings found matching your search.';
    document.getElementById('vertex-projects-table').style.display = 'none';
    document.getElementById('vertex-projects-pagination').innerHTML = '';
    return;
  }

  document.getElementById('vertex-projects-loading').style.display = 'none';
  document.getElementById('vertex-projects-table').style.display = 'table';

  pageItems.forEach(project => {
    const row = document.createElement('tr');
    const isActive = project.active === true;

    const ownerCell = document.createElement('td');
    ownerCell.textContent = project.owner_email || 'Unknown';
    row.appendChild(ownerCell);

    const projectIdCell = document.createElement('td');
    const projectIdCode = document.createElement('code');
    projectIdCode.textContent = project.project_id || '';
    projectIdCell.appendChild(projectIdCode);
    row.appendChild(projectIdCell);

    const nicknameCell = document.createElement('td');
    nicknameCell.textContent = project.nickname || '-';
    row.appendChild(nicknameCell);

    const linkedCell = document.createElement('td');
    linkedCell.textContent = formatVertexProjectTimestamp(project.created_at);
    row.appendChild(linkedCell);

    const statusCell = document.createElement('td');
    const statusBadge = document.createElement('span');
    statusBadge.className = 'badge ' + (isActive ? 'badge-approved' : 'badge-rejected');
    statusBadge.textContent = isActive ? 'Active' : 'Revoked';
    statusCell.appendChild(statusBadge);
    row.appendChild(statusCell);

    const actionsCell = document.createElement('td');
    if (isActive) {
      const revokeBtn = document.createElement('button');
      revokeBtn.className = 'btn-danger vertex-revoke-btn';
      revokeBtn.textContent = 'Revoke';
      revokeBtn.addEventListener('click', () => showRevokeProjectModal(project));
      actionsCell.appendChild(revokeBtn);
    } else {
      const revokedSpan = document.createElement('span');
      revokedSpan.className = 'text-muted';
      revokedSpan.textContent = 'Revoked';
      actionsCell.appendChild(revokedSpan);
    }
    row.appendChild(actionsCell);

    tableBody.appendChild(row);
  });

  window.generatePagination(
    window.filteredVertexProjects.length,
    page,
    'vertex-projects-pagination',
    renderVertexProjectsPage
  );
}

function showRevokeProjectModal(project) {
  currentVertexProjectId = project.project_id;
  document.getElementById('project-owner-email').textContent = project.owner_email || 'Unknown';
  document.getElementById('project-id-display').textContent = project.project_id || '';
  document.getElementById('project-nickname-display').textContent = project.nickname || '-';
  document.getElementById('project-created-display').textContent = formatVertexProjectTimestamp(project.created_at);
  document.getElementById('revoke-project-error').style.display = 'none';
  document.getElementById('revoke-project-success').style.display = 'none';
  document.getElementById('revoke-project-modal').style.display = 'block';
}

function revokeVertexProjectAdmin() {
  if (!currentVertexProjectId) return;

  const errorDiv = document.getElementById('revoke-project-error');
  const successDiv = document.getElementById('revoke-project-success');
  errorDiv.style.display = 'none';
  successDiv.style.display = 'none';

  firebase.auth().currentUser.getIdToken(true).then(function(idToken) {
    fetch(`/admin/vertex-projects/${encodeURIComponent(currentVertexProjectId)}/revoke`, {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + idToken,
        'Content-Type': 'application/json'
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.status === 'success') {
        successDiv.textContent = 'Vertex project revoked successfully!';
        successDiv.style.display = 'block';
        setTimeout(() => {
          document.getElementById('revoke-project-modal').style.display = 'none';
          loadVertexProjectsAdmin();
        }, 1200);
      } else {
        errorDiv.textContent = 'Error: ' + (data.error || 'Failed to revoke Vertex project');
        errorDiv.style.display = 'block';
      }
    })
    .catch(error => {
      console.error('Error revoking Vertex project:', error);
      errorDiv.textContent = 'Error revoking Vertex project. Please try again.';
      errorDiv.style.display = 'block';
    });
  }).catch(function(error) {
    console.error('Error getting auth token:', error);
    errorDiv.textContent = 'Authentication error. Please try logging in again.';
    errorDiv.style.display = 'block';
  });
}

function showAdminLinkProjectModal() {
  document.getElementById('admin-link-project-error').style.display = 'none';
  document.getElementById('admin-link-project-success').style.display = 'none';
  document.getElementById('admin-link-project-modal').style.display = 'block';
}

function adminLinkVertexProject() {
  const ownerEmail = document.getElementById('admin-project-owner-email').value.trim();
  const projectId = document.getElementById('admin-project-id').value.trim();
  const nickname = document.getElementById('admin-project-nickname').value.trim();
  const errorDiv = document.getElementById('admin-link-project-error');
  const successDiv = document.getElementById('admin-link-project-success');

  errorDiv.style.display = 'none';
  successDiv.style.display = 'none';

  firebase.auth().currentUser.getIdToken(true).then(function(idToken) {
    fetch('/admin/vertex-projects', {
      method: 'POST',
      headers: {
        'Authorization': 'Bearer ' + idToken,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        owner_email: ownerEmail,
        project_id: projectId,
        nickname: nickname
      })
    })
    .then(async response => {
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || `Server returned ${response.status}`);
      }
      return data;
    })
    .then(data => {
      successDiv.textContent = data.message || 'Vertex project linked successfully.';
      successDiv.style.display = 'block';
      document.getElementById('admin-project-owner-email').value = '';
      document.getElementById('admin-project-id').value = '';
      document.getElementById('admin-project-nickname').value = '';
      loadVertexProjectsAdmin();
      setTimeout(() => {
        document.getElementById('admin-link-project-modal').style.display = 'none';
        successDiv.style.display = 'none';
      }, 1200);
    })
    .catch(error => {
      console.error('Error linking Vertex project as admin:', error);
      errorDiv.textContent = error.message;
      errorDiv.style.display = 'block';
    });
  }).catch(function(error) {
    console.error('Error getting auth token:', error);
    errorDiv.textContent = 'Authentication error. Please try logging in again.';
    errorDiv.style.display = 'block';
  });
}

document.addEventListener('DOMContentLoaded', function() {
  const confirmRevokeProjectBtn = document.getElementById('confirm-revoke-project-btn');
  if (confirmRevokeProjectBtn) {
    confirmRevokeProjectBtn.addEventListener('click', revokeVertexProjectAdmin);
  }

  const cancelRevokeProjectBtn = document.getElementById('cancel-revoke-project-btn');
  if (cancelRevokeProjectBtn) {
    cancelRevokeProjectBtn.addEventListener('click', function() {
      document.getElementById('revoke-project-modal').style.display = 'none';
    });
  }

  const adminLinkProjectBtn = document.getElementById('admin-link-project-btn');
  if (adminLinkProjectBtn) {
    adminLinkProjectBtn.addEventListener('click', showAdminLinkProjectModal);
  }

  const confirmAdminLinkProjectBtn = document.getElementById('confirm-admin-link-project-btn');
  if (confirmAdminLinkProjectBtn) {
    confirmAdminLinkProjectBtn.addEventListener('click', adminLinkVertexProject);
  }

  const cancelAdminLinkProjectBtn = document.getElementById('cancel-admin-link-project-btn');
  if (cancelAdminLinkProjectBtn) {
    cancelAdminLinkProjectBtn.addEventListener('click', function() {
      document.getElementById('admin-link-project-modal').style.display = 'none';
    });
  }
});

window.loadVertexProjectsAdmin = loadVertexProjectsAdmin;
window.renderVertexProjectsPage = renderVertexProjectsPage;
window.showRevokeProjectModal = showRevokeProjectModal;
