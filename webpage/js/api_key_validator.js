// API Key and Auth Token Validation Logic for VoucherVision API Test

// Create modal overlay and popup for API Key
function createApiKeyModal() {
    // Create modal container
    const modalOverlay = document.createElement('div');
    modalOverlay.id = 'apiKeyModalOverlay';
    modalOverlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        justify-content: center;
        align-items: center;
        z-index: 1000;
    `;

    // Create modal content
    const modalContent = document.createElement('div');
    modalContent.style.cssText = `
        background: white;
        padding: 30px;
        border-radius: 8px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
        width: 400px;
        max-width: 90%;
    `;

    // Add title and description
    const modalTitle = document.createElement('h2');
    modalTitle.textContent = 'VoucherVision API Key Required';
    modalTitle.style.color = '#2E7D32';
    modalTitle.style.marginTop = '0';

    const modalDescription = document.createElement('p');
    modalDescription.innerHTML = 'Please enter your API key to use the VoucherVision API testing tool. If you do not have an API Key or an Authentication Token, <a href="https://vouchervision-go-738307415303.us-central1.run.app/signup" target="_blank">sign up for access</a> or <a href="https://vouchervision-go-738307415303.us-central1.run.app/login" target="_blank">log in to an existing account</a>.';

    // Create form elements
    const apiKeyInput = document.createElement('input');
    apiKeyInput.type = 'text';
    apiKeyInput.id = 'modalApiKey';
    apiKeyInput.placeholder = 'Enter your API key';
    apiKeyInput.style.cssText = `
        width: 100%;
        padding: 10px;
        margin: 10px 0;
        border: 1px solid #ddd;
        border-radius: 4px;
        box-sizing: border-box;
    `;

    // Create buttons
    const buttonContainer = document.createElement('div');
    buttonContainer.style.display = 'flex';
    buttonContainer.style.justifyContent = 'space-between';
    buttonContainer.style.marginTop = '20px';

    const continueButton = document.createElement('button');
    continueButton.textContent = 'Continue';
    continueButton.className = 'button';
    continueButton.style.cssText = `
        background-color: #4CAF50;
        color: white;
        border: none;
        padding: 10px 15px;
        border-radius: 4px;
        cursor: pointer;
        font-size: 16px;
    `;

    const cancelButton = document.createElement('button');
    cancelButton.textContent = 'Skip for now';
    cancelButton.style.cssText = `
        background-color: #f1f1f1;
        color: #333;
        border: 1px solid #ddd;
        padding: 10px 15px;
        border-radius: 4px;
        cursor: pointer;
        font-size: 16px;
    `;

    // Add event listeners
    continueButton.addEventListener('click', function() {
        const apiKey = apiKeyInput.value.trim();
        if (apiKey) {
            // Store the actual API key in a hidden input
            const actualApiKey = apiKey;
            
            // Set the displayed masked API key
            document.getElementById('apiKey').value = maskApiKey(apiKey);
            
            // Store actual API key in localStorage for future visits
            localStorage.setItem('vouchervision_api_key', apiKey);
            
            // Store the actual API key in a data attribute for use in API calls
            document.getElementById('apiKey').dataset.apiKey = actualApiKey;
            
            // Show testing message
            logDebug('Testing API key validity...');
            
            // Automatically test the API key
            testCorsSupport().then(success => {
                if (success) {
                    logDebug('API key validation successful');
                    // Enable all buttons
                    enableButtons();
                } else {
                    logDebug('API key validation failed');
                    // Keep buttons disabled if validation fails
                    disableButtons();
                    alert('Could not connect to the API with the provided API key. Please check your API key and try again.');
                }
            });
            
            // Remove the modal regardless of test result
            document.body.removeChild(modalOverlay);
        } else {
            // Show error message
            alert('Please enter a valid API key');
        }
    });

    cancelButton.addEventListener('click', function() {
        document.body.removeChild(modalOverlay);
        // Keep buttons disabled if canceled
        disableButtons();
        logDebug('API key prompt canceled');
    });

    // Add keypress event for Enter key
    apiKeyInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            continueButton.click();
        }
    });

    // Assemble the modal
    buttonContainer.appendChild(cancelButton);
    buttonContainer.appendChild(continueButton);

    modalContent.appendChild(modalTitle);
    modalContent.appendChild(modalDescription);
    modalContent.appendChild(apiKeyInput);
    modalContent.appendChild(buttonContainer);

    modalOverlay.appendChild(modalContent);
    
    return modalOverlay;
}

// Create modal overlay and popup for Auth Token
function createAuthTokenModal() {
    // Create modal container
    const modalOverlay = document.createElement('div');
    modalOverlay.id = 'authTokenModalOverlay';
    modalOverlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.5);
        display: flex;
        justify-content: center;
        align-items: center;
        z-index: 1000;
    `;

    // Create modal content
    const modalContent = document.createElement('div');
    modalContent.style.cssText = `
        background: white;
        padding: 30px;
        border-radius: 8px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
        width: 500px;
        max-width: 90%;
    `;

    // Add title and description
    const modalTitle = document.createElement('h2');
    modalTitle.textContent = 'VoucherVision Auth Token Required';
    modalTitle.style.color = '#2E7D32';
    modalTitle.style.marginTop = '0';

    const modalDescription = document.createElement('p');
    modalDescription.textContent = 'Please enter your Token to use the VoucherVision API testing tool.';

    // Help text
    const helpText = document.createElement('p');
    helpText.innerHTML = '<small>Tokens are valid for 1 hour, or as long as you are logged into the browser page. API Keys are valid for longer durations without requiring browser-based authentication.</small>';
    helpText.style.color = '#666';

    // Create form elements
    const tokenInput = document.createElement('textarea');
    tokenInput.id = 'modalAuthToken';
    tokenInput.placeholder = 'Enter your authentication token';
    tokenInput.style.cssText = `
        width: 100%;
        height: 100px;
        padding: 10px;
        margin: 10px 0;
        border: 1px solid #ddd;
        border-radius: 4px;
        box-sizing: border-box;
        font-family: monospace;
        font-size: 12px;
    `;

    // Create buttons
    const buttonContainer = document.createElement('div');
    buttonContainer.style.display = 'flex';
    buttonContainer.style.justifyContent = 'space-between';
    buttonContainer.style.marginTop = '20px';

    const continueButton = document.createElement('button');
    continueButton.textContent = 'Continue';
    continueButton.className = 'button';
    continueButton.style.cssText = `
        background-color: #4CAF50;
        color: white;
        border: none;
        padding: 10px 15px;
        border-radius: 4px;
        cursor: pointer;
        font-size: 16px;
    `;

    const cancelButton = document.createElement('button');
    cancelButton.textContent = 'Skip for now';
    cancelButton.style.cssText = `
        background-color: #f1f1f1;
        color: #333;
        border: 1px solid #ddd;
        padding: 10px 15px;
        border-radius: 4px;
        cursor: pointer;
        font-size: 16px;
    `;

    // Add event listeners
    continueButton.addEventListener('click', function() {
        const token = tokenInput.value.trim();
        if (token) {
            // Store the actual token in a data attribute
            const authTokenField = document.getElementById('authToken');
            authTokenField.dataset.authToken = token;
            
            // Set the masked token in the visible input field
            authTokenField.value = maskAuthToken(token);
            
            // Store token in localStorage for future visits
            localStorage.setItem('vouchervision_auth_token', token);
            
            // Show testing message
            logDebug('Testing auth token validity...');
            
            // Automatically test the auth token
            testCorsSupport().then(success => {
                if (success) {
                    logDebug('Auth token validation successful');
                    // Enable all buttons
                    enableButtons();
                } else {
                    logDebug('Auth token validation failed');
                    // Keep buttons disabled if validation fails
                    disableButtons();
                    alert('Could not connect to the API with the provided authentication token. Please check your token and try again.');
                }
            });
            
            // Remove the modal regardless of test result
            document.body.removeChild(modalOverlay);
        } else {
            // Show error message
            alert('Please enter a valid authentication token');
        }
    });

    cancelButton.addEventListener('click', function() {
        document.body.removeChild(modalOverlay);
        // Keep buttons disabled if canceled
        disableButtons();
        logDebug('Auth token prompt canceled');
    });

    // Add keypress event for Enter key
    tokenInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && e.ctrlKey) {
            continueButton.click();
        }
    });

    // Assemble the modal
    buttonContainer.appendChild(cancelButton);
    buttonContainer.appendChild(continueButton);

    modalContent.appendChild(modalTitle);
    modalContent.appendChild(modalDescription);
    modalContent.appendChild(helpText);
    modalContent.appendChild(tokenInput);
    modalContent.appendChild(buttonContainer);

    modalOverlay.appendChild(modalContent);
    
    return modalOverlay;
}

// Function to check if the API key is set
function isApiKeySet() {
    const apiKeyField = document.getElementById('apiKey');
    const apiKey = apiKeyField.dataset.apiKey || apiKeyField.value.trim();
    return apiKey !== '' && apiKey !== 'YOUR_API_KEY';
}

// Function to check if the auth token is set
function isAuthTokenSet() {
    const authTokenField = document.getElementById('authToken');
    const authToken = authTokenField.dataset.authToken || authTokenField.value.trim();
    return authToken !== '';
}

// Function to mask API key for display
function maskApiKey(apiKey) {
    if (apiKey.length <= 8) {
        return '---HIDDEN---';
    }
    return apiKey.substring(0, 4) + '---HIDDEN---' + apiKey.substring(apiKey.length - 4);
}

// Function to mask auth token for display
function maskAuthToken(token) {
    if (!token || token.length <= 10) {
        return '---HIDDEN---';
    }
    return token.substring(0, 5) + '---HIDDEN---' + token.substring(token.length - 5);
}

// Function to disable all action buttons until authentication is provided
function disableButtons() {
    document.getElementById('uploadButton').disabled = true;
    document.getElementById('processUrlButton').disabled = true;
    document.getElementById('testUrlAvailability').disabled = true;
}

// Function to enable all action buttons
function enableButtons() {
    document.getElementById('uploadButton').disabled = false;
    document.getElementById('processUrlButton').disabled = false;
    document.getElementById('testUrlAvailability').disabled = false;
}

// Check the current authentication method and initialize accordingly
function initAuthCheck() {
    const authMethod = $('input[name="authMethod"]:checked').val();
    
    if (authMethod === 'apiKey') {
        return initApiKeyCheck();
    } else if (authMethod === 'token') {
        return initAuthTokenCheck();
    }
    
    // Default to API key if something goes wrong
    return initApiKeyCheck();
}

// Initialize API key check
function initApiKeyCheck() {
    // See if we have a stored API key
    const storedApiKey = localStorage.getItem('vouchervision_api_key');
    
    if (storedApiKey) {
        // Display masked API key
        document.getElementById('apiKey').value = maskApiKey(storedApiKey);
        // Store the actual API key in a data attribute for use in API calls
        document.getElementById('apiKey').dataset.apiKey = storedApiKey;
        logDebug('API key loaded from local storage');
        
        // Automatically test the stored API key
        logDebug('Testing stored API key validity...');
        testCorsSupport().then(success => {
            if (success) {
                logDebug('Stored API key validation successful');
                enableButtons();
            } else {
                logDebug('Stored API key validation failed');
                disableButtons();
                // Show the API key modal to get a new key
                const modal = createApiKeyModal();
                document.body.appendChild(modal);
                document.getElementById('modalApiKey').focus();
            }
        });
        
        return true;
    }
    
    // Check if API key is already set (not the default value)
    if (isApiKeySet()) {
        // If it's already set but not masked, mask it now
        const currentKey = document.getElementById('apiKey').value.trim();
        if (currentKey !== 'YOUR_API_KEY' && !currentKey.includes('•')) {
            document.getElementById('apiKey').dataset.apiKey = currentKey;
            document.getElementById('apiKey').value = maskApiKey(currentKey);
        }
        logDebug('API key already set in the form');
        
        // Automatically test the existing API key
        logDebug('Testing existing API key validity...');
        testCorsSupport().then(success => {
            if (success) {
                logDebug('Existing API key validation successful');
                enableButtons();
            } else {
                logDebug('Existing API key validation failed');
                disableButtons();
                // Show the API key modal to get a new key
                const modal = createApiKeyModal();
                document.body.appendChild(modal);
                document.getElementById('modalApiKey').focus();
            }
        });
        
        return true;
    }
    
    // Create and show modal
    const modal = createApiKeyModal();
    document.body.appendChild(modal);
    document.getElementById('modalApiKey').focus();
    
    // Disable buttons until API key is set
    disableButtons();
    
    logDebug('API key prompt displayed');
    return false;
}

// Initialize auth token check
function initAuthTokenCheck() {
    // See if we have a stored auth token
    const storedToken = localStorage.getItem('vouchervision_auth_token');
    
    if (storedToken) {
        // Set the masked token in the visible input field
        document.getElementById('authToken').value = maskAuthToken(storedToken);
        // Store the actual token in a data attribute for use in API calls
        document.getElementById('authToken').dataset.authToken = storedToken;
        logDebug('Auth token loaded from local storage (masked for display)');
        
        // Automatically test the stored token
        logDebug('Testing stored auth token validity...');
        testCorsSupport().then(success => {
            if (success) {
                logDebug('Stored auth token validation successful');
                enableButtons();
            } else {
                logDebug('Stored auth token validation failed');
                disableButtons();
                // Show the auth token modal to get a new token
                const modal = createAuthTokenModal();
                document.body.appendChild(modal);
                document.getElementById('modalAuthToken').focus();
            }
        });
        
        return true;
    }
    
    // Check if auth token is already set
    if (isAuthTokenSet()) {
        // If it's already set but not masked, mask it now
        const currentToken = document.getElementById('authToken').value.trim();
        if (!currentToken.includes('•')) {
            document.getElementById('authToken').dataset.authToken = currentToken;
            document.getElementById('authToken').value = maskAuthToken(currentToken);
        }
        logDebug('Auth token already set in the form');
        
        // Automatically test the existing token
        logDebug('Testing existing auth token validity...');
        testCorsSupport().then(success => {
            if (success) {
                logDebug('Existing auth token validation successful');
                enableButtons();
            } else {
                logDebug('Existing auth token validation failed');
                disableButtons();
                // Show the auth token modal to get a new token
                const modal = createAuthTokenModal();
                document.body.appendChild(modal);
                document.getElementById('modalAuthToken').focus();
            }
        });
        
        return true;
    }
    
    // Create and show modal
    const modal = createAuthTokenModal();
    document.body.appendChild(modal);
    document.getElementById('modalAuthToken').focus();
    
    // Disable buttons until auth token is set
    disableButtons();
    
    logDebug('Auth token prompt displayed');
    return false;
}

// Create and add API Key buttons dynamically
function createApiKeyButtons() {
    const apiKeyInput = document.getElementById('apiKey');
    const apiKeyContainer = apiKeyInput.parentNode;
    
    // Create Clear API Key button
    const clearButton = document.createElement('button');
    clearButton.textContent = 'Clear API Key';
    clearButton.className = 'button';
    clearButton.style.cssText = `
        background-color: #f44336;
        margin-left: 10px;
    `;
    
    clearButton.addEventListener('click', function() {
        // Clear the API key
        document.getElementById('apiKey').value = '';
        document.getElementById('apiKey').dataset.apiKey = '';
        localStorage.removeItem('vouchervision_api_key');
        
        // Disable buttons until new key is provided
        disableButtons();
        
        // Show the modal again
        initApiKeyCheck();
        
        logDebug('API key cleared');
    });
    
    // Create Test API Key button
    const validateButton = document.createElement('button');
    validateButton.textContent = 'Test API Key';
    validateButton.className = 'button';
    validateButton.style.cssText = `
        background-color: #2196F3;
        margin-left: 10px;
    `;
    
    validateButton.addEventListener('click', function() {
        const apiKeyField = document.getElementById('apiKey');
        const apiKey = apiKeyField.dataset.apiKey || apiKeyField.value.trim();
        
        if (!apiKey || apiKey === 'YOUR_API_KEY') {
            alert('Please enter an API key');
            return;
        }
        
        // Test the API key with a simple endpoint
        validateButton.disabled = true;
        validateButton.textContent = 'Testing...';
        
        // Try to validate by checking with the API
        testCorsSupport().then(success => {
            if (success) {
                alert('API connection successful! You can now use the tool.');
                enableButtons();
            } else {
                alert('Could not connect to the API. Please check your API key and try again.');
            }
            validateButton.disabled = false;
            validateButton.textContent = 'Test API Key';
        });
    });
    
    // Add buttons to the container
    apiKeyContainer.appendChild(clearButton);
    apiKeyContainer.appendChild(validateButton);
}

// Setup clear token button event handler
function setupClearTokenButton() {
    const clearTokenButton = document.getElementById('clearTokenButton');
    if (clearTokenButton) {
        clearTokenButton.addEventListener('click', function() {
            // Clear the auth token
            document.getElementById('authToken').value = '';
            document.getElementById('authToken').dataset.authToken = '';
            localStorage.removeItem('vouchervision_auth_token');
            
            // Disable buttons until new token is provided
            disableButtons();
            
            // Show the modal again
            initAuthTokenCheck();
            
            logDebug('Auth token cleared');
        });
    }
}

// Add this to the document ready function
$(document).ready(function() {
    // Initialize auth check based on selected method
    initAuthCheck();
    
    // Create API key buttons dynamically
    createApiKeyButtons();
    
    // Setup clear token button (this button exists in HTML)
    setupClearTokenButton();
    
    // Handle auth method change
    $('input[name="authMethod"]').change(function() {
        const method = $(this).val();
        
        // Check if we need to initialize the newly selected method
        if (method === 'apiKey') {
            initApiKeyCheck();
        } else if (method === 'token') {
            initAuthTokenCheck();
        }
    });
    
    // Intercept all action button clicks to verify authentication is set
    const actionButtons = ['uploadButton', 'processUrlButton', 'testUrlAvailability'];
    
    actionButtons.forEach(buttonId => {
        const originalButton = document.getElementById(buttonId);
        if (originalButton) {
            const originalOnClick = originalButton.onclick;
            
            originalButton.onclick = function(e) {
                const authMethod = $('input[name="authMethod"]:checked').val();
                
                if (authMethod === 'apiKey' && !isApiKeySet()) {
                    e.preventDefault();
                    const modal = createApiKeyModal();
                    document.body.appendChild(modal);
                    return false;
                } else if (authMethod === 'token' && !isAuthTokenSet()) {
                    e.preventDefault();
                    const modal = createAuthTokenModal();
                    document.body.appendChild(modal);
                    return false;
                }
                
                // Continue with the original handler
                if (typeof originalOnClick === 'function') {
                    return originalOnClick.call(this, e);
                }
                return true;
            };
        }
    });
});