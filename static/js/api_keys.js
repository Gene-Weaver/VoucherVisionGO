// Load admins
async function loadAdmins(user) {
    try {
      // Show loading indicator
      document.getElementById('admins-loading').style.display = 'block';
      document.getElementById('admins-table').style.display = 'none';
      
      // Get ID token
      const idToken = await user.getIdToken(true);
      
      // Fetch admins
      const response = await fetch('/admin/list-admins', {
        headers: {
          'Authorization': `Bearer ${idToken}`
        }
      });
      
      if (!response.ok) {
        throw new Error(`Server returned ${response.status}: ${response.statusText}`);
      }
      
      const data = await response.json();
      
      if (data.status === 'success') {
        // Hide loading, show table
        document.getElementById('admins-loading').style.display = 'none';
        document.getElementById('admins-table').style.display = 'table';
        
        // Populate table
        const adminsListElem = document.getElementById('admins-list');
        adminsListElem.innerHTML = '';
        
        data.admins.forEach(admin => {
          // Format date
          const addedDate = admin.added_at ? 
            new Date(admin.added_at._seconds * 1000).toLocaleDateString() : 'N/A';
          
          const row = document.createElement('tr');
          row.innerHTML = `
            <td>${admin.email}</td>
            <td>${admin.added_by || 'N/A'}</td>
            <td>${addedDate}</td>
            <td>
              ${admin.email !== user.email ? 
                `<button class="btn-danger remove-admin-btn" data-email="${admin.email}">Remove</button>` : 
                '<em>Current User</em>'}
            </td>
          `;
          
          adminsListElem.appendChild(row);
        });
        
        // Setup remove buttons
        document.querySelectorAll('.remove-admin-btn').forEach(btn => {
          btn.addEventListener('click', () => {
            const email = btn.getAttribute('data-email');
            if (confirm(`Are you sure you want to remove ${email} as an admin?`)) {
              removeAdmin(email);
            }
          });
        });
      } else {
        throw new Error(data.error || 'Failed to load admins');
      }
    } catch (error) {
      console.error('Error loading admins:', error);
      document.getElementById('admins-loading').textContent = 
        'Error loading admins: ' + error.message;
    }
  }
  
  // Add admin
  async function addAdmin() {
    const emailElem = document.getElementById('admin-email');
    const errorElem = document.getElementById('add-admin-error');
    const successElem = document.getElementById('add-admin-success');
    const email = emailElem.value.trim();
    
    // Clear status messages
    errorElem.style.display = 'none';
    successElem.style.display = 'none';
    
    if (!email) {
      errorElem.textContent = 'Please enter an email address';
      errorElem.style.display = 'block';
      return;
    }
    
    try {
      const user = firebase.auth().currentUser;
      if (!user) throw new Error('Not authenticated');
      
      // Get ID token
      const idToken = await user.getIdToken(true);
      
      // Send add admin request
      const response = await fetch('/admin/add-admin', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${idToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          email: email
        })
      });
      
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || `Server returned ${response.status}`);
      }
      
      const data = await response.json();
      
      if (data.status === 'success') {
        // Show success message
        successElem.textContent = `${email} has been added as an admin`;
        successElem.style.display = 'block';
        
        // Clear input
        emailElem.value = '';
        
        // Reload admins list
        loadAdmins(user);
      } else {
        throw new Error(data.error || 'Failed to add admin');
      }
    } catch (error) {
      console.error('Error adding admin:', error);
      errorElem.textContent = 'Error: ' + error.message;
      errorElem.style.display = 'block';
    }
  }
  
  // Remove admin
  async function removeAdmin(email) {
    try {
      const user = firebase.auth().currentUser;
      if (!user) throw new Error('Not authenticated');
      
      // Get ID token
      const idToken = await user.getIdToken(true);
      
      // Send remove admin request
      const response = await fetch('/admin/remove-admin', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${idToken}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          email: email
        })
      });
      
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || `Server returned ${response.status}`);
      }
      
      const data = await response.json();
      
      if (data.status === 'success') {
        // Reload admins list
        loadAdmins(user);
      } else {
        throw new Error(data.error || 'Failed to remove admin');
      }
    } catch (error) {
      console.error('Error removing admin:', error);
      alert('Error: ' + error.message);
    }
  }