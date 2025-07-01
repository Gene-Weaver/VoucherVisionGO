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


// Get selected model
function getSelectedModel() {
    // Get the selected model directly from the DOM
    const selectedRadio = document.querySelector('input[name="llm_model"]:checked');
    
    // Debug the selection
    console.log("Selected LLM model radio:", selectedRadio);
    
    if (selectedRadio) {
        console.log("Selected model value:", selectedRadio.value);
        return selectedRadio.value;
    } else {
        // Fallback to default if no radio is selected (shouldn't happen with properly set defaults)
        console.log("No model selected, using default: gemini-2.0-flash");
        return "gemini-2.0-flash";
    }
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
    const llm_model = getSelectedModel(); // Get selected model
    
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
    
    // Add selected model
    if (llm_model) {
        formData.append('llm_model', llm_model);
    }
    
    // Disable button during processing
    $('#uploadButton').prop('disabled', true).text('Processing...');
    $('#fileResults').html('<p class="loading">Processing... Please wait.</p>');
    
    // Get authentication headers
    const headers = getAuthHeaders();
    delete headers['Content-Type'];

    // Log request details
    logDebug('Starting file upload', {
        fileName: fileInput.files[0].name,
        fileSize: fileInput.files[0].size,
        fileType: fileInput.files[0].type,
        authMethod,
        ocrOnly: ocrOnly,
        engines: engines,
        promptTemplate: promptTemplate,
        llm_model: llm_model // Log the model
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


// Process image with URL - Using FormData
// function processImageUrl() {
//     const imageUrl = $('#imageUrl').val();
//     if (!imageUrl) {
//         alert('Please enter an image URL');
//         return;
//     }
    
//     // Check authentication
//     const authMethod = $('input[name="authMethod"]:checked').val();
//     if (authMethod === 'apiKey') {
//         const apiKeyField = document.getElementById('apiKey');
//         const apiKey = apiKeyField.dataset.apiKey || apiKeyField.value.trim();
//         if (!apiKey || apiKey === 'YOUR_API_KEY') {
//             alert('Please enter an API key');
//             return;
//         }
//     } else if (authMethod === 'token') {
//         const authToken = $('#authToken').val().trim();
//         if (!authToken) {
//             alert('Please enter an auth token');
//             return;
//         }
//     }

//     const ocrOnly = $('#ocrOnly').is(':checked');
//     const engines = getSelectedEngines();
//     const promptTemplate = $('#promptTemplate').val();
//     const llm_model = getSelectedModel(); // use your standard function here!

//     if (engines.length === 0) {
//         alert('Please select at least one engine');
//         return;
//     }

//     $('#processUrlButton').prop('disabled', true).text('Processing...');
//     $('#urlResults').html('<p class="loading">Processing... Please wait...</p>');

//     const formData = new FormData();
//     formData.append('image_url', imageUrl);

//     engines.forEach(engine => formData.append('engines', engine));
//     if (promptTemplate) formData.append('prompt', promptTemplate);
//     if (ocrOnly) formData.append('ocr_only', 'true');
//     if (llm_model) formData.append('llm_model', llm_model);

//     // Get auth headers
//     const headers = getAuthHeaders();
//     if ('Content-Type' in headers) {delete headers['Content-Type'];}

//     const formDataEntries = [];
//     for (const pair of formData.entries()) {
//         formDataEntries.push({ key: pair[0], value: pair[1] });
//     }
//     logDebug('FINAL FormData contents for URL upload', formDataEntries);

//     fetch('https://vouchervision-go-738307415303.us-central1.run.app/process-url', {
//         method: 'POST',
//         headers: headers,
//         body: formData
//     })
//     .then(response => {
//         logDebug(`Response status: ${response.status}`);
//         if (!response.ok) {
//             throw new Error(`HTTP error! Status: ${response.status}`);
//         }
//         return response.json();
//     })
//     .then(data => {
//         logDebug('API response success', data);
//         $('#urlResults').html(`
//             <h3 class="success">Results:</h3>
//             <pre>${JSON.stringify(data, null, 2)}</pre>
//         `);
//     })
//     .catch(error => {
//         logDebug('API response error', { error: error.toString() });
//         $('#urlResults').html(`
//             <h3 class="error">Error:</h3>
//             <p>Error: ${error.toString()}</p>
//         `);
//     })
//     .finally(() => {
//         $('#processUrlButton').prop('disabled', false).text('Process URL');
//     });
// }


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
    console.log(`
    VoucherVision API Test Tool
    ---------------------------
    To run this locally:
    1. Start a local server: python -m http.server 8000
    2. Open in browser: http://localhost:8000/vouchervisiongo.html
    `);

    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', function(event) {
            openTab(event, this.getAttribute('data-tab'));
        });
    });

    $('#testCorsButton').click(testCorsSupport);
    $('#testUrlAvailability').click(testUrlAvailability);
    $('#uploadButton').click(() => processImage('file'));
    $('#processUrlButton').click(() => processImage('url'));

    $('input[name="authMethod"]').change(toggleAuthFields);
    toggleAuthFields();

    $('#fileInput').change(function() {
        if (this.files && this.files.length > 0) {
            const fileName = this.files[0].name;
            $(this).next('.file-name').remove();
            $(this).after(`<span class="file-name">Selected: ${fileName}</span>`);
        }
    });

    logDebug('Page initialized');
});


// Process a single URL
// async function processUrl() {
//     const imageUrl = $('#imageUrl').val();
//     if (!imageUrl) {
//         alert('Please enter an image URL');
//         return;
//     }

//     const authMethod = $('input[name="authMethod"]:checked').val();
//     if (authMethod === 'apiKey') {
//         const apiKeyField = document.getElementById('apiKey');
//         const apiKey = apiKeyField.dataset.apiKey || apiKeyField.value.trim();
//         if (!apiKey || apiKey === 'YOUR_API_KEY') {
//             alert('Please enter a valid API key');
//             return;
//         }
//     } else if (authMethod === 'token') {
//         const authToken = $('#authToken').val().trim();
//         if (!authToken) {
//             alert('Please enter a valid auth token');
//             return;
//         }
//     }

//     const ocrOnly = $('#ocrOnly').is(':checked');
//     const engines = getSelectedEngines();
//     const promptTemplate = $('#promptTemplate').val();
//     const llm_model = getSelectedModel(); 

//     if (engines.length === 0) {
//         alert('Please select at least one engine');
//         return;
//     }

//     // Create form data
//     const formData = new FormData();
//     formData.append('image_url', imageUrl);

//     engines.forEach(engine => {
//         formData.append('engines', engine);
//     });

//     if (promptTemplate) {
//         formData.append('prompt', promptTemplate);
//     }

//     if (ocrOnly) {
//         formData.append('ocr_only', 'true');
//     }

//     if (llm_model) {
//         formData.append('llm_model', llm_model);  // ✅ add selected model
//     }

//     $('#processUrlButton').prop('disabled', true).text('Processing...');
//     $('#urlResults').html('<p class="loading">Processing... Please wait.</p>');

//     const headers = getAuthHeaders();
//     delete headers['Content-Type'];

//     logDebug('Starting URL processing', {
//         imageUrl: imageUrl,
//         authMethod,
//         ocrOnly: ocrOnly,
//         engines: engines,
//         promptTemplate: promptTemplate,
//         llm_model: llm_model
//     });

//     try {
//         const response = await fetch('https://vouchervision-go-738307415303.us-central1.run.app/process-url', {
//             method: 'POST',
//             headers: headers,
//             body: formData,
//         });

//         if (!response.ok) {
//             throw new Error(`API error: ${response.status} ${response.statusText}`);
//         }

//         const data = await response.json();
//         logDebug('API response success', data);

//         $('#urlResults').html(`
//             <h3 class="success">Results:</h3>
//             <pre>${JSON.stringify(data, null, 2)}</pre>
//         `);
//     } catch (error) {
//         logDebug('API response error', error);

//         $('#urlResults').html(`
//             <h3 class="error">Error:</h3>
//             <p>${error.message}</p>
//         `);
//     } finally {
//         $('#processUrlButton').prop('disabled', false).text('Process URL');
//     }
// }
// $(document).ready(function() {
//     $('#processUrlButton').click(processUrl);
// });


// Universal Image Processor
async function processImage(sourceType = 'file') {
    const authMethod = $('input[name="authMethod"]:checked').val();
    if (authMethod === 'apiKey') {
        const apiKeyField = document.getElementById('apiKey');
        const apiKey = apiKeyField.dataset.apiKey || apiKeyField.value.trim();
        if (!apiKey || apiKey === 'YOUR_API_KEY') {
            alert('Please enter a valid API key');
            return;
        }
    } else if (authMethod === 'token') {
        const authToken = $('#authToken').val().trim();
        if (!authToken) {
            alert('Please enter a valid auth token');
            return;
        }
    }

    const ocrOnly = $('#ocrOnly').is(':checked');
    const engines = getSelectedEngines();
    const promptTemplate = $('#promptTemplate').val();
    const llm_model = getSelectedModel();

    if (engines.length === 0) {
        alert('Please select at least one engine');
        return;
    }

    const formData = new FormData();

    if (sourceType === 'file') {
        const fileInput = document.getElementById('fileInput');
        if (!fileInput.files || fileInput.files.length === 0) {
            alert('Please select a file first');
            return;
        }
        formData.append('file', fileInput.files[0]);
    } else if (sourceType === 'url') {
        const imageUrl = $('#imageUrl').val();
        if (!imageUrl) {
            alert('Please enter an image URL');
            return;
        }
        formData.append('image_url', imageUrl);
    } else {
        alert('Invalid source type');
        return;
    }

    engines.forEach(engine => formData.append('engines', engine));
    if (promptTemplate) formData.append('prompt', promptTemplate);
    if (ocrOnly) formData.append('ocr_only', 'true');
    if (llm_model) formData.append('llm_model', llm_model);
    if ($('#includeWfo').is(':checked')) formData.append('include_wfo', 'true');

    const headers = getAuthHeaders();
    if ('Content-Type' in headers) delete headers['Content-Type'];

    // Choose the correct endpoint
    const endpoint = (sourceType === 'file') 
        ? 'https://vouchervision-go-738307415303.us-central1.run.app/process'
        : 'https://vouchervision-go-738307415303.us-central1.run.app/process-url';

    // Disable buttons during processing
    if (sourceType === 'file') {
        $('#uploadButton').prop('disabled', true).text('Processing...');
        $('#fileResults').html('<p class="loading">Processing... Please wait.</p>');
    } else {
        $('#processUrlButton').prop('disabled', true).text('Processing...');
        $('#urlResults').html('<p class="loading">Processing... Please wait.</p>');
    }

    // Debug log
    const formDataEntries = [];
    for (const pair of formData.entries()) {
        formDataEntries.push({ key: pair[0], value: pair[1] instanceof File ? pair[1].name : pair[1] });
    }
    logDebug('FINAL FormData contents', formDataEntries);

    try {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: headers,
            body: formData,
        });

        if (!response.ok) {
            const errorText = await response.text();
            if (response.status === 503) {
                throw new Error('API is temporarily down for maintenance');
            }
            throw new Error(`API error: ${response.status} ${response.statusText}`);
        }

        const data = await response.json();
        logDebug('API response success', data);

        let resultsHTML = `<h3 class="success">Results:</h3>`;

        // Show collage image if available
        if (data.collage_info && data.collage_info.image_collage) {
            resultsHTML += `
                <div style="margin: 10px 0;">
                    <h4>Processed Collage:</h4>
                    <img src="data:image/jpeg;base64,${data.collage_info.image_collage}" 
                        style="max-width: 100%; max-height: 400px; border: 1px solid #ccc;" />
                </div>
            `;
        }

        resultsHTML += `<pre>${JSON.stringify(data, null, 2)}</pre>`;

        if (sourceType === 'file') {
            $('#fileResults').html(resultsHTML);
        } else {
            $('#urlResults').html(resultsHTML);
        }
    } catch (error) {
        logDebug('API response error', { error: error.toString() });

        if (sourceType === 'file') {
            $('#fileResults').html(`
                <h3 class="error">Error:</h3>
                <p>${error.message}</p>
            `);
        } else {
            $('#urlResults').html(`
                <h3 class="error">Error:</h3>
                <p>${error.message}</p>
            `);
        }
    } finally {
        if (sourceType === 'file') {
            $('#uploadButton').prop('disabled', false).text('Upload and Process');
        } else {
            $('#processUrlButton').prop('disabled', false).text('Process URL');
        }
    }
}