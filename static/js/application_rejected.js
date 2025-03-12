// Initialize Firebase
firebase.initializeApp(firebaseConfig);

// Check if user is signed in
firebase.auth().onAuthStateChanged(function(user) {
  if (user) {
    // Display user email
    document.getElementById('user-email').textContent = user.email;
    
    // Get rejection reason
    getRejectionReason(user);
  } else {
    // Not signed in, redirect to login
    window.location.href = '/login';
  }
});

// Function to get rejection reason
async function getRejectionReason(user) {
  try {
    // Get ID token
    const idToken = await user.getIdToken(true);
    
    // Check status and get rejection reason
    const response = await fetch('/check-approval-status', {
      headers: {
        'Authorization': `Bearer ${idToken}`
      }
    });
    
    if (response.ok) {
      const data = await response.json();
      
      if (data.status === 'rejected') {
        document.getElementById('rejection-reason').textContent = 
          data.reason || 'No specific reason provided.';
      } else if (data.status === 'approved') {
        // Redirect to success page if actually approved
        window.location.href = '/auth-success';
      } else if (data.status === 'pending') {
        // Redirect to pending page if actually pending
        window.location.href = '/pending-approval';
      }
    }
  } catch (error) {
    console.error('Error getting rejection reason:', error);
    document.getElementById('rejection-reason').textContent = 
      'Could not retrieve rejection reason. Please contact support.';
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