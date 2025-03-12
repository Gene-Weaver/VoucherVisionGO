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
        });
      } else if (data.status === 'pending') {
        // Redirect to pending approval page
        window.location.href = '/pending-approval';
      } else if (data.status === 'rejected') {
        // Redirect to rejected page
        window.location.href = '/application-rejected';
      }
    }
  } catch (error) {
    console.error('Error checking approval status:', error);
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
document.getElementById('forgot-password').addEventListener('click', function(e) {
  e.preventDefault();
  
  const email = document.getElementById('email').value;
  const errorElement = document.getElementById('error-message');
  const successElement = document.getElementById('success-message');
  
  errorElement.style.display = 'none';
  successElement.style.display = 'none';
  
  if (!email) {
    errorElement.textContent = 'Please enter your email address';
    errorElement.style.display = 'block';
    return;
  }
  
  firebase.auth().sendPasswordResetEmail(email)
    .then(() => {
      successElement.textContent = 'Password reset email sent. Please check your inbox.';
      successElement.style.display = 'block';
    })
    .catch((error) => {
      errorElement.textContent = error.message;
      errorElement.style.display = 'block';
    });
});