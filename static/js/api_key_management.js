// Initialize Firebase
firebase.initializeApp(firebaseConfig);

// Helper function for formatting Firestore timestamps
function formatFirestoreDate(firestoreTimestamp) {
  if (!firestoreTimestamp) return 'N/A';
  
  // Check if it's a Firestore timestamp object
  if (firestoreTimestamp._seconds) {
    // Convert seconds to milliseconds and create a JavaScript Date
    return new Date(firestoreTimestamp._seconds * 1000).toLocaleDateString();
  } 
  // If it's already a JavaScript Date object
  else if (firestoreTimestamp instanceof Date) {
    return firestoreTimestamp.toLocaleDateString();
  }
  // If it's an ISO string
  else if (typeof firestoreTimestamp === 'string') {
    return new Date(firestoreTimestamp).toLocaleDateString();
  }
  
  return 'Invalid Date';
}

// Initialize the page
function initPage() {
  console.log("Initializing API key management page");
  // Check if user is authenticated
  firebase.auth().onAuthStateChanged(function(user) {
    if (user) {
      // User is signed in, display their email
      document.getElementById('user-email').textContent = user.email;
      console.log("User authenticated:", user.email);
      
      // Check if user has API key permission
      checkApiKeyPermission(user)
        .then(hasApiKeyAccess => {
          console.log("API key permission check result:", hasApiKeyAccess);
          if (hasApiKeyAccess) {
            // User has permission, initialize API key management functionality
            initializeCreateKeyListeners();
            loadApiKeys(user);
          } else {
            // Show no permission message
            document.getElementById('no-permission').style.display = 'block';
            document.getElementById('create-key-btn').style.display = 'none';
            document.getElementById('keys-container').style.display = 'none';
          }
        })
        .catch(error => {
          console.error('Error checking API key permission:', error);
          document.getElementById('error-message').textContent = 'Error: ' + error.message;
          document.getElementById('error-message').style.display = 'block';
        });
      
      // Attach logout button handler
      document.getElementById('logout-btn').addEventListener('click', () => {
        firebase.auth().signOut().then(() => {
          window.location.href = '/login';
        });
      });
    } else {
      // Not signed in, redirect to login page
      window.location.href = '/login';
    }
  });
}

// Set up all event listeners for the key management interface
function initializeCreateKeyListeners() {
  console.log("Setting up event listeners for API key management");
  
  // Create Key button
  const createKeyBtn = document.getElementById('create-key-btn');
  if (createKeyBtn) {
    createKeyBtn.addEventListener('click', () => {
      document.getElementById('create-key-modal').style.display = 'block';
    });
  }
  
  // Close buttons
  document.querySelectorAll('.close').forEach(btn => {
    btn.addEventListener('click', () => {
      document.getElementById('create-key-modal').style.display = 'none';
      document.getElementById('display-key-modal').style.display = 'none';
    });
  });
  
  // Close modals when clicking outside
  window.addEventListener('click', (event) => {
    if (event.target === document.getElementById('create-key-modal')) {
      document.getElementById('create-key-modal').style.display = 'none';
    }
    if (event.target === document.getElementById('display-key-modal')) {
      document.getElementById('display-key-modal').style.display = 'none';
    }
  });
  
  // Create key form submission
  const createKeyForm = document.getElementById('create-key-form');
  if (createKeyForm) {
    createKeyForm.addEventListener('submit', (e) => {
      e.preventDefault();
      createApiKey();
    });
  }
  
  // Copy key button
  const copyKeyBtn = document.getElementById('copy-key-btn');
  if (copyKeyBtn) {
    copyKeyBtn.addEventListener('click', () => {
      const keyText = document.getElementById('api-key-display').textContent;
      navigator.clipboard.writeText(keyText)
        .then(() => {
          document.getElementById('copy-success').style.display = 'block';
          setTimeout(() => {
            document.getElementById('copy-success').style.display = 'none';
          }, 3000);
        })
        .catch(err => {
          console.error('Could not copy text: ', err);
        });
    });
  }
}

// Improved checkApiKeyPermission function with better error handling
async function checkApiKeyPermission(user) {
  try {
    // Get ID token for authentication
    const idToken = await user.getIdToken();
    
    // Check permission
    const response = await fetch('/check-api-key-permission', {
      headers: {
        'Authorization': `Bearer ${idToken}`
      }
    });
    
    // Log the raw response for debugging
    console.log("API key permission check response status:", response.status);
    
    if (!response.ok) {
      const errorText = await response.text();
      console.error("API key permission check error:", errorText);
      try {
        const errorData = JSON.parse(errorText);
        throw new Error(errorData.error || `Server returned ${response.status}`);
      } catch (jsonError) {
        throw new Error(`Server returned ${response.status}: ${errorText}`);
      }
    }
    
    const data = await response.json();
    console.log("API key permission data:", data);
    
    // Be explicit about checking the value to avoid falsy values
    return data.has_api_key_permission === true;
  } catch (error) {
    console.error('Error checking API key permission:', error);
    return false;
  }
}

// Modified createApiKey function with better error handling
async function createApiKey() {
  const formError = document.getElementById('form-error');
  try {
    formError.style.display = 'none';
    
    // Get form values
    const name = document.getElementById('key-name').value;
    const description = document.getElementById('key-description').value;
    const expiryDays = document.getElementById('key-expiry').value;
    
    if (!name) {
      throw new Error('Please provide a name for your API key');
    }
    
    // Get current user
    const user = firebase.auth().currentUser;
    if (!user) {
      throw new Error('You must be logged in to create an API key');
    }
    
    // Get ID token for authentication
    const idToken = await user.getIdToken();
    
    console.log("Creating API key...");
    
    // Create the API key
    const response = await fetch('/api-keys/create', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${idToken}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        name: name,
        description: description,
        expires_days: parseInt(expiryDays, 10)
      })
    });
    
    if (!response.ok) {
      const errorText = await response.text();
      console.error("API key creation error response:", errorText);
      try {
        const errorData = JSON.parse(errorText);
        if (response.status === 403 && errorData.code === 'no_api_key_permission') {
          throw new Error('You do not have permission to create API keys. Please contact an administrator to request this access.');
        } else {
          throw new Error(errorData.error || `Server returned ${response.status}`);
        }
      } catch (jsonError) {
        throw new Error(`Server error: ${errorText}`);
      }
    }
    
    const data = await response.json();
    console.log("API key created successfully");
    
    if (data.status === 'success') {
      // Close create modal
      document.getElementById('create-key-modal').style.display = 'none';
      
      // Update usage example with the new key
      const usageExample = document.getElementById('usage-example');
      usageExample.textContent = usageExample.textContent.replace(/YOUR_API_KEY/g, data.api_key);
      
      // Display the API key
      document.getElementById('api-key-display').textContent = data.api_key;
      document.getElementById('display-key-modal').style.display = 'block';
      
      // Reset form
      document.getElementById('create-key-form').reset();
      
      // Reload the API keys list
      loadApiKeys(user);
    } else {
      throw new Error(data.error || 'Failed to create API key');
    }
  } catch (error) {
    console.error('Error creating API key:', error);
    formError.textContent = error.message;
    formError.style.display = 'block';
  }
}

// Load API keys
async function loadApiKeys(user) {
  const keysContainer = document.getElementById('keys-container');
  const loadingElem = document.getElementById('loading');
  const errorMessageElem = document.getElementById('error-message');
  const noKeysElem = document.getElementById('no-keys');
  const keysTableElem = document.getElementById('keys-table');
  const keysListElem = document.getElementById('keys-list');
  
  try {
    // Get ID token for authentication
    const idToken = await user.getIdToken();
    
    // Fetch API keys from server
    const response = await fetch('/api-keys', {
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
        // No keys found
        noKeysElem.style.display = 'block';
        keysTableElem.style.display = 'none';
      } else {
        // Display keys
        noKeysElem.style.display = 'none';
        keysTableElem.style.display = 'table';
        
        // Clear existing list
        keysListElem.innerHTML = '';
        
        // Add each key to the table
        data.api_keys.forEach(key => {
          const row = document.createElement('tr');
          
          // Format dates using the helper function
          const createdDate = formatFirestoreDate(key.created_at);
          const expiresDate = formatFirestoreDate(key.expires_at);
          
          // Status badge
          const statusBadge = key.active 
            ? '<span class="badge-active">Active</span>'
            : '<span class="badge-inactive">Inactive</span>';
          
          row.innerHTML = `
            <td>${key.name || 'Unnamed Key'}</td>
            <td>${createdDate}</td>
            <td>${expiresDate}</td>
            <td>${statusBadge}</td>
            <td>
              ${key.active ? `<button class="btn-revoke" data-key-id="${key.key_id}">Revoke</button>` : ''}
            </td>
          `;
          
          keysListElem.appendChild(row);
        });
        
        // Add event listeners to revoke buttons
        document.querySelectorAll('.btn-revoke').forEach(btn => {
          btn.addEventListener('click', (e) => {
            const keyId = e.target.getAttribute('data-key-id');
            if (confirm('Are you sure you want to revoke this API key? This action cannot be undone.')) {
              revokeApiKey(keyId);
            }
          });
        });
      }
    } else {
      throw new Error(data.error || 'Failed to load API keys');
    }
  } catch (error) {
    console.error('Error loading API keys:', error);
    loadingElem.style.display = 'none';
    errorMessageElem.textContent = `Error: ${error.message}`;
    errorMessageElem.style.display = 'block';
  }
}

// Revoke API key
async function revokeApiKey(keyId) {
  try {
    // Get current user
    const user = firebase.auth().currentUser;
    if (!user) {
      throw new Error('You must be logged in to revoke an API key');
    }
    
    // Get ID token for authentication
    const idToken = await user.getIdToken();
    
    // Revoke the API key
    const response = await fetch(`/api-keys/${keyId}/revoke`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${idToken}`
      }
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.error || `Server returned ${response.status}`);
    }
    
    const data = await response.json();
    
    if (data.status === 'success') {
      // Reload the API keys list
      loadApiKeys(user);
    } else {
      throw new Error(data.error || 'Failed to revoke API key');
    }
  } catch (error) {
    console.error('Error revoking API key:', error);
    alert(`Error: ${error.message}`);
  }
}

// Start the page initialization when the DOM is ready
document.addEventListener('DOMContentLoaded', function() {
  console.log("DOM content loaded, initializing page");
  initPage();
});