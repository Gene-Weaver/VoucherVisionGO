// VoucherVision API Test Scripts

// Animated processing loader
const VV_LOADER_MESSAGES = [
    'Reading specimen label\u2026',
    'Analyzing handwriting\u2026',
    'Parsing collector info\u2026',
    'Extracting locality data\u2026',
    'Structuring results\u2026',
    'Verifying taxonomy\u2026',
    'Deciphering dates\u2026',
    'Almost there\u2026',
];

function vvLoaderHTML() {
    return `<div class="vv-loader">
        <div class="vv-loader-leaf">
            <span></span><span></span><span></span><span></span><span></span>
        </div>
        <div class="vv-loader-text"><span>${VV_LOADER_MESSAGES[0]}</span></div>
    </div>`;
}

// Cycle through loader messages
let _vvLoaderInterval = null;
function startLoaderCycle(container) {
    let idx = 0;
    _vvLoaderInterval = setInterval(() => {
        idx = (idx + 1) % VV_LOADER_MESSAGES.length;
        const txt = container.querySelector('.vv-loader-text span');
        if (txt) {
            txt.style.opacity = '0';
            setTimeout(() => {
                txt.textContent = VV_LOADER_MESSAGES[idx];
                txt.style.opacity = '1';
            }, 300);
        }
    }, 3000);
}
function stopLoaderCycle() {
    if (_vvLoaderInterval) { clearInterval(_vvLoaderInterval); _vvLoaderInterval = null; }
}

function setButtonProcessing(selector, processing) {
    const btn = $(selector);
    if (processing) {
        btn.prop('disabled', true).addClass('vv-processing').attr('data-processing-text', 'Processing\u2026');
    } else {
        btn.prop('disabled', false).removeClass('vv-processing').removeAttr('data-processing-text').text('Run VoucherVision');
    }
}

// ── Result history (single-image runs) ──
const resultHistory = [];  // [{label, html, data}]
let activeResultIndex = -1;

function addResultToHistory(label, html, data) {
    resultHistory.push({ label, html, data });
    activeResultIndex = resultHistory.length - 1;
    renderHistoryDropdown();
    showResultByIndex(activeResultIndex);
}

function renderHistoryDropdown() {
    const bar = document.getElementById('resultHistoryBar');
    const sel = document.getElementById('resultHistorySelect');
    if (!bar || !sel) return;
    if (resultHistory.length <= 1) {
        bar.style.display = 'none';
        return;
    }
    bar.style.display = 'flex';
    sel.innerHTML = resultHistory.map((r, i) =>
        `<option value="${i}"${i === activeResultIndex ? ' selected' : ''}>${r.label}</option>`
    ).join('');
}

function showResultByIndex(idx) {
    if (idx < 0 || idx >= resultHistory.length) return;
    activeResultIndex = idx;
    const entry = resultHistory[idx];
    $('#singleResults').html(entry.html);
    // Re-wire tab switching inside results
    setupResultsInteractions('single');
    // Update map to match the active result
    if (window.updateMapFromData) {
        window.updateMapFromData(entry.data);
    }
}

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
        // Build auth headers so we actually validate the API key or token
        const headers = getAuthHeaders();

        logDebug(`Testing authentication against: https://vouchervision-go-738307415303.us-central1.run.app/auth-check`);

        corsStatusElement.textContent = 'Testing authentication...';
        corsStatusElement.className = 'status-display';

        const response = await fetch('https://vouchervision-go-738307415303.us-central1.run.app/auth-check', {
            method: 'GET',
            headers: headers
        });

        logDebug(`Auth check response status: ${response.status}`);

        if (response.ok) {
            const result = await response.json();
            corsStatusElement.textContent = 'Authentication successful!';
            corsStatusElement.className = 'status-display cors-success';

            logDebug('Auth check successful:', result);
            return true;
        } else {
            const statusMsg = response.status === 401
                ? 'Invalid API key or token'
                : `Auth check failed: ${response.status}`;
            corsStatusElement.textContent = statusMsg;
            corsStatusElement.className = 'status-display cors-error';

            logDebug(`Auth check failed: ${response.status}`);
            return false;
        }
    } catch (error) {
        corsStatusElement.textContent = `Connection error: ${error.message}`;
        corsStatusElement.className = 'status-display cors-error';

        logDebug('Auth check error:', error);
        return false;
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
    $('#uploadButton').click(() => processImage('file'));
    $('#processUrlButton').click(() => processImage('url'));

    // Result history dropdown
    $('#resultHistorySelect').on('change', function() {
        showResultByIndex(parseInt(this.value, 10));
    });

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
    const notebookMode = $('#notebookMode').is(':checked');
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
    if (notebookMode) formData.append('notebook_mode', 'true');
    if (llm_model) formData.append('llm_model', llm_model);
    if ($('#includeWfo').is(':checked')) formData.append('include_wfo', 'true');
    if ($('#includeCop90').is(':checked')) formData.append('include_cop90', 'true');
    if ($('#skipLabelCollage').is(':checked')) formData.append('skip_label_collage', 'true');

    const headers = getAuthHeaders();
    if ('Content-Type' in headers) delete headers['Content-Type'];

    // Choose the correct endpoint
    const endpoint = (sourceType === 'file') 
        ? 'https://vouchervision-go-738307415303.us-central1.run.app/process'
        : 'https://vouchervision-go-738307415303.us-central1.run.app/process-url';

    // Determine a human-readable label for this run
    let resultLabel;
    if (sourceType === 'file') {
        resultLabel = document.getElementById('fileInput').files[0].name;
    } else {
        resultLabel = $('#imageUrl').val();
    }

    // Disable buttons & show animated loader during processing
    const buttonSelector = (sourceType === 'file') ? '#uploadButton' : '#processUrlButton';
    setButtonProcessing(buttonSelector, true);
    $('#singleResults').html(vvLoaderHTML());
    startLoaderCycle($('#singleResults')[0]);

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

        // Create split layout for results
        const resultsHTML = createSplitResultsLayout(data);

        // Add to history and display
        addResultToHistory(resultLabel, resultsHTML, data);

    } catch (error) {
        logDebug('API response error', { error: error.toString() });
        $('#singleResults').html(`
            <h3 class="error">Error:</h3>
            <p>${error.message}</p>
        `);
    } finally {
        stopLoaderCycle();
        setButtonProcessing(buttonSelector, false);
    }
}


// Build the formatted summary tab content from API response data
function buildFormattedSummary(data) {
    let sections = '';

    // OCR text
    if (data.ocr) {
        sections += `
            <div class="formatted-section">
                <h4>OCR Text</h4>
                <pre class="formatted-value">${typeof data.ocr === 'string' ? data.ocr.replace(/</g, '&lt;').replace(/>/g, '&gt;') : JSON.stringify(data.ocr, null, 2)}</pre>
            </div>`;
    }

    // Formatted JSON (parsed label fields)
    if (data.formatted_json && typeof data.formatted_json === 'object' && Object.keys(data.formatted_json).length > 0) {
        let tableRows = '';
        for (const [key, val] of Object.entries(data.formatted_json)) {
            const display = (val === null || val === undefined || val === '') ? '<span style="color:#999;">—</span>' : String(val).replace(/</g, '&lt;').replace(/>/g, '&gt;');
            tableRows += `<tr><td style="font-weight:600; white-space:nowrap; vertical-align:top; padding:4px 12px 4px 0;">${key}</td><td style="padding:4px 0;">${display}</td></tr>`;
        }
        sections += `
            <div class="formatted-section">
                <h4>Parsed Label Fields</h4>
                <table style="width:100%; border-collapse:collapse; font-size:0.92rem;">${tableRows}</table>
            </div>`;
    }

    // Formatted markdown
    if (data.formatted_md && typeof data.formatted_md === 'string' && data.formatted_md.trim()) {
        sections += `
            <div class="formatted-section">
                <h4>Formatted Markdown</h4>
                <pre class="formatted-value">${data.formatted_md.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</pre>
            </div>`;
    }

    if (!sections) {
        sections = '<p style="color:#888;">No formatted data available.</p>';
    }

    return sections;
}

// Build the Data Enrichment tab content (WFO + COP90)
function buildEnrichmentSummary(data) {
    let sections = '';

    // WFO info
    if (data.WFO_info && typeof data.WFO_info === 'object' && Object.keys(data.WFO_info).length > 0) {
        let wfoRows = '';
        for (const [key, val] of Object.entries(data.WFO_info)) {
            const display = (val === null || val === undefined || val === '') ? '<span style="color:#999;">\u2014</span>' : String(val).replace(/</g, '&lt;').replace(/>/g, '&gt;');
            wfoRows += `<tr><td style="font-weight:600; white-space:nowrap; vertical-align:top; padding:4px 12px 4px 0;">${key}</td><td style="padding:4px 0;">${display}</td></tr>`;
        }
        sections += `
            <div class="formatted-section">
                <h4>WFO Validation</h4>
                <table style="width:100%; border-collapse:collapse; font-size:0.92rem;">${wfoRows}</table>
            </div>`;
    }

    // COP90 elevation
    if (data.COP90_elevation_m !== undefined && data.COP90_elevation_m !== null) {
        sections += `
            <div class="formatted-section">
                <h4>COP90 Elevation</h4>
                <p style="font-size:1.1rem; font-weight:600; margin:4px 0;">${data.COP90_elevation_m} m</p>
            </div>`;
    }

    if (!sections) {
        sections = '<p style="color:#888;">No enrichment data available. Enable WFO validation or COP90 elevation in Step 4.</p>';
    }

    return sections;
}

// Create split layout with JSON on left and image on right
function createSplitResultsLayout(data) {
    const hasCollageImage = data.collage_info && data.collage_info.base64image_text_collage;
    const hasMd = $('#notebookMode').is(':checked') && typeof data.formatted_md === 'string' && data.formatted_md.trim();

    let html = `
        <div class="split-results-container">
            <div class="json-result-container">
                <div class="json-controls">
                    <button class="button copy-btn" onclick="copyJsonToClipboard()">Copy JSON</button>
                    <button class="button download-btn" onclick="downloadJson()">Download JSON</button>
                    ${hasMd ? `<button class="button download-btn" onclick="downloadFormattedMarkdown()">Download Markdown (.md)</button>` : ``}
                </div>
                <div class="result-tabs">
                    <div class="result-tab active" data-result-tab="formatted">Formatted</div>
                    <div class="result-tab" data-result-tab="enrichment">Data Enrichment</div>
                    <div class="result-tab" data-result-tab="rawjson">Full API Response</div>
                </div>
                <div class="result-tab-content active" id="resultTabFormatted">
                    ${buildFormattedSummary(data)}
                </div>
                <div class="result-tab-content" id="resultTabEnrichment">
                    ${buildEnrichmentSummary(data)}
                </div>
                <div class="result-tab-content" id="resultTabRawJson">
                    <div class="json-content">${JSON.stringify(data, null, 2)}</div>
                </div>
            </div>
    `;

    // Add image container on the right
    html += `
            <div class="image-result-container">
                <h4>Text Collage</h4>
    `;

    if (hasCollageImage) {
        html += `
                <img src="data:image/jpeg;base64,${data.collage_info.base64image_text_collage}"
                     class="processed-image"
                     alt="Processed Collage"
                     onclick="openImageModal(this)" />
                <div class="image-actions">
                    <button class="button" onclick="downloadCollageImage('${data.collage_info.base64image_text_collage}')">Download Image</button>
                </div>
        `;
    } else {
        html += `
                <div class="no-image-msg">
                    Text Collage image not available.
                </div>
        `;
    }

    html += `
            </div>
        </div>
    `;

    return html;
}

// Set up interactive features for the results
function setupResultsInteractions() {
    const resultsContainer = '#singleResults';
    const jsonContent = $(resultsContainer + ' .json-content').text();

    // Store data in a global variable for access by other functions
    try { window.currentResultData = JSON.parse(jsonContent); } catch(_) {}

    // Wire up result tab switching (Formatted / Raw JSON)
    $(resultsContainer + ' .result-tab').off('click').on('click', function() {
        const parent = $(this).closest('.json-result-container');
        parent.find('.result-tab').removeClass('active');
        parent.find('.result-tab-content').removeClass('active');
        $(this).addClass('active');
        const tabId = $(this).data('result-tab');
        const tabMap = { formatted: '#resultTabFormatted', enrichment: '#resultTabEnrichment', rawjson: '#resultTabRawJson' };
        parent.find(tabMap[tabId] || '#resultTabFormatted').addClass('active');
    });
}

// Copy JSON to clipboard
function copyJsonToClipboard() {
    if (window.currentResultData) {
        const jsonText = JSON.stringify(window.currentResultData, null, 2);
        
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(jsonText).then(() => {
                showTemporaryMessage('JSON copied to clipboard!');
            }).catch(err => {
                console.error('Failed to copy: ', err);
                fallbackCopyToClipboard(jsonText);
            });
        } else {
            fallbackCopyToClipboard(jsonText);
        }
    }
}

// Fallback copy method for older browsers
function fallbackCopyToClipboard(text) {
    const textArea = document.createElement('textarea');
    textArea.value = text;
    textArea.style.position = 'fixed';
    textArea.style.left = '-999999px';
    textArea.style.top = '-999999px';
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    
    try {
        document.execCommand('copy');
        showTemporaryMessage('JSON copied to clipboard!');
    } catch (err) {
        console.error('Fallback copy failed: ', err);
        showTemporaryMessage('Copy failed. Please select and copy manually.');
    }
    
    document.body.removeChild(textArea);
}

// Download JSON file
function downloadJson() {
    if (window.currentResultData) {
        const jsonText = JSON.stringify(window.currentResultData, null, 2);
        const blob = new Blob([jsonText], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `vouchervision_result_${Date.now()}.json`;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => {
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        }, 100);
    }
}

// Download OCR as Markdown (.md)
function downloadFormattedMarkdown() {
    if (!window.currentResultData) return;

    // Prefer new field; fall back for backward compatibility
    const md = (typeof window.currentResultData.formatted_md === 'string' && window.currentResultData.formatted_md.trim())
        ? window.currentResultData.formatted_md.trim()
        : (typeof window.currentResultData.ocr === 'string' ? window.currentResultData.ocr.trim() : '');

    if (!md) {
        showTemporaryMessage('No Markdown available to download.');
        return;
    }

    const base = (window.currentResultData.filename || 'vouchervision_ocr').replace(/\.[^/.]+$/, '');
    const mdName = `${base}.md`;

    const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = mdName;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }, 100);
}

// Download collage image
function downloadCollageImage(base64Data) {
    const link = document.createElement('a');
    link.href = `data:image/jpeg;base64,${base64Data}`;
    link.download = `vouchervision_collage_${Date.now()}.jpg`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// Step Info Popup data and functions
const STEP_INFO = {
    step1: {
        title: 'Model & Mode Selection',
        number: '1',
        sections: [
            { title: 'Recommendations', body: 'Use <strong><code>gemini-3.1-flash-lite-preview</code></strong> for both OCR and parsing\u2014it performs comparably to more expensive models at a fraction of the cost.<br><br><strong><code>gemini-3.1-pro-preview</code></strong> is limited to 100 calls per user.' },
            { title: 'OCR', body: 'VoucherVision uses vision language models to perform optical character recognition (OCR). Generally, this is the accuracy-limiting step: if the OCR text is inaccurate, parsing will inevitably struggle as well. Prior to the Gemini 3.1 model family, we recommended using Gemini Pro models for OCR and Flash models for parsing. However, we now recommend <code>gemini-3.1-flash-lite-preview</code> for both steps due to its exceptional cost-to-performance ratio.<br><br>OCR models also detect handwritten text (\u00ABhandwritten\u00BB) and stricken text (\u00A7stricken\u00A7) using these special characters to inform the parsing LLM, but are removed from the final API response.' },
            { title: 'LLMs', body: 'The selected LLM parses unstructured OCR text into structured JSON, which can then be transformed into a spreadsheet. Generally, <code>gemini-3.1-flash-lite-preview</code> is quite capable for this task. Gemini Pro models should be reserved for particularly challenging or atypical prompts.' },
            { title: 'Processing Options', body: 'VoucherVision supports several alternative modes. <strong>OCR Only Mode</strong> returns raw OCR text without JSON parsing. <strong>Notebook Mode</strong> is experimental and designed for full-page text images like field notebooks\u2014it returns Markdown files instead of JSON. <strong>Skip Label Collage</strong> should be used if your image is primarily text or if you observe the Text Collage cutting off parts of the text.' }
        ]
    },
    step2: {
        title: 'Data Enrichment',
        number: '2',
        sections: [
            { title: 'What is data enrichment?', body: 'Data enrichment adds supplemental information from third-party sources. These are returned as additional fields in the JSON response and do not override any of the actual label text. You can use this information for post-processing or quality control.' },
            { title: 'World Flora Online', body: 'Validates plant names against the <a href="https://www.worldfloraonline.org/" target="_blank">World Flora Online</a> (WFO) taxonomic backbone and provides taxonomic corrections, accepted name status, and classification hierarchy.' },
            { title: 'Copernicus GLO-90 Elevation', body: 'Returns elevation (m) from specimen coordinates using the Copernicus GLO-90 Digital Surface Model (90 m resolution), derived from the TanDEM-X mission (DLR/Airbus) and distributed by ESA via <a href="https://portal.opentopography.org/raster?opentopoID=OTSDEM.032021.4326.1" target="_blank">OpenTopography</a>.<br><br><span style="font-size:0.85em; color:#666;">Contains modified Copernicus data (2011\u20132015). \u00a9 DLR e.V. 2010\u20132014 and \u00a9 Airbus Defence and Space GmbH 2014\u20132018, provided under Copernicus by the European Union and ESA.</span>' }
        ]
    },
    step3: {
        title: 'Prompt Template',
        number: '3',
        sections: [
            { title: 'What are prompt templates?', body: "Prompt templates provide VoucherVision with instructions on how to parse the unstructured OCR text into your desired field names. You can browse the available prompts by clicking <strong>Available Prompts</strong> at the top of the page. We regularly modify and customize prompts for users. If you want something different, please reach out to the VoucherVision team and we'll make it happen." }
        ]
    },
    step4: {
        title: 'Process Images',
        number: '4',
        sections: [
            { title: 'Selecting images to transcribe with VoucherVision', body: 'This website is designed to get you familiar with VoucherVision or to run a few images at a time. If you want to run VoucherVision regularly or for large batches (more than a few hundred images), you should use the <strong><a href="https://pypi.org/project/vouchervision-go-client/" target="_blank">Python package</a></strong> or call the API directly. Learn more on the <strong>About</strong> page.' },
            { title: 'PDF Support', body: 'You can upload PDF files directly\u2014each page is automatically converted to a JPG and processed as a separate specimen image. Multi-page PDFs (up to 200 pages) are fully supported. All processing options (Text Collage, Notebook Mode, Skip Label Collage) apply to each page individually. For large PDFs, we recommend using the <strong><a href="https://pypi.org/project/vouchervision-go-client/" target="_blank">Python package</a></strong>, which converts pages locally and processes them in parallel for much faster results.' }
        ]
    },
    step5: {
        title: 'VoucherVision Results',
        number: '5',
        sections: [
            { title: 'What do I do with the VoucherVision output?', body: 'On this webpage, you can download the JSON output. However, VoucherVision is designed to export data directly to spreadsheets. For regular use or large batches, please use the <strong><a href="https://pypi.org/project/vouchervision-go-client/" target="_blank">Python package</a></strong> to call the API\u2014it will make your life easier! Please ask the VoucherVision team for reference Python scripts if you want help.' },
            { title: 'Text Collage', body: 'Every VoucherVision response contains a base-64 image (in the field <code>base64image_text_collage</code>) that you can save to a .jpg file later. If you used the <strong>Text Collage</strong>, this will be the collage image. If you used <strong>Notebook Mode</strong> or skipped the Text Collage, it will be the full input image (but possibly resized).' },
            { title: 'Bounding Boxes', body: 'The API response also includes the bounding boxes (<code>position_original</code>) of <strong>LeafMachine2</strong> archival classes of the objects found in the image, e.g. ruler, barcode, label, colorcard, envelope, weights, etc.' }
        ]
    }
};

function openStepInfoPopup(stepKey) {
    const info = STEP_INFO[stepKey];
    if (!info) return;

    const sectionsHTML = info.sections.map(s =>
        `<div class="step-info-section"><h4>${s.title}</h4><p>${s.body}</p></div>`
    ).join('');

    const overlay = document.createElement('div');
    overlay.className = 'step-info-overlay';
    overlay.innerHTML = `
        <div class="step-info-popup">
            <div class="step-info-popup-header">
                <span class="step-number">${info.number}</span>
                <h3>${info.title}</h3>
                <button class="step-info-popup-close" onclick="closeStepInfoPopup()">×</button>
            </div>
            <div class="step-info-popup-body">
                ${sectionsHTML}
            </div>
        </div>
    `;

    document.body.appendChild(overlay);
    window._stepInfoOverlay = overlay;

    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) closeStepInfoPopup();
    });

    window._stepInfoEscHandler = function(e) {
        if (e.key === 'Escape') closeStepInfoPopup();
    };
    document.addEventListener('keydown', window._stepInfoEscHandler);
}

function closeStepInfoPopup() {
    if (window._stepInfoOverlay) {
        document.body.removeChild(window._stepInfoOverlay);
        window._stepInfoOverlay = null;
    }
    if (window._stepInfoEscHandler) {
        document.removeEventListener('keydown', window._stepInfoEscHandler);
        window._stepInfoEscHandler = null;
    }
}

// Download the Step 4 preview image
function downloadPreviewImage() {
    const src = window._step4PreviewSrc;
    if (!src) return;
    const link = document.createElement('a');
    link.href = src;
    link.download = 'vouchervision_preview_' + Date.now() + '.jpg';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// Open image in modal for full-size viewing
function openImageModal(img) {
    const modal = document.createElement('div');
    modal.className = 'image-modal-overlay';
    modal.innerHTML = `
        <div class="image-modal-content">
            <button class="image-modal-close" onclick="closeImageModal()">×</button>
            <img src="${img.src}" alt="Full Size Image" class="image-modal-img">
            <div class="image-modal-actions">
                <button class="button" onclick="downloadModalImage()">Download Image</button>
            </div>
        </div>
    `;

    // Store src for modal download
    window._modalImageSrc = img.src;

    document.body.appendChild(modal);

    // Close modal when clicking outside the image
    modal.addEventListener('click', function(e) {
        if (e.target === modal) {
            closeImageModal();
        }
    });

    // Close on Escape key
    window._modalEscHandler = function(e) {
        if (e.key === 'Escape') closeImageModal();
    };
    document.addEventListener('keydown', window._modalEscHandler);

    // Store reference to modal for closing
    window.currentImageModal = modal;
}

// Download image from modal
function downloadModalImage() {
    const src = window._modalImageSrc;
    if (!src) return;
    const link = document.createElement('a');
    link.href = src;
    link.download = 'vouchervision_image_' + Date.now() + '.jpg';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// Close image modal
function closeImageModal() {
    if (window.currentImageModal) {
        document.body.removeChild(window.currentImageModal);
        window.currentImageModal = null;
    }
    if (window._modalEscHandler) {
        document.removeEventListener('keydown', window._modalEscHandler);
        window._modalEscHandler = null;
    }
    window._modalImageSrc = null;
}

// Show temporary message
function showTemporaryMessage(message, duration = 2000) {
    const messageDiv = document.createElement('div');
    messageDiv.textContent = message;
    messageDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background-color: #4CAF50;
        color: white;
        padding: 10px 20px;
        border-radius: 4px;
        z-index: 1000;
        box-shadow: 0 2px 10px rgba(0,0,0,0.2);
    `;
    
    document.body.appendChild(messageDiv);
    
    setTimeout(() => {
        if (document.body.contains(messageDiv)) {
            document.body.removeChild(messageDiv);
        }
    }, duration);
}