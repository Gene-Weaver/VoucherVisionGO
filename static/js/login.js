// Initialize Firebase
firebase.initializeApp(firebaseConfig);

// Set persistence based on remember me checkbox
// Default to LOCAL persistence (survives browser restarts)
firebase.auth().setPersistence(firebase.auth.Auth.Persistence.LOCAL);

// Check if user is already signed in
firebase.auth().onAuthStateChanged(function(user) {
  if (user) {
    // Check the user's approval status
    checkApprovalStatus(user);
  }
});

const STORED_AUTH_KEYS = ['auth_id_token', 'auth_refresh_token', 'auth_user_email'];
// Firebase reports these when the saved session can no longer be used, for
// example after a password reset on this or another device.
const ENDED_SESSION_CODES = ['auth/user-token-expired', 'auth/invalid-user-token',
                             'auth/user-disabled', 'auth/user-not-found'];

function showLoginError(message) {
  const errorElement = document.getElementById('error-message');
  document.getElementById('success-message').style.display = 'none';
  errorElement.textContent = message;
  errorElement.style.display = 'block';
}

// Called when the account-status check cannot complete.
function handleStatusCheckError(error) {
  console.error('Error checking approval status:', error);
  if (error && ENDED_SESSION_CODES.indexOf(error.code) !== -1) {
    STORED_AUTH_KEYS.forEach(function(key) { localStorage.removeItem(key); });
    firebase.auth().signOut().catch(function() {});
    showLoginError('Your password was changed or your session ended. Please sign in again.');
  } else {
    showLoginError('We could not check your account status. Please try again.');
  }
}

// Function to check user approval status
async function checkApprovalStatus(user) {
  try {
    // Get ID token for API call
    const idToken = await user.getIdToken();
    
    // Check user status
    const response = await fetch('/check-approval-status', {
      headers: {
        'Authorization': `Bearer ${idToken}`
      }
    });
    
    if (response.ok) {
      const data = await response.json();
      
      if (data.status === 'approved') {
        // Store user info
        localStorage.setItem('auth_user_email', user.email);
        
        // Get the latest ID token and save refresh token
        user.getIdToken(true).then(function(idToken) {
          localStorage.setItem('auth_id_token', idToken);
          
          // Also store user refresh token for later use
          if (user.refreshToken) {
            localStorage.setItem('auth_refresh_token', user.refreshToken);
          }
          
          // Redirect to success page
          window.location.href = '/auth-success';
        }).catch(handleStatusCheckError);
      } else if (data.status === 'pending') {
        // Redirect to pending approval page
        window.location.href = '/pending-approval';
      } else if (data.status === 'rejected') {
        // Redirect to rejected page
        window.location.href = '/application-rejected';
      }
    } else {
      handleStatusCheckError(new Error('Status check failed with HTTP ' + response.status));
    }
  } catch (error) {
    handleStatusCheckError(error);
  }
}

// Email/Password login
document.getElementById('login-button').addEventListener('click', function() {
  const email = document.getElementById('email').value;
  const password = document.getElementById('password').value;
  const rememberMe = document.getElementById('remember-me').checked;
  const errorElement = document.getElementById('error-message');
  const successElement = document.getElementById('success-message');
  
  errorElement.style.display = 'none';
  successElement.style.display = 'none';
  
  if (!email || !password) {
    errorElement.textContent = 'Please enter both email and password';
    errorElement.style.display = 'block';
    return;
  }
  
  // Set persistence type based on remember me
  const persistenceType = rememberMe 
    ? firebase.auth.Auth.Persistence.LOCAL  // Survives browser restart
    : firebase.auth.Auth.Persistence.SESSION; // Until tab is closed
  
  firebase.auth().setPersistence(persistenceType)
    .then(() => {
      return firebase.auth().signInWithEmailAndPassword(email, password);
    })
    .then((userCredential) => {
      // Success - will redirect via checkApprovalStatus
      successElement.textContent = 'Login successful, checking account status...';
      successElement.style.display = 'block';
      
      // Check approval status
      checkApprovalStatus(userCredential.user);
    })
    .catch((error) => {
      // Show error message
      errorElement.textContent = error.message;
      errorElement.style.display = 'block';
    });
});

// Forgot password handler
const RESET_COOLDOWN_MS = 60000;
let lastResetRequestAt = 0;

document.getElementById('forgot-password').addEventListener('click', function(e) {
  e.preventDefault();
  
  const email = document.getElementById('email').value.trim();
  const errorElement = document.getElementById('error-message');
  const successElement = document.getElementById('success-message');
  
  errorElement.style.display = 'none';
  successElement.style.display = 'none';
  
  if (!email) {
    errorElement.textContent = 'Please enter your email address';
    errorElement.style.display = 'block';
    return;
  }
  
  // Each new reset email invalidates the earlier ones, so stop rapid repeats.
  const waitMs = lastResetRequestAt + RESET_COOLDOWN_MS - Date.now();
  if (waitMs > 0) {
    errorElement.textContent = 'A reset email was just requested. Please wait ' +
      Math.ceil(waitMs / 1000) + ' seconds before asking for another.';
    errorElement.style.display = 'block';
    return;
  }
  lastResetRequestAt = Date.now();
  
  firebase.auth().sendPasswordResetEmail(email)
    .then(() => {
      // Firebase does not reveal whether the address has an account.
      successElement.textContent = 'If an account exists for ' + email +
        ', a password reset email is on its way. Use the most recent email, and check your spam folder.';
      successElement.style.display = 'block';
    })
    .catch((error) => {
      lastResetRequestAt = 0;
      errorElement.textContent = error.code === 'auth/invalid-email'
        ? 'That does not look like a valid email address.'
        : error.message;
      errorElement.style.display = 'block';
    });
});