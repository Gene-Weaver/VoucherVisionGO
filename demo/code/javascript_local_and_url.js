/**
 * Process an image using the VoucherVision API with a local file input
 * 
 * @param {File} file - The file object (from file input)
 * @param {string} apiKey - API key for VoucherVision
 * @param {string[]} engines - Array of OCR engines to use
 * @param {string} prompt - Custom prompt file to use
 * @param {boolean} verbose - Whether to log detailed information
 * @returns {Promise} - Promise that resolves with the API response
 */
async function processLocalImage(file, apiKey, engines = ['gemini-1.5-pro', 'gemini-2.0-flash'], prompt = 'SLTPvM_default.yaml', verbose = false) {
    const serverUrl = 'https://vouchervision-go-738307415303.us-central1.run.app';
    const endpoint = '/process';
    
    if (verbose) {
        console.log(`Processing local file: ${file.name}`);
        console.log(`Server URL: ${serverUrl}${endpoint}`);
    }
    
    // Create a FormData object
    const formData = new FormData();
    formData.append('file', file);
    
    // Add engines as separate form fields with the same name
    if (engines && engines.length) {
        engines.forEach(engine => {
            formData.append('engines', engine);
        });
        
        if (verbose) {
            console.log(`Using engines: ${engines.join(', ')}`);
        }
    }
    
    // Add prompt if specified
    if (prompt) {
        formData.append('prompt', prompt);
        
        if (verbose) {
            console.log(`Using prompt: ${prompt}`);
        }
    }
    
    // Prepare headers
    const headers = {
        'X-API-Key': apiKey
        // No Content-Type header - let the browser set it for FormData
    };
    
    if (verbose) {
        console.log('Sending request with headers:', headers);
        console.log(`File details: ${file.name}, ${file.type}, ${file.size} bytes`);
    }
    
    try {
        // Send the request
        const response = await fetch(`${serverUrl}${endpoint}`, {
            method: 'POST',
            headers: headers,
            body: formData
        });
        
        if (verbose) {
            console.log(`Response status: ${response.status}`);
            console.log('Response headers:', Object.fromEntries([...response.headers.entries()]));
        }
        
        if (!response.ok) {
            const errorText = await response.text();
            if (verbose) {
                console.error(`Request failed: ${response.status} - ${errorText}`);
            }
            throw new Error(`API request failed: ${response.status} - ${errorText}`);
        }
        
        const result = await response.json();
        
        if (verbose) {
            console.log('Request successful!');
        }
        
        return result;
    } catch (error) {
        if (verbose) {
            console.error('Error in processLocalImage:', error);
        }
        throw error;
    }
}

/**
 * Process an image using the VoucherVision API with an image URL
 * 
 * @param {string} imageUrl - URL of the image to process
 * @param {string} apiKey - API key for VoucherVision
 * @param {string[]} engines - Array of OCR engines to use
 * @param {string} prompt - Custom prompt file to use
 * @param {boolean} verbose - Whether to log detailed information
 * @returns {Promise} - Promise that resolves with the API response
 */
async function processImageUrl(imageUrl, apiKey, engines = ['gemini-1.5-pro', 'gemini-2.0-flash'], prompt = 'SLTPvM_default.yaml', verbose = false) {
    const serverUrl = 'https://vouchervision-go-738307415303.us-central1.run.app';
    const endpoint = '/process-url';
    
    if (verbose) {
        console.log(`Processing image URL: ${imageUrl}`);
        console.log(`Server URL: ${serverUrl}${endpoint}`);
    }
    
    // Create request data
    const requestData = {
        image_url: imageUrl
    };
    
    // Add engines if specified
    if (engines && engines.length) {
        requestData.engines = engines;
        
        if (verbose) {
            console.log(`Using engines: ${engines.join(', ')}`);
        }
    }
    
    // Add prompt if specified
    if (prompt) {
        requestData.prompt = prompt;
        
        if (verbose) {
            console.log(`Using prompt: ${prompt}`);
        }
    }
    
    // Prepare headers
    const headers = {
        'X-API-Key': apiKey,
        'Content-Type': 'application/json'
    };
    
    if (verbose) {
        console.log('Sending request with headers:', headers);
        console.log('Request data:', requestData);
    }
    
    try {
        // Send the request
        const response = await fetch(`${serverUrl}${endpoint}`, {
            method: 'POST',
            headers: headers,
            body: JSON.stringify(requestData)
        });
        
        if (verbose) {
            console.log(`Response status: ${response.status}`);
            console.log('Response headers:', Object.fromEntries([...response.headers.entries()]));
        }
        
        if (!response.ok) {
            const errorText = await response.text();
            if (verbose) {
                console.error(`Request failed: ${response.status} - ${errorText}`);
            }
            throw new Error(`API request failed: ${response.status} - ${errorText}`);
        }
        
        const result = await response.json();
        
        if (verbose) {
            console.log('Request successful!');
        }
        
        return result;
    } catch (error) {
        if (verbose) {
            console.error('Error in processImageUrl:', error);
        }
        throw error;
    }
}

/**
 * Process an image URL by first downloading it and then uploading to the API
 * This is a workaround if the server doesn't support the /process-url endpoint
 * 
 * @param {string} imageUrl - URL of the image to process
 * @param {string} apiKey - API key for VoucherVision
 * @param {string[]} engines - Array of OCR engines to use
 * @param {string} prompt - Custom prompt file to use
 * @param {boolean} verbose - Whether to log detailed information
 * @returns {Promise} - Promise that resolves with the API response
 */
async function processImageUrlWorkaround(imageUrl, apiKey, engines = ['gemini-1.5-pro', 'gemini-2.0-flash'], prompt = 'SLTPvM_default.yaml', verbose = false) {
    try {
        if (verbose) {
            console.log(`Using URL download workaround for: ${imageUrl}`);
            console.log('This method first downloads the image then uploads it to the API');
        }
        
        // First fetch the image - note that this might not work for cross-origin images
        // without proper CORS headers on the image server
        const imageResponse = await fetch(imageUrl);
        if (!imageResponse.ok) {
            const errorMessage = `Failed to fetch image: ${imageResponse.status}`;
            if (verbose) {
                console.error(errorMessage);
            }
            throw new Error(errorMessage);
        }
        
        // Get the image as a blob
        const imageBlob = await imageResponse.blob();
        
        if (verbose) {
            console.log(`Downloaded image: ${imageBlob.type}, ${imageBlob.size} bytes`);
        }
        
        // Get filename from URL
        const filename = imageUrl.split('/').pop() || 'image.jpg';
        
        // Create a File object from the blob
        const file = new File([imageBlob], filename, { type: imageBlob.type });
        
        if (verbose) {
            console.log(`Created file object: ${file.name}`);
        }
        
        // Use the processLocalImage function to upload the file
        return await processLocalImage(file, apiKey, engines, prompt, verbose);
    } catch (error) {
        if (verbose) {
            console.error('Error in processImageUrlWorkaround:', error);
        }
        throw error;
    }
}

// Example usage for browsers
document.addEventListener('DOMContentLoaded', () => {
    // Set verbose logging to true for all examples
    const verbose = true;
    
    // Get DOM elements
    const fileInput = document.getElementById('imageInput');
    const processButton = document.getElementById('processButton');
    const urlInput = document.getElementById('imageUrlInput');
    const processUrlButton = document.getElementById('processUrlButton');
    const apiKeyInput = document.getElementById('apiKeyInput');
    const resultsDiv = document.getElementById('results');
    const verboseCheckbox = document.getElementById('verboseCheckbox');
    
    // Use default verbose value if checkbox doesn't exist
    let isVerbose = verbose;
    if (verboseCheckbox) {
        verboseCheckbox.checked = verbose;
        verboseCheckbox.addEventListener('change', () => {
            isVerbose = verboseCheckbox.checked;
        });
    }
    
    // Process local file example
    if (processButton) {
        processButton.addEventListener('click', async () => {
            if (!fileInput.files.length) {
                alert('Please select a file first');
                return;
            }
            
            const apiKey = apiKeyInput.value;
            if (!apiKey) {
                alert('Please enter your API key');
                return;
            }
            
            try {
                resultsDiv.innerHTML = '<div class="loading">Processing...</div>';
                
                const result = await processLocalImage(
                    fileInput.files[0], 
                    apiKey,
                    ['gemini-1.5-pro', 'gemini-2.0-flash'],
                    'SLTPvM_default.yaml',
                    isVerbose
                );
                
                resultsDiv.innerHTML = '<pre>' + JSON.stringify(result, null, 2) + '</pre>';
            } catch (error) {
                resultsDiv.innerHTML = `<div class="error">Error: ${error.message}</div>`;
            }
        });
    }
    
    // Process image URL example
    if (processUrlButton) {
        processUrlButton.addEventListener('click', async () => {
            const imageUrl = urlInput.value;
            if (!imageUrl) {
                alert('Please enter an image URL');
                return;
            }
            
            const apiKey = apiKeyInput.value;
            if (!apiKey) {
                alert('Please enter your API key');
                return;
            }
            
            try {
                resultsDiv.innerHTML = '<div class="loading">Processing...</div>';
                
                let result;
                // Try direct URL endpoint first, fallback to workaround if needed
                try {
                    result = await processImageUrl(
                        imageUrl,
                        apiKey,
                        ['gemini-1.5-pro', 'gemini-2.0-flash'],
                        'SLTPvM_default.yaml',
                        isVerbose
                    );
                } catch (directUrlError) {
                    if (isVerbose) {
                        console.warn('Direct URL processing failed, trying workaround:', directUrlError);
                        resultsDiv.innerHTML += '<div>Direct URL processing failed, trying workaround...</div>';
                    }
                    
                    // Fallback to the workaround method
                    result = await processImageUrlWorkaround(
                        imageUrl,
                        apiKey,
                        ['gemini-1.5-pro', 'gemini-2.0-flash'],
                        'SLTPvM_default.yaml',
                        isVerbose
                    );
                }
                
                resultsDiv.innerHTML = '<pre>' + JSON.stringify(result, null, 2) + '</pre>';
            } catch (error) {
                resultsDiv.innerHTML = `<div class="error">Error: ${error.message}</div>`;
            }
        });
    }
    
    // Log that the script is loaded
    if (verbose) {
        console.log('VoucherVision API client script loaded and initialized');
        console.log('Verbose logging is enabled');
    }
});

// Example in Node.js environment
// Note: This code would run in Node.js, not in browser
/*
const fetch = require('node-fetch');
const FormData = require('form-data');
const fs = require('fs');

async function nodeExample() {
    const apiKey = 'YOUR_API_KEY';
    const imageUrl = 'https://example.com/image.jpg';
    const localImagePath = './local-image.jpg';
    const verbose = true;
    
    try {
        // Example: Process URL
        console.log("\n--- Processing image URL ---");
        const urlData = {
            image_url: imageUrl,
            engines: ['gemini-1.5-pro', 'gemini-2.0-flash'],
            prompt: 'SLTPvM_default.yaml'
        };
        
        const urlResponse = await fetch('https://vouchervision-go-738307415303.us-central1.run.app/process-url', {
            method: 'POST',
            headers: {
                'X-API-Key': apiKey,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(urlData)
        });
        
        if (!urlResponse.ok) {
            throw new Error(`URL processing failed: ${urlResponse.status}`);
        }
        
        const urlResult = await urlResponse.json();
        console.log('URL processing successful!');
        console.log(urlResult);
        
        // Example: Process local file
        console.log("\n--- Processing local image ---");
        const formData = new FormData();
        formData.append('file', fs.createReadStream(localImagePath));
        formData.append('engines', 'gemini-1.5-pro');
        formData.append('engines', 'gemini-2.0-flash');
        formData.append('prompt', 'SLTPvM_default.yaml');
        
        const fileResponse = await fetch('https://vouchervision-go-738307415303.us-central1.run.app/process', {
            method: 'POST',
            headers: {
                'X-API-Key': apiKey,
                ...formData.getHeaders()
            },
            body: formData
        });
        
        if (!fileResponse.ok) {
            throw new Error(`File processing failed: ${fileResponse.status}`);
        }
        
        const fileResult = await fileResponse.json();
        console.log('File processing successful!');
        console.log(fileResult);
        
    } catch (error) {
        console.error('Error in example:', error);
    }
}
*/