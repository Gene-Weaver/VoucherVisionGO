// Add token as hidden input field
const TOKEN_REFRESH_INTERVAL = 2700000;
let tokenRefreshTimer;

// Initialize the page
function initPage() {
  const tokenElement = document.getElementById('token');
  const userEmailElement = document.getElementById('user-email');
  const errorElement = document.getElementById('error-message');
  const successElement = document.getElementById('success-message');
  const userInfoDiv = document.querySelector('.user-info div');
  
  // Initialize Firebase
  firebase.initializeApp(firebaseConfig);
  
  // Check if user is authenticated
  firebase.auth().onAuthStateChanged(function(user) {
    if (user) {
      // User is signed in, display their email
      userEmailElement.textContent = user.email;
      
      // First, check if user is an admin
      checkAdminStatus(user)
        .then(isAdmin => {
          if (isAdmin) {
            // Add admin dashboard button
            console.log("User is an admin, adding admin button");
            const adminButton = document.createElement('button');
            adminButton.className = 'btn-admin';
            adminButton.textContent = 'Admin Dashboard';
            adminButton.onclick = async function() {
              try {
                // Get fresh token
                const freshToken = await user.getIdToken(true);
                
                // Create a form to submit the token via POST
                const form = document.createElement('form');
                form.method = 'POST';
                form.action = '/admin';
                form.style.display = 'none';
                
                // Add the token as a hidden input
                const tokenInput = document.createElement('input');
                tokenInput.type = 'hidden';
                tokenInput.name = 'auth_token';
                tokenInput.value = freshToken;
                form.appendChild(tokenInput);
                
                // Add the form to the body and submit it
                document.body.appendChild(form);
                form.submit();
              } catch (error) {
                console.error('Error accessing admin dashboard:', error);
                alert('Authentication error. Please try logging in again.');
              }
            };
            userInfoDiv.appendChild(adminButton);
          }
          
          // Then check if user is approved
          return checkUserApproval(user);
        })
        .then(isApproved => {
          if (isApproved) {
            // Check if user has API key permission and show API key management button if they do
            checkApiKeyPermission(user)
              .then(hasApiKeyAccess => {
                if (hasApiKeyAccess) {
                  console.log("User has API key permission, adding management button");
                  // Add API key management button
                  const apiKeysDiv = document.createElement('div');
                  apiKeysDiv.className = 'api-keys-access mt-4 p-3 bg-light rounded';
                  apiKeysDiv.innerHTML = `
                  <h4>API Key Management</h4>
                  <p>You have permission to create and manage API keys for programmatic access.</p>
                  <button id="manage-api-keys-btn" class="btn btn-primary">Manage API Keys</button>
                  `;
                  
                  // Find appropriate container to add the API keys div
                  const tokenContainer = document.querySelector('.token-container');
                  if (tokenContainer) {
                    tokenContainer.parentNode.insertBefore(apiKeysDiv, tokenContainer.nextSibling);
                  } else {
                    // If token container not found, add to the main container
                    const mainContainer = document.querySelector('.container');
                    if (mainContainer) {
                      mainContainer.appendChild(apiKeysDiv);
                    }
                  }
                  
                  // Add event listener *after* adding to DOM
                  console.log("Adding event listener to API keys button");
                  const manageApiKeysBtn = document.getElementById('manage-api-keys-btn');
                  if (manageApiKeysBtn) {
                    manageApiKeysBtn.addEventListener('click', async function() {
                      try {
                          console.log("API keys button clicked");
                          // Get fresh ID token
                          const freshToken = await user.getIdToken(true);
                          
                          // First log token info for debugging (just the length, not the token itself)
                          console.log("Token length:", freshToken.length);
                          
                          // Create form with the proper encoding type
                          const form = document.createElement('form');
                          form.method = 'POST';
                          form.action = '/api-key-management';
                          form.style.display = 'none';
                          form.enctype = 'application/x-www-form-urlencoded';
                          
                          // Add token as hidden input field
                          const tokenInput = document.createElement('input');
                          tokenInput.type = 'hidden';
                          tokenInput.name = 'auth_token';
                          tokenInput.value = freshToken;
                          form.appendChild(tokenInput);
                          
                          // Add the form to the document body
                          document.body.appendChild(form);
                          
                          // Log that we're submitting the form
                          console.log("Submitting form to /api-key-management with token length:", freshToken.length);
                          
                          // Submit the form
                          form.submit();
                      } catch (error) {
                          console.error('Error preparing API key management form:', error);
                          alert('Authentication error. Please try logging in again.');
                      }
                    });
                    console.log("Event listener added successfully");
                  } else {
                    console.error("Could not find manage-api-keys-btn element after adding to DOM");
                  }
                }
              })
              .catch(error => {
                console.error('Error checking API key permission:', error);
              });
            
            // Continue with token display
            updateTokenDisplay(user);
            setupTokenRefresh(user);
          } else {
            // Not approved, redirect to pending page
            window.location.href = '/pending-approval';
          }
        })
        .catch(error => {
          console.error('Error during initialization:', error);
          errorElement.textContent = 'Error: ' + error.message;
          errorElement.style.display = 'block';
        });
    } else {
      // Not signed in, redirect to login page
      window.location.href = '/login';
    }
  });
  
  // Copy token button
  document.getElementById('copy-token-btn').addEventListener('click', function() {
    const token = tokenElement.textContent;
    navigator.clipboard.writeText(token)
      .then(() => {
        successElement.textContent = 'Token copied to clipboard!';
        successElement.style.display = 'block';
        errorElement.style.display = 'none';
        setTimeout(() => {
          successElement.style.display = 'none';
        }, 3000);
      })
      .catch(err => {
        errorElement.textContent = 'Failed to copy: ' + err;
        errorElement.style.display = 'block';
        successElement.style.display = 'none';
      });
  });
  
  // Refresh token button
  document.getElementById('refresh-token-btn').addEventListener('click', function() {
    const currentUser = firebase.auth().currentUser;
    
    if (currentUser) {
      refreshToken(currentUser);
    } else {
      errorElement.textContent = 'Not signed in. Please log in again.';
      errorElement.style.display = 'block';
      successElement.style.display = 'none';
    }
  });
  
  // Logout button
  document.getElementById('logout-btn').addEventListener('click', function() {
    firebase.auth().signOut().then(function() {
      // Clear localStorage items
      localStorage.removeItem('auth_id_token');
      localStorage.removeItem('auth_refresh_token');
      localStorage.removeItem('auth_user_email');
      
      // Clear any refresh timers
      clearTimeout(tokenRefreshTimer);
      
      // Redirect to login page
      window.location.href = '/login';
    }).catch(function(error) {
      errorElement.textContent = 'Error signing out: ' + error.message;
      errorElement.style.display = 'block';
    });
  });
}

// Update token display
function updateTokenDisplay(user) {
  const tokenElement = document.getElementById('token');
  const errorElement = document.getElementById('error-message');
  
  user.getIdToken(true).then(function(idToken) {
    // Store the token in localStorage for persistence
    localStorage.setItem('auth_id_token', idToken);
    
    // Display the token
    tokenElement.textContent = idToken;
  }).catch(function(error) {
    errorElement.textContent = 'Error getting token: ' + error.message;
    errorElement.style.display = 'block';
    
    // Try to use cached token if available
    const cachedToken = localStorage.getItem('auth_id_token');
    if (cachedToken) {
      tokenElement.textContent = cachedToken;
    }
  });
}

// Set up automatic token refresh
function setupTokenRefresh(user) {
  // Clear any existing timer
  clearTimeout(tokenRefreshTimer);
  
  // Setup new timer to refresh the token
  tokenRefreshTimer = setTimeout(() => {
    refreshToken(user);
  }, TOKEN_REFRESH_INTERVAL);
}

// Refresh the token
function refreshToken(user) {
  const tokenElement = document.getElementById('token');
  const errorElement = document.getElementById('error-message');
  const successElement = document.getElementById('success-message');
  
  errorElement.style.display = 'none';
  successElement.style.display = 'none';
  
  // Force token refresh
  user.getIdToken(true).then(function(idToken) {
    // Update the token in localStorage
    localStorage.setItem('auth_id_token', idToken);
    
    // Update displayed token
    tokenElement.textContent = idToken;
    
    // Show success message
    successElement.textContent = 'Token refreshed successfully';
    successElement.style.display = 'block';
    
    // Set up the next refresh
    setupTokenRefresh(user);
  }).catch(function(error) {
    errorElement.textContent = 'Error refreshing token: ' + error.message;
    errorElement.style.display = 'block';
    
    // If error, try again in 1 minute
    tokenRefreshTimer = setTimeout(() => {
      const currentUser = firebase.auth().currentUser;
      if (currentUser) {
        refreshToken(currentUser);
      }
    }, 60000);
  });
}

// Check if user is an admin
async function checkAdminStatus(user) {
  try {
    console.log("Checking admin status for user:", user.email);
    const idToken = await user.getIdToken();
    
    const response = await fetch('/check-admin-status', {
      headers: {
        'Authorization': `Bearer ${idToken}`
      }
    });
    
    if (response.ok) {
      const data = await response.json();
      console.log("Admin status response:", data);
      return data.is_admin === true;
    }
    
    console.log("Admin check failed, response status:", response.status);
    return false;
  } catch (error) {
    console.error('Error checking admin status:', error);
    return false;
  }
}

// Function to check approval status
async function checkUserApproval(user) {
  try {
    const idToken = await user.getIdToken();
    const response = await fetch('/check-approval-status', {
      headers: {
        'Authorization': `Bearer ${idToken}`
      }
    });
    
    if (response.ok) {
      const data = await response.json();
      if (data.status === 'approved') {
        return true;
      } else if (data.status === 'pending') {
        window.location.href = '/pending-approval';
        return false;
      } else if (data.status === 'rejected') {
        window.location.href = '/application-rejected';
        return false;
      }
    }
    return false;
  } catch (error) {
    console.error('Error checking approval status:', error);
    return false;
  }
}

// Function to check API key permission
async function checkApiKeyPermission(user) {
  try {
    console.log("Checking API key permission for user:", user.email);
    const idToken = await user.getIdToken();
    const response = await fetch('/check-api-key-permission', {
      headers: {
        'Authorization': `Bearer ${idToken}`
      }
    });
    
    if (response.ok) {
      const data = await response.json();
      console.log("API key permission response:", data);
      return data.has_api_key_permission === true;
    }
    console.log("API key permission check failed, response status:", response.status);
    return false;
  } catch (error) {
    console.error('Error checking API key permission:', error);
    return false;
  }
}

// Start the page initialization when the DOM is ready
document.addEventListener('DOMContentLoaded', initPage);