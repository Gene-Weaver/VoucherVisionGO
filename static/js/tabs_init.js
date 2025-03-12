// Initialize Bootstrap tabs and accordions
document.addEventListener('DOMContentLoaded', function () {
    // Check if the user has API key access and show/hide the API Key tab accordingly
    const currentUser = firebase.auth().currentUser;
    if (currentUser) {
      checkApiKeyPermission(currentUser)
        .then(hasApiKeyAccess => {
          const apikeyTab = document.getElementById('apikey-tab');
          if (!hasApiKeyAccess && apikeyTab) {
            apikeyTab.parentElement.style.display = 'none';
          }
        })
        .catch(error => {
          console.error('Error checking API key permission:', error);
        });
    }
    
    // Add click handler for "Manage API Keys" button
    const goToApiKeysBtn = document.getElementById('go-to-api-keys');
    if (goToApiKeysBtn) {
      goToApiKeysBtn.addEventListener('click', async function(e) {
        e.preventDefault();
        
        try {
          const user = firebase.auth().currentUser;
          if (!user) throw new Error('Not signed in');
          
          // Get fresh ID token
          const freshToken = await user.getIdToken(true);
          
          // Create a form with the proper encoding type
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
          
          // Submit the form
          form.submit();
        } catch (error) {
          console.error('Error accessing API key management:', error);
          alert('Authentication error. Please try logging in again.');
        }
      });
    }
  });