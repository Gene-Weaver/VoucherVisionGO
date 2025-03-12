// Initialize Firebase
firebase.initializeApp(firebaseConfig);

// Set persistence to LOCAL (survives browser restarts)
firebase.auth().setPersistence(firebase.auth.Auth.Persistence.LOCAL);

// Check if user is already signed in
firebase.auth().onAuthStateChanged(function(user) {
  if (user) {
    // Check if user is approved
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
        // Redirect to success page if approved
        window.location.href = '/auth-success';
      } else if (data.status === 'pending') {
        // Redirect to pending approval page
        window.location.href = '/pending-approval';
      } else {
        // Rejected or unknown status
        window.location.href = '/application-rejected';
      }
    } else {
      // Default to pending page for new users
      window.location.href = '/pending-approval';
    }
  } catch (error) {
    console.error('Error checking approval status:', error);
  }
}

// Email/Password signup
document.getElementById('signup-button').addEventListener('click', function() {
  const email = document.getElementById('email').value;
  const password = document.getElementById('password').value;
  const confirmPassword = document.getElementById('confirm-password').value;
  const organization = document.getElementById('organization').value;
  const purpose = document.getElementById('purpose').value;
  const errorElement = document.getElementById('error-message');
  const successElement = document.getElementById('success-message');
  
  errorElement.style.display = 'none';
  successElement.style.display = 'none';
  
  if (!email || !password || !confirmPassword || !organization || !purpose) {
    errorElement.textContent = 'Please fill in all fields';
    errorElement.style.display = 'block';
    return;
  }
  
  if (password !== confirmPassword) {
    errorElement.textContent = 'Passwords do not match';
    errorElement.style.display = 'block';
    return;
  }
  
  if (password.length < 6) {
    errorElement.textContent = 'Password must be at least 6 characters';
    errorElement.style.display = 'block';
    return;
  }
  
  // Create user account
  firebase.auth().createUserWithEmailAndPassword(email, password)
    .then((userCredential) => {
      const user = userCredential.user;
      
      // Submit additional registration info
      submitRegistrationInfo(user, organization, purpose);
    })
    .catch((error) => {
      errorElement.textContent = error.message;
      errorElement.style.display = 'block';
    });
});

// Submit additional registration info
async function submitRegistrationInfo(user, organization, purpose) {
  const errorElement = document.getElementById('error-message');
  const successElement = document.getElementById('success-message');
  
  try {
    // Get ID token
    const idToken = await user.getIdToken();
    
    // Submit application data
    const response = await fetch('/submit-application', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${idToken}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        organization,
        purpose,
        email: user.email
      })
    });
    
    if (response.ok) {
      successElement.textContent = 'Your application has been submitted. You will be notified when it is approved.';
      successElement.style.display = 'block';
      
      // Redirect to pending page after a short delay
      setTimeout(() => {
        window.location.href = '/pending-approval';
      }, 3000);
    } else {
      const data = await response.json();
      throw new Error(data.error || 'Failed to submit application');
    }
  } catch (error) {
    console.error('Error submitting application:', error);
    errorElement.textContent = error.message;
    errorElement.style.display = 'block';
  }
}