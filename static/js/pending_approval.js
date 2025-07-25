// Initialize Firebase
firebase.initializeApp(firebaseConfig);

// Check if user is signed in
firebase.auth().onAuthStateChanged(function(user) {
  if (user) {
    // Display user email
    document.getElementById('user-email').textContent = user.email;
    
    // Check approval status once on page load
    checkApprovalStatus(user);
    // setInterval(() => checkApprovalStatus(user), 60000); // Check every minute
  } else {
    // Not signed in, redirect to login
    window.location.href = '/login';
  }
});

// Function to check approval status
async function checkApprovalStatus(user) {
  try {
    // Get ID token
    const idToken = await user.getIdToken(true);
    
    // Check status
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
      } else if (data.status === 'rejected') {
        // Redirect to rejected page
        window.location.href = '/application-rejected';
      }
      // If still pending, stay on this page
    }
  } catch (error) {
    console.error('Error checking approval status: ', error);
  }
}

// Logout button
document.getElementById('logout-btn').addEventListener('click', function() {
  firebase.auth().signOut().then(function() {
    window.location.href = '/login';
  }).catch(function(error) {
    console.error('Error signing out:', error);
  });
});