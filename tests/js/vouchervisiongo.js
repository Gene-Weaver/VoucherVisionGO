// VoucherVision API Test Scripts

// Tab functionality
function openTab(evt, tabName) {
    // Hide all tab content
    const tabcontent = document.getElementsByClassName("tab-content");
    for (let i = 0; i < tabcontent.length; i++) {
        tabcontent[i].classList.remove("active");
    }
    
    // Remove active class from all tabs
    const tablinks = document.getElementsByClassName("tab");
    for (let i = 0; i < tablinks.length; i++) {
        tablinks[i].classList.remove("active");
    }
    
    // Show the selected tab content and mark the tab as active
    document.getElementById(tabName).classList.add("active");
    evt.currentTarget.classList.add("active");
}

// Logger function for debug info
function logDebug(message, data = null) {
    const timestamp = new Date().toISOString();
    let logEntry = `<div><strong>${timestamp}</strong>: ${message}</div>`;
    
    if (data) {
        let dataStr;
        try {
            dataStr = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
            logEntry += `<pre>${dataStr}</pre>`;
        } catch (e) {
            logEntry += `<pre>Error stringifying data: ${e.message}</pre>`;
        }
    }
    
    $('#debugInfo').prepend(logEntry);
}

// Get selected engines
function getSelectedEngines() {
    const engines = [];
    $('input[name="engines"]:checked').each(function() {
        engines.push($(this).val());
    });
    return engines;
}

// Test CORS support
async function testCorsSupport() {
    const corsStatusElement = document.getElementById('corsStatus');
    
    try {
        logDebug(`Testing CORS support for: https://vouchervision-go-738307415303.us-central1.run.app/cors-test`);
        
        corsStatusElement.textContent = 'Testing CORS...';
        corsStatusElement.className = 'status-display';
        
        const response = await fetch('https://vouchervision-go-738307415303.us-central1.run.app/cors-test', {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        logDebug(`CORS test response status: ${response.status}`);
        
        if (response.ok) {
            const result = await response.json();
            corsStatusElement.textContent = 'CORS is properly configured!';
            corsStatusElement.className = 'status-display cors-success';
            
            logDebug('CORS test successful:', result);
            return true;
        } else {
            corsStatusElement.textContent = `CORS test failed: ${response.status}`;
            corsStatusElement.className = 'status-display cors-error';
            
            logDebug(`CORS test failed: ${response.status}`);
            return false;
        }
    } catch (error) {
        corsStatusElement.textContent = `CORS test error: ${error.message}`;
        corsStatusElement.className = 'status-display cors-error';
        
        logDebug('CORS test error:', error);
        return false;
    }
}

// Test URL availability
async function testUrlAvailability() {
    const imageUrl = $('#imageUrl').val();
    if (!imageUrl) {
        $('#urlTestResult').html('<span class="error">Please enter a URL</span>');
        return;
    }

    $('#urlTestResult').html('<span class="loading">Testing...</span>');
    
    logDebug(`Testing URL availability: ${imageUrl}`);

    // Use fetch with CORS mode to test URL availability
    try {
        const response = await fetch(imageUrl, { 
            method: 'HEAD',
            mode: 'no-cors' // This is important for cross-origin requests
        });
        
        // If we get here, the URL exists and can be accessed
        $('#urlTestResult').html('<span class="success">URL is accessible!</span>');
        logDebug('URL test success');
        
        // Show image preview
        $('#urlResults').html(`
            <div style="margin-top: 20px;">
                <h3>Image Preview:</h3>
                <img src="${imageUrl}" style="max-width: 100%; max-height: 300px;" />
            </div>
        `);
    } catch (error) {
        $('#urlTestResult').html(`<span class="error">Error accessing URL: ${error.message}</span>`);
        logDebug('URL test failed', error);
    }
}

// Get authentication headers based on the selected auth method
function getAuthHeaders() {
    const headers = {
        'Content-Type': 'application/json'
    };
    
    // Get auth method
    const authMethod = $('input[name="authMethod"]:checked').val();
    
    if (authMethod === 'apiKey') {
        // Get the API key value from the data attribute (not the visible field)
        const apiKeyField = document.getElementById('apiKey');
        const apiKey = apiKeyField.dataset.apiKey || apiKeyField.value.trim();
        
        if (apiKey && apiKey !== 'YOUR_API_KEY') {
            headers['X-API-Key'] = apiKey;
            logDebug('Using API Key authentication', {
                apiKey: apiKey.substring(0, 3) + '•••••••' + apiKey.substring(apiKey.length - 2)
            });
        }
    } else if (authMethod === 'token') {
        // Get the auth token from the data attribute (not the visible field)
        const authTokenField = document.getElementById('authToken');
        const authToken = authTokenField.dataset.authToken || authTokenField.value.trim();
        
        if (authToken) {
            headers['Authorization'] = `Bearer ${authToken}`;
            logDebug('Using Bearer Token authentication', {
                tokenLength: authToken.length,
                tokenPrefix: authToken.substring(0, 3) + '•••••••'
            });
        }
    }
    
    return headers;
}

// Process image with file upload
function processFile() {
    const fileInput = document.getElementById('fileInput');
    if (!fileInput.files || fileInput.files.length === 0) {
        alert('Please select a file first');
        return;
    }
    
    // Check authentication
    const authMethod = $('input[name="authMethod"]:checked').val();
    
    if (authMethod === 'apiKey') {
        // Get the API key value from the data attribute (not the visible field)
        const apiKeyField = document.getElementById('apiKey');
        const apiKey = apiKeyField.dataset.apiKey || apiKeyField.value.trim();
        
        if (!apiKey || apiKey === 'YOUR_API_KEY') {
            alert('Please enter an API key');
            return;
        }
    } else if (authMethod === 'token') {
        const authToken = $('#authToken').val().trim();
        if (!authToken) {
            alert('Please enter an auth token');
            return;
        }
    }
    
    const ocrOnly = $('#ocrOnly').is(':checked');
    const engines = getSelectedEngines();
    const promptTemplate = $('#promptTemplate').val();
    
    if (engines.length === 0) {
        alert('Please select at least one engine');
        return;
    }
    
    // Create form data
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    
    // Add each selected engine
    engines.forEach(engine => {
        formData.append('engines', engine);
    });
    
    // Add prompt template if specified
    if (promptTemplate) {
        formData.append('prompt', promptTemplate);
    }
    
    // Add OCR only mode if selected
    if (ocrOnly) {
        formData.append('ocr_only', 'true');
    }
    
    // Disable button during processing
    $('#uploadButton').prop('disabled', true).text('Processing...');
    $('#fileResults').html('<p class="loading">Processing... Please wait.</p>');
    
    // Get authentication headers
    const headers = getAuthHeaders();
    // Note: Do not set Content-Type header when using FormData - the browser will set it automatically with the boundary
    delete headers['Content-Type']; 
    
    // Log request details
    logDebug('Starting file upload', {
        fileName: fileInput.files[0].name,
        fileSize: fileInput.files[0].size,
        fileType: fileInput.files[0].type,
        authMethod,
        ocrOnly: ocrOnly,
        engines: engines,
        promptTemplate: promptTemplate
    });
    
    // Log FormData contents for debugging
    const formDataEntries = [];
    for (const pair of formData.entries()) {
        formDataEntries.push({key: pair[0], value: pair[0] === 'file' ? pair[1].name : pair[1]});
    }
    logDebug('FormData contents', formDataEntries);
    
    // Use fetch API instead of jQuery AJAX
    fetch('https://vouchervision-go-738307415303.us-central1.run.app/process', {
        method: 'POST',
        headers: headers,
        body: formData,
    })
    .then(response => {
        logDebug(`Response status: ${response.status}`);
        return response.json();
    })
    .then(data => {
        logDebug('API response success', data);
        $('#fileResults').html(`
            <h3 class="success">Results:</h3>
            <pre>${JSON.stringify(data, null, 2)}</pre>
        `);
    })
    .catch(error => {
        logDebug('API response error', {
            error: error.toString(),
        });
        
        $('#fileResults').html(`
            <h3 class="error">Error:</h3>
            <p>Error: ${error.toString()}</p>
        `);
    })
    .finally(() => {
        // Re-enable button
        $('#uploadButton').prop('disabled', false).text('Upload and Process');
    });
}

// Process image with URL
function processImageUrl() {
    const imageUrl = $('#imageUrl').val();
    if (!imageUrl) {
        alert('Please enter an image URL');
        return;
    }
    
    // Check authentication
    const authMethod = $('input[name="authMethod"]:checked').val();
    
    if (authMethod === 'apiKey') {
        // Get the API key value from the data attribute (not the visible field)
        const apiKeyField = document.getElementById('apiKey');
        const apiKey = apiKeyField.dataset.apiKey || apiKeyField.value.trim();
        
        if (!apiKey || apiKey === 'YOUR_API_KEY') {
            alert('Please enter an API key');
            return;
        }
    } else if (authMethod === 'token') {
        const authToken = $('#authToken').val().trim();
        if (!authToken) {
            alert('Please enter an auth token');
            return;
        }
    }
    
    const ocrOnly = $('#ocrOnly').is(':checked');
    const engines = getSelectedEngines();
    const promptTemplate = $('#promptTemplate').val();
    
    if (engines.length === 0) {
        alert('Please select at least one engine');
        return;
    }
    
    // Disable button during processing
    $('#processUrlButton').prop('disabled', true).text('Processing...');
    $('#urlResults').html('<p class="loading">Processing... Please wait...</p>');
    
    logDebug('Starting URL processing', {
        imageUrl: imageUrl,
        authMethod,
        ocrOnly: ocrOnly,
        engines: engines,
        promptTemplate: promptTemplate
    });
    
    const requestBody = {
        image_url: imageUrl,
        engines: engines,
        ocr_only: ocrOnly
    };
    
    if (promptTemplate) {
        requestBody.prompt = promptTemplate;
    }
    
    // Get authentication headers
    const headers = getAuthHeaders();
    
    $.ajax({
        type: 'POST',
        headers: headers,
        url: 'https://vouchervision-go-738307415303.us-central1.run.app/process-url',
        data: JSON.stringify(requestBody),
        dataType: 'json',
        contentType: 'application/json',
        success: function(data) {
            logDebug('API response success', data);
            $('#urlResults').html(`
                <h3 class="success">Results:</h3>
                <pre>${JSON.stringify(data, null, 2)}</pre>
            `);
        },
        error: function(xhr, status, error) {
            const response = xhr.responseText || 'No response content';
            logDebug('API response error', {
                status: status,
                error: error,
                response: response,
                statusCode: xhr.status,
                headers: xhr.getAllResponseHeaders()
            });
            
            $('#urlResults').html(`
                <h3 class="error">Error:</h3>
                <p>Status: ${status}</p>
                <p>Status Code: ${xhr.status}</p>
                <p>Error: ${error}</p>
                <p>Response:</p>
                <pre>${response}</pre>
            `);
        },
        complete: function() {
            // Re-enable button
            $('#processUrlButton').prop('disabled', false).text('Process URL');
        }
    });
}

// Toggle auth method visibility
function toggleAuthFields() {
    const authMethod = $('input[name="authMethod"]:checked').val();
    
    if (authMethod === 'apiKey') {
        $('#apiKeyFields').show();
        $('#tokenFields').hide();
    } else {
        $('#apiKeyFields').hide();
        $('#tokenFields').show();
    }
    
    logDebug(`Auth method changed to: ${authMethod}`);
}

// Initialize when document is ready
$(document).ready(function() {
    // Add comments at the top for running local server
    console.log(`
    VoucherVision API Test Tool
    ---------------------------
    To run this locally:
    1. Start a local server: python -m http.server 8000
    2. Open in browser: http://localhost:8000/vouchervisiongo.html
    `);
    
    // Set up tab click events
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', function(event) {
            openTab(event, this.getAttribute('data-tab'));
        });
    });
    
    // Set up button click events
    $('#testCorsButton').click(testCorsSupport);
    $('#testUrlAvailability').click(testUrlAvailability);
    $('#uploadButton').click(processFile);
    $('#processUrlButton').click(processImageUrl);
    
    // Set up auth method toggle
    $('input[name="authMethod"]').change(toggleAuthFields);
    
    // Init auth method visibility
    toggleAuthFields();
    
    // Set up file input change event for visual feedback
    $('#fileInput').change(function() {
        if (this.files && this.files.length > 0) {
            const fileName = this.files[0].name;
            $(this).next('.file-name').remove();
            $(this).after(`<span class="file-name">Selected: ${fileName}</span>`);
        }
    });
    
    // Initialize the page
    logDebug('Page initialized');
});

