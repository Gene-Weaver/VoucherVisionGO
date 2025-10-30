// Utility function to convert CSV data to structured object
async function parseCSV(csvContent, urlColumnName = 'url') {
    return new Promise((resolve, reject) => {
        try {
            // Parse CSV using Papa Parse
            Papa.parse(csvContent, {
                header: true,
                skipEmptyLines: true,
                complete: function(results) {
                    // Check if the URL column exists
                    if (results.data.length > 0) {
                        if (!results.data[0].hasOwnProperty(urlColumnName)) {
                            // Try to find a column that might contain URLs
                            const columns = Object.keys(results.data[0]);
                            const possibleUrlColumns = columns.filter(col => 
                                col.toLowerCase().includes('url') || 
                                col.toLowerCase().includes('link') ||
                                col.toLowerCase().includes('image')
                            );

                            if (possibleUrlColumns.length > 0) {
                                // Use the first column that might contain URLs
                                urlColumnName = possibleUrlColumns[0];
                                logDebug(`URL column "${urlColumnName}" auto-detected in CSV`);
                            } else {
                                reject(`Column "${urlColumnName}" not found in CSV. Available columns: ${columns.join(', ')}`);
                                return;
                            }
                        }

                        // Extract URLs from the specified column
                        const urls = results.data.map(row => {
                            // Keep the original row data and add a clean URL
                            return {
                                original: row,
                                url: row[urlColumnName]?.trim()
                            };
                        }).filter(item => item.url); // Remove empty URLs

                        resolve({
                            urls: urls,
                            originalData: results.data,
                            headers: results.meta.fields
                        });
                    } else {
                        reject('No data found in CSV file');
                    }
                },
                error: function(error) {
                    reject(`Error parsing CSV: ${error}`);
                }
            });
        } catch (error) {
            reject(`Error in parseCSV: ${error.message}`);
        }
    });
}

// Parse TXT file with one URL per line
function parseTXT(txtContent) {
    // Split by newlines and filter out empty lines
    const lines = txtContent.split(/\r?\n/).map(line => line.trim()).filter(line => line);
    
    // Create structured data with URLs
    const urls = lines.map(url => ({
        original: { url: url },
        url: url
    }));
    
    return {
        urls: urls,
        originalData: lines,
        headers: ['url']
    };
}

// Check if a string is a valid URL
function isValidUrl(string) {
    try {
        new URL(string);
        return true;
    } catch (_) {
        return false;
    }
}

// Process a batch of URLs with controlled concurrency
async function processBatchUrls(urls, concurrency, options = {}) {
    const results = [];
    const errors = [];
    const totalCount = urls.length;
    let completedCount = 0;
    
    // Update the progress bar
    function updateProgress() {
        const progressPercent = (completedCount / totalCount) * 100;
        $('.batch-progress .progress-bar').css('width', `${progressPercent}%`);
        $('.batch-progress .progress-count').text(`${completedCount}/${totalCount}`);
        
        if (completedCount === totalCount) {
            $('.batch-progress .progress-text').html(`<strong>Processing complete!</strong>`);
        } else {
            $('.batch-progress .progress-text').text(`Processing ${completedCount} of ${totalCount} URLs...`);
        }
    }
    
    // Process a single URL
    async function processUrl(urlData) {
        const url = urlData.url;
        try {
            logDebug(`Processing URL: ${url}`);
    
            // Get authentication headers
            const headers = getAuthHeaders();
    
            // Get the selected LLM model
            const llm_model = getSelectedModel();
    
            // Build request body
            const formData = new FormData();
            formData.append('image_url', url);
    
            // Add selected engines
            getSelectedEngines().forEach(engine => {
                formData.append('engines', engine);
            });
    
            // Add OCR only mode if selected
            if ($('#ocrOnly').is(':checked')) {
                formData.append('ocr_only', 'true');
            }

            if ($('#notebookMode').is(':checked')) {
                formData.append('notebook_mode', 'true');
            }
    
            if ($('#includeWfo').is(':checked')) {
                formData.append('include_wfo', 'true');
            }
    
            // Add prompt template if specified
            const promptTemplate = $('#promptTemplate').val();
            if (promptTemplate) {
                formData.append('prompt', promptTemplate);
            }
    
            // Add selected model - make sure to include this!
            if (llm_model) {
                formData.append('llm_model', llm_model);
            }
    
            // Remove Content-Type header as it will be set by the browser with form boundary
            if ('Content-Type' in headers) {
                delete headers['Content-Type'];
            }
    
            // Log what we're sending
            const formDataEntries = [];
            for (const pair of formData.entries()) {
                formDataEntries.push({ key: pair[0], value: pair[1] });
            }
            logDebug(`Request for URL ${url}:`, formDataEntries);
    
            // Make the API request
            const response = await fetch('https://vouchervision-go-738307415303.us-central1.run.app/process-url', {
                method: 'POST',
                headers: headers,
                body: formData
            });
    
            if (!response.ok) {
                throw new Error(`API error: ${response.status} ${response.statusText}`);
            }
    
            const data = await response.json();
    
            // Combine original data with API response
            const result = {
                url: url,
                originalData: urlData.original,
                apiResponse: data,
                success: true
            };
    
            results.push(result);
    
            // Add a preview thumbnail
            addUrlPreview(url, result);
    
            return result;
        } catch (error) {
            logDebug(`Error processing URL ${url}: ${error.message}`);
    
            const errorResult = {
                url: url,
                originalData: urlData.original,
                error: error.message,
                success: false
            };
    
            errors.push(errorResult);
            return errorResult;
        } finally {
            completedCount++;
            updateProgress();
        }
    }
    
    // Process URLs with controlled concurrency
    async function processInBatches() {
        // Initialize progress tracking
        $('.batch-progress').show();
        
        // Clear any previous download options
        $('.batch-progress .progress-download-options').remove();
        
        // Add download buttons (disabled initially)
        $('.batch-progress').append(`
            <div class="progress-download-options">
                <button id="downloadSummaryBtn" class="button" disabled>Download Summary CSV</button>
                <button id="downloadDetailedCsvBtn" class="button" disabled>Download Results CSV</button>
                <button id="downloadJsonFilesBtn" class="button" disabled>Download Results JSON</button>
                <button id="downloadFullJsonFilesBtn" class="button" disabled>Download Full JSON</button>
                <button id="downloadMdFilesBtn" class="button" disabled>Download Markdown</button>
            </div>
        `);
        
        updateProgress();
        
        // Clear previous results
        $('.url-preview-gallery').empty();
        $('#batchUrlResults').empty();
        
        // Process in batches with controlled concurrency
        const urlsToProcess = [...urls]; // Create a copy to avoid modifying the original
        const batchResults = [];
        
        while (urlsToProcess.length > 0) {
            // Take up to 'concurrency' items
            const batch = urlsToProcess.splice(0, concurrency);
            
            // Process the batch concurrently
            const batchPromises = batch.map(urlData => processUrl(urlData));
            const batchResult = await Promise.all(batchPromises);
            
            batchResults.push(...batchResult);
            
            // Update UI with each batch result
            batchResult.forEach(result => {
                renderResultItem(result);
            });
        }
        
        // Show summary in progress bar
        const successCount = results.length;
        const errorCount = errors.length;
        
        $('.batch-progress .progress-text').html(`
            <strong>Processing Complete</strong><br>
            Successfully processed: ${successCount} URLs<br>
            Errors: ${errorCount} URLs
        `);
        
        // Enable download buttons if we have results
        $('#downloadSummaryBtn').prop('disabled', false);
        
        if (successCount > 0) {
            $('#downloadDetailedCsvBtn, #downloadJsonFilesBtn, #downloadFullJsonFilesBtn').prop('disabled', false);
        }

        // Enable OCR Markdown when notebook mode + at least one OCR present
        const hasAnyMd = results.some(r =>
            r.success &&
            r.apiResponse &&
            (
                (typeof r.apiResponse.formatted_md === 'string' && r.apiResponse.formatted_md.trim()) ||
                (typeof r.apiResponse.ocr === 'string' && r.apiResponse.ocr.trim()) // fallback
            )
        );

        if ($('#notebookMode').is(':checked') && hasAnyMd) {
            $('#downloadMdFilesBtn').prop('disabled', false).off('click').on('click', async function() {
                try {
                    $(this).prop('disabled', true).text('Creating ZIP...');
                    const zipContent = await createMdZipArchive(results);
                    const url = URL.createObjectURL(zipContent);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `batch_markdown_${Date.now()}.zip`;
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(() => {
                        document.body.removeChild(a);
                        URL.revokeObjectURL(url);
                    }, 100);
                } catch (error) {
                    logDebug('Error creating Markdown ZIP', error);
                    alert(`Error creating ZIP archive: ${error.message}`);
                } finally {
                    $(this).prop('disabled', false).text('Download Markdown');
                }
            });
        }
        
        // Download Summary CSV
        $('#downloadSummaryBtn').click(function() {
            const csvContent = generateResultsSummaryCSV(results, errors);
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `batch_summary_${Date.now()}.csv`;
            document.body.appendChild(a);
            a.click();
            setTimeout(() => {
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }, 100);
        });
        
        // Download Detailed CSV
        $('#downloadDetailedCsvBtn').click(function() {
            const csvContent = generateDetailedResultsCSV(results);
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `batch_detailed_results_${Date.now()}.csv`;
            document.body.appendChild(a);
            a.click();
            setTimeout(() => {
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }, 100);
        });
        
        // Download Results JSON
        $('#downloadJsonFilesBtn').click(async function() {
            try {
                $(this).prop('disabled', true).text('Creating ZIP...');
                const zipContent = await createJsonZipArchive(results);
                const url = URL.createObjectURL(zipContent);
                const a = document.createElement('a');
                a.href = url;
                a.download = `batch_json_results_${Date.now()}.zip`;
                document.body.appendChild(a);
                a.click();
                setTimeout(() => {
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                }, 100);
            } catch (error) {
                logDebug('Error creating ZIP archive', error);
                alert(`Error creating ZIP archive: ${error.message}`);
            } finally {
                $(this).prop('disabled', false).text('Download Results JSON');
            }
        });
        
        // Download Full JSON
        $('#downloadFullJsonFilesBtn').click(async function() {
            try {
                $(this).prop('disabled', true).text('Creating ZIP...');
                const zipContent = await createFullJsonZipArchive(results);
                const url = URL.createObjectURL(zipContent);
                const a = document.createElement('a');
                a.href = url;
                a.download = `batch_full_json_results_${Date.now()}.zip`;
                document.body.appendChild(a);
                a.click();
                setTimeout(() => {
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                }, 100);
            } catch (error) {
                logDebug('Error creating ZIP archive', error);
                alert(`Error creating ZIP archive: ${error.message}`);
            } finally {
                $(this).prop('disabled', false).text('Download Full JSON');
            }
        });
        
        return {
            results,
            errors,
            totalProcessed: completedCount
        };
    }
    
    return processInBatches();
}

// Add a URL preview thumbnail to the gallery
function addUrlPreview(url, result) {
    // Skip invalid URLs
    if (!url || !isValidUrl(url)) return;
    
    // Create preview element
    const previewElem = document.createElement('div');
    previewElem.className = 'url-preview-item';
    
    const img = document.createElement('img');
    img.alt = 'Preview';
    img.src = url;
    
    // Handle load errors
    img.onerror = function() {
        img.src = 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>';
        img.alt = 'Image load error';
    };
    
    const urlText = document.createElement('div');
    urlText.className = 'url-name';
    urlText.title = url;
    
    // Extract filename or short form of URL
    const urlObj = new URL(url);
    const filename = urlObj.pathname.split('/').pop() || url;
    urlText.textContent = filename;
    
    // Add success/error indicator
    previewElem.classList.add(result.success ? 'success' : 'error');
    
    previewElem.appendChild(img);
    previewElem.appendChild(urlText);
    
    // Add click event to show full result
    previewElem.addEventListener('click', function() {
        // Find the corresponding result item and highlight it
        const resultId = `result-${btoa(url).replace(/=/g, '')}`;
        const resultElem = document.getElementById(resultId);
        
        if (resultElem) {
            resultElem.scrollIntoView({ behavior: 'smooth', block: 'center' });
            resultElem.classList.add('highlight');
            setTimeout(() => {
                resultElem.classList.remove('highlight');
            }, 2000);
        }
    });
    
    $('.url-preview-gallery').append(previewElem);
}

// Render a single result item in the results container
function renderResultItem(result) {
    const resultId = `result-${btoa(result.url).replace(/=/g, '')}`;
    
    let resultHTML = `
        <div id="${resultId}" class="result-item ${result.success ? 'success' : 'error'}">
            <h4>${result.url}</h4>
    `;
    
    if (result.success) {
        // Format a condensed view of the API response
        let responsePreview = '';
        
        try {
            // Show filename and formatted JSON if available
            if (result.apiResponse.filename) {
                responsePreview += `<p>Filename: ${result.apiResponse.filename}</p>`;
            }
            
            // Show OCR text (truncated)
            if (result.apiResponse.formatted_md || result.apiResponse.ocr) {
                const md = (typeof result.apiResponse.formatted_md === 'string' && result.apiResponse.formatted_md.trim())
                    ? result.apiResponse.formatted_md
                    : (typeof result.apiResponse.ocr === 'string' ? result.apiResponse.ocr : '');
            
                if (md) {
                    const truncated = md.substring(0, 500) + (md.length > 500 ? '...' : '');
                    responsePreview += `<details>
                        <summary>Markdown (formatted)</summary>
                        <pre>${truncated}</pre>
                    </details>`;
                }
            }
            
            // Add full response details
            responsePreview += `<details>
                <summary>Full Response</summary>
                <pre>${JSON.stringify(result.apiResponse, null, 2)}</pre>
            </details>`;
            
        } catch (e) {
            responsePreview = `<p>Error formatting response: ${e.message}</p>`;
        }
        
        resultHTML += responsePreview;
    } else {
        resultHTML += `<p class="error">Error: ${result.error}</p>`;
    }
    
    resultHTML += '</div>';
    
    $('#batchUrlResults').append(resultHTML);
}

// Generate CSV from processing results
function generateResultsCSV(results, errors) {
    // Combine successful and failed results
    const allResults = [...results, ...errors];
    
    if (allResults.length === 0) {
        return 'No results to export';
    }
    
    // Start with headers
    const headers = [
        'URL',
        'Status',
        'Error',
        'OCR Engine',
        'Formatted JSON'
    ];
    
    // Add column headers
    let csv = headers.join(',') + '\n';
    
    // Add rows
    allResults.forEach(result => {
        const row = [
            // URL - escape quotes
            `"${result.url.replace(/"/g, '""')}"`,
            
            // Status
            result.success ? 'Success' : 'Failed',
            
            // Error message (if any)
            result.success ? '' : `"${result.error.replace(/"/g, '""')}"`,
            
            // OCR Engine
            result.success ? (result.apiResponse.ocr_info ? 
                Object.keys(result.apiResponse.ocr_info).join('+') : '') : '',
                
            // Formatted JSON (if available)
            result.success ? (result.apiResponse.formatted_json ? 
                `"${JSON.stringify(result.apiResponse.formatted_json).replace(/"/g, '""')}"` : '') : ''
        ];
        
        csv += row.join(',') + '\n';
    });
    
    return csv;
}

// Process a batch of local image files
async function processBatchImages(files, concurrency, options = {}) {
    const results = [];
    const errors = [];
    const totalCount = files.length;
    let completedCount = 0;
    
    // Update the progress bar
    function updateProgress() {
        const progressPercent = (completedCount / totalCount) * 100;
        $('#BatchFolder .batch-progress .progress-bar').css('width', `${progressPercent}%`);
        $('#BatchFolder .batch-progress .progress-count').text(`${completedCount}/${totalCount}`);
        
        if (completedCount === totalCount) {
            $('#BatchFolder .batch-progress .progress-text').text('Processing complete');
        }
    }
    
    // Process a single image file
    async function processImageFile(file) {
        try {
            logDebug(`Processing file: ${file.name} (${(file.size / 1024).toFixed(2)} KB)`);
            
            // Get authentication headers
            const headers = getAuthHeaders();
            // Remove Content-Type header as it will be set by the browser with form boundary
            delete headers['Content-Type'];
            
            // Create form data
            const formData = new FormData();
            formData.append('file', file);
            
            // Add each selected engine
            getSelectedEngines().forEach(engine => {
                formData.append('engines', engine);
            });
            
            // Add OCR only mode if selected
            if ($('#ocrOnly').is(':checked')) {
                formData.append('ocr_only', 'true');
            }

            // Add Notebook Mode if selected (bypass collage on server)
            if ($('#notebookMode').is(':checked')) {
                formData.append('notebook_mode', 'true');
            }

            // Add WFO validation if selected
            if ($('#includeWfo').is(':checked')) {
                formData.append('include_wfo', 'true');
            }
            
            // Add prompt template if specified
            const promptTemplate = $('#promptTemplate').val();
            if (promptTemplate) {
                formData.append('prompt', promptTemplate);
            }
            
            // Add selected model - make sure to include this!
            const llm_model = getSelectedModel();
            if (llm_model) {
                formData.append('llm_model', llm_model);
            }
            
            // Log what we're sending
            const formDataEntries = [];
            for (const pair of formData.entries()) {
                if (pair[0] !== 'file') {
                    formDataEntries.push({ key: pair[0], value: pair[1] });
                } else {
                    formDataEntries.push({ key: pair[0], value: pair[1].name });
                }
            }
            logDebug(`Request for file ${file.name}:`, formDataEntries);
            
            // Make the API request
            const response = await fetch('https://vouchervision-go-738307415303.us-central1.run.app/process', {
                method: 'POST',
                headers: headers,
                body: formData
            });
            
            if (!response.ok) {
                throw new Error(`API error: ${response.status} ${response.statusText}`);
            }
            
            const data = await response.json();
            
            // Process and store result
            const result = {
                filename: file.name,
                fileSize: file.size,
                fileType: file.type,
                apiResponse: data,
                success: true
            };
            
            results.push(result);
            return result;
        } catch (error) {
            logDebug(`Error processing file ${file.name}: ${error.message}`);
            
            const errorResult = {
                filename: file.name,
                fileSize: file.size,
                fileType: file.type,
                error: error.message,
                success: false
            };
            
            errors.push(errorResult);
            return errorResult;
        } finally {
            completedCount++;
            updateProgress();
        }
    }
    
    // Render a single image result item
    function renderImageResultItem(result) {
        const resultId = `image-result-${result.filename.replace(/[^a-z0-9]/gi, '')}`;
        
        let resultHTML = `
            <div id="${resultId}" class="result-item ${result.success ? 'success' : 'error'}">
                <h4>${result.filename}</h4>
                <p>Size: ${(result.fileSize / 1024).toFixed(2)} KB | Type: ${result.fileType}</p>
        `;
        
        if (result.success) {
            // Format a condensed view of the API response
            let responsePreview = '';
            
            try {
                // Show OCR text (truncated)
                const md = (result.apiResponse && typeof result.apiResponse.formatted_md === 'string' && result.apiResponse.formatted_md.trim())
                    ? result.apiResponse.formatted_md
                    : (result.apiResponse && typeof result.apiResponse.ocr === 'string' ? result.apiResponse.ocr : '');

                if (md) {
                    const truncated = md.substring(0, 500) + (md.length > 500 ? '...' : '');
                    responsePreview += `<details>
                        <summary>Markdown (formatted)</summary>
                        <pre>${truncated}</pre>
                    </details>`;
                }
                
                // Add formatted JSON preview
                if (result.apiResponse.formatted_json) {
                    responsePreview += `<details>
                        <summary>Formatted JSON</summary>
                        <pre>${JSON.stringify(result.apiResponse.formatted_json, null, 2)}</pre>
                    </details>`;
                }
                
                // Add full response details
                responsePreview += `<details>
                    <summary>Full Response</summary>
                    <pre>${JSON.stringify(result.apiResponse, null, 2)}</pre>
                </details>`;
                
            } catch (e) {
                responsePreview = `<p>Error formatting response: ${e.message}</p>`;
            }
            
            resultHTML += responsePreview;
        } else {
            resultHTML += `<p class="error">Error: ${result.error}</p>`;
        }
        
        resultHTML += '</div>';
        
        $('#batchImageResults').append(resultHTML);
    }
    
    // Process images with controlled concurrency
    async function processInBatches() {
        // Initialize progress tracking
        $('#BatchFolder .batch-progress').show();
        
        // Clear any previous download options
        $('#BatchFolder .batch-progress .progress-download-options').remove();
        
        // Add download buttons (disabled initially)
        $('#BatchFolder .batch-progress').append(`
            <div class="progress-download-options">
                <button id="downloadImageSummaryBtn" class="button" disabled>Download Summary CSV</button>
                <button id="downloadImageDetailedCsvBtn" class="button" disabled>Download Results CSV</button>
                <button id="downloadImageJsonFilesBtn" class="button" disabled>Download Results JSON</button>
                <button id="downloadImageFullJsonFilesBtn" class="button" disabled>Download Full JSON</button>
                <button id="downloadImageMdFilesBtn" class="button" disabled>Download Markdown</button>

            </div>
        `);
        
        updateProgress();
        
        // Clear previous results
        $('#batchImageResults').empty();
        
        // Process in batches with controlled concurrency
        const filesToProcess = [...files]; // Create a copy to avoid modifying the original
        const batchResults = [];
        
        while (filesToProcess.length > 0) {
            // Take up to 'concurrency' items
            const batch = filesToProcess.splice(0, concurrency);
            
            // Process the batch concurrently
            const batchPromises = batch.map(file => processImageFile(file));
            const batchResult = await Promise.all(batchPromises);
            
            batchResults.push(...batchResult);
            
            // Update UI with each batch result
            batchResult.forEach(result => {
                renderImageResultItem(result);
            });
        }
        
        // Show summary
        const successCount = results.length;
        const errorCount = errors.length;
        
        $('#BatchFolder .batch-progress .progress-text').html(`
            <strong>Processing Complete</strong><br>
            Successfully processed: ${successCount} images<br>
            Errors: ${errorCount} images
        `);
        
        // Enable download buttons if we have results
        $('#downloadImageSummaryBtn').prop('disabled', false);
        
        if (successCount > 0) {
            $('#downloadImageDetailedCsvBtn, #downloadImageJsonFilesBtn, #downloadImageFullJsonFilesBtn').prop('disabled', false);
        }

        const hasAnyImageMd = results.some(r =>
            r.success &&
            r.apiResponse &&
            (
                (typeof r.apiResponse.formatted_md === 'string' && r.apiResponse.formatted_md.trim()) ||
                (typeof r.apiResponse.ocr === 'string' && r.apiResponse.ocr.trim())
            )
        );

        if ($('#notebookMode').is(':checked') && hasAnyImageMd) {
            $('#downloadImageMdFilesBtn').prop('disabled', false).off('click').on('click', async function() {
                try {
                    $(this).prop('disabled', true).text('Creating ZIP...');
                    const zipContent = await createImageMdZipArchive(results);
                    const url = URL.createObjectURL(zipContent);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `image_batch_markdown_${Date.now()}.zip`;
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(() => {
                        document.body.removeChild(a);
                        URL.revokeObjectURL(url);
                    }, 100);
                } catch (error) {
                    logDebug('Error creating Markdown ZIP', error);
                    alert(`Error creating ZIP archive: ${error.message}`);
                } finally {
                    $(this).prop('disabled', false).text('Download Markdown');
                }
            });
        }
        
        // Download Summary CSV
        $('#downloadImageSummaryBtn').click(function() {
            const csvContent = generateImageSummaryCSV(results, errors);
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `image_batch_summary_${Date.now()}.csv`;
            document.body.appendChild(a);
            a.click();
            setTimeout(() => {
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }, 100);
        });

        // Download Detailed CSV
        $('#downloadImageDetailedCsvBtn').click(function() {
            const csvContent = generateImageDetailedCSV(results);
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `image_batch_detailed_results_${Date.now()}.csv`;
            document.body.appendChild(a);
            a.click();
            setTimeout(() => {
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            }, 100);
        });

        // Download Results JSON
        $('#downloadImageJsonFilesBtn').click(async function() {
            try {
                $(this).prop('disabled', true).text('Creating ZIP...');
                const zipContent = await createImageJsonZipArchive(results);
                const url = URL.createObjectURL(zipContent);
                const a = document.createElement('a');
                a.href = url;
                a.download = `image_batch_json_results_${Date.now()}.zip`;
                document.body.appendChild(a);
                a.click();
                setTimeout(() => {
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                }, 100);
            } catch (error) {
                logDebug('Error creating ZIP archive', error);
                alert(`Error creating ZIP archive: ${error.message}`);
            } finally {
                $(this).prop('disabled', false).text('Download Results JSON');
            }
        });

        // Download Full JSON
        $('#downloadImageFullJsonFilesBtn').click(async function() {
            try {
                $(this).prop('disabled', true).text('Creating ZIP...');
                const zipContent = await createFullImageJsonZipArchive(results);
                const url = URL.createObjectURL(zipContent);
                const a = document.createElement('a');
                a.href = url;
                a.download = `image_batch_full_json_results_${Date.now()}.zip`;
                document.body.appendChild(a);
                a.click();
                setTimeout(() => {
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                }, 100);
            } catch (error) {
                logDebug('Error creating ZIP archive', error);
                alert(`Error creating ZIP archive: ${error.message}`);
            } finally {
                $(this).prop('disabled', false).text('Download Full JSON');
            }
        });
        
        return {
            results,
            errors,
            totalProcessed: completedCount
        };
    }
    return processInBatches();
}

// Generate CSV from image processing results - summary only
function generateImageSummaryCSV(results, errors) {
    // Combine successful and failed results
    const allResults = [...results, ...errors];
    
    if (allResults.length === 0) {
        return 'No results to export';
    }
    
    // Start with headers
    const headers = [
        'Filename',
        'FileSize',
        'FileType',
        'Status',
        'Error',
        'OCR Engine'
    ];
    
    // Add column headers
    let csv = headers.join(',') + '\n';
    
    // Add rows
    allResults.forEach(result => {
        const row = [
            // Filename - escape quotes
            `"${result.filename.replace(/"/g, '""')}"`,
            
            // FileSize in KB
            (result.fileSize / 1024).toFixed(2),
            
            // FileType
            result.fileType,
            
            // Status
            result.success ? 'Success' : 'Failed',
            
            // Error message (if any)
            result.success ? '' : `"${result.error.replace(/"/g, '""')}"`,
            
            // OCR Engine
            result.success ? (result.apiResponse.ocr_info ? 
                Object.keys(result.apiResponse.ocr_info).join('+') : '') : ''
        ];
        
        csv += row.join(',') + '\n';
    });
    
    return csv;
}

// Generate detailed CSV for image results with JSON fields as columns
function generateImageDetailedCSV(results) {
    if (results.length === 0) {
        return 'No results to export';
    }
    
    // First pass: gather all possible fields from formatted_json across all results
    const allJsonFields = new Set();
    
    results.forEach(result => {
        if (result.success && result.apiResponse.formatted_json) {
            Object.keys(result.apiResponse.formatted_json).forEach(key => {
                allJsonFields.add(key);
            });
        }
    });
    
    // Convert to array and sort for consistent output
    const jsonFields = Array.from(allJsonFields).sort();
    
    // Start with headers (Filename + all JSON fields)
    const headers = ['Filename', ...jsonFields];
    
    // Add column headers
    let csv = headers.join(',') + '\n';
    
    // Add rows for successful results only
    results.forEach(result => {
        if (!result.success || !result.apiResponse.formatted_json) return;
        
        const row = [
            // Filename - escape quotes
            `"${result.filename.replace(/"/g, '""')}"`
        ];
        
        // Add data for each JSON field (or empty if not present)
        jsonFields.forEach(field => {
            const value = result.apiResponse.formatted_json[field];
            
            if (value === undefined || value === null) {
                row.push(''); // Empty for missing fields
            } else if (typeof value === 'object') {
                // For objects or arrays, convert to JSON string and escape quotes
                row.push(`"${JSON.stringify(value).replace(/"/g, '""')}"`);
            } else if (typeof value === 'string') {
                // For strings, escape quotes and wrap in quotes
                row.push(`"${value.replace(/"/g, '""')}"`);
            } else {
                // For numbers, booleans, etc.
                row.push(value);
            }
        });
        
        csv += row.join(',') + '\n';
    });
    
    return csv;
}

// Create zip archive with image JSON files
async function createImageJsonZipArchive(results) {
    // Dynamically load JSZip library
    if (typeof JSZip === 'undefined') {
        await new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }
    
    const zip = new JSZip();
    
    // Add each formatted_json as a separate file
    results.forEach(result => {
        if (result.success && result.apiResponse.formatted_json) {
            // Get filename without extension
            const filenameWithoutExt = result.filename.substring(0, result.filename.lastIndexOf('.'));
            const jsonFilename = `${filenameWithoutExt}.json`;
            
            zip.file(jsonFilename, JSON.stringify(result.apiResponse.formatted_json, null, 2));
        }
    });
    
    // Generate the zip file
    const content = await zip.generateAsync({type: 'blob'});
    return content;
}

function generateResultsSummaryCSV(results, errors) {
    // Combine successful and failed results
    const allResults = [...results, ...errors];
    
    if (allResults.length === 0) {
        return 'No results to export';
    }
    
    // Start with headers
    const headers = [
        'URL',
        'Status',
        'Error',
        'OCR Engine'
    ];
    
    // Add column headers
    let csv = headers.join(',') + '\n';
    
    // Add rows
    allResults.forEach(result => {
        const row = [
            // URL - escape quotes
            `"${result.url.replace(/"/g, '""')}"`,
            
            // Status
            result.success ? 'Success' : 'Failed',
            
            // Error message (if any)
            result.success ? '' : `"${result.error.replace(/"/g, '""')}"`,
            
            // OCR Engine
            result.success ? (result.apiResponse.ocr_info ? 
                Object.keys(result.apiResponse.ocr_info).join('+') : '') : ''
        ];
        
        csv += row.join(',') + '\n';
    });
    
    return csv;
}

// Generate detailed CSV with JSON fields as columns
function generateDetailedResultsCSV(results) {
    if (results.length === 0) {
        return 'No results to export';
    }
    
    // First pass: gather all possible fields from formatted_json across all results
    const allJsonFields = new Set();
    
    results.forEach(result => {
        if (result.success && result.apiResponse.formatted_json) {
            Object.keys(result.apiResponse.formatted_json).forEach(key => {
                allJsonFields.add(key);
            });
        }
    });
    
    // Convert to array and sort for consistent output
    const jsonFields = Array.from(allJsonFields).sort();
    
    // Start with headers (URL + all JSON fields)
    const headers = ['URL', ...jsonFields];
    
    // Add column headers
    let csv = headers.join(',') + '\n';
    
    // Add rows for successful results only
    results.forEach(result => {
        if (!result.success || !result.apiResponse.formatted_json) return;
        
        const row = [
            // URL - escape quotes
            `"${result.url.replace(/"/g, '""')}"`
        ];
        
        // Add data for each JSON field (or empty if not present)
        jsonFields.forEach(field => {
            const value = result.apiResponse.formatted_json[field];
            
            if (value === undefined || value === null) {
                row.push(''); // Empty for missing fields
            } else if (typeof value === 'object') {
                // For objects or arrays, convert to JSON string and escape quotes
                row.push(`"${JSON.stringify(value).replace(/"/g, '""')}"`);
            } else if (typeof value === 'string') {
                // For strings, escape quotes and wrap in quotes
                row.push(`"${value.replace(/"/g, '""')}"`);
            } else {
                // For numbers, booleans, etc.
                row.push(value);
            }
        });
        
        csv += row.join(',') + '\n';
    });
    
    return csv;
}

// Extract filename from URL
function getFilenameFromUrl(url) {
    try {
        // Parse the URL
        const urlObj = new URL(url);
        
        // Get the path part
        const path = urlObj.pathname;
        
        // Get the last segment (filename with extension)
        const filename = path.split('/').pop();
        
        // If no filename found or it's empty, use a hash of the URL
        if (!filename || filename === '') {
            return `file_${Math.abs(hashCode(url))}.json`;
        }
        
        // If filename has no extension, add .json
        if (!filename.includes('.')) {
            return `${filename}.json`;
        }
        
        // Replace extension with .json
        const filenameWithoutExt = filename.substring(0, filename.lastIndexOf('.'));
        return `${filenameWithoutExt}.json`;
    } catch (e) {
        // If URL parsing fails, use a hash of the URL
        return `file_${Math.abs(hashCode(url))}.json`;
    }
}

// Simple string hash function
function hashCode(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash; // Convert to 32bit integer
    }
    return hash;
}

// Create zip archive with JSON files
async function createJsonZipArchive(results) {
    // Dynamically load JSZip library if not already loaded
    if (typeof JSZip === 'undefined') {
        await new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }
    
    const zip = new JSZip();
    
    // Add each formatted_json as a separate file
    results.forEach(result => {
        if (result.success && result.apiResponse.formatted_json) {
            const filename = getFilenameFromUrl(result.url);
            zip.file(filename, JSON.stringify(result.apiResponse.formatted_json, null, 2));
        }
    });
    
    // Generate the zip file
    const content = await zip.generateAsync({type: 'blob'});
    return content;
}

// Function to create a ZIP archive with full API response JSON files for URLs
async function createFullJsonZipArchive(results) {
    // Dynamically load JSZip library if not already loaded
    if (typeof JSZip === 'undefined') {
        await new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }
    
    const zip = new JSZip();
    
    // Add each full API response as a separate file
    results.forEach(result => {
        if (result.success && result.apiResponse) {
            const filename = getFilenameFromUrl(result.url);
            zip.file(filename, JSON.stringify(result.apiResponse, null, 2));
        }
    });
    
    // Generate the zip file
    const content = await zip.generateAsync({type: 'blob'});
    return content;
}

// Function to create a ZIP archive with full API response JSON files for image files
async function createFullImageJsonZipArchive(results) {
    // Dynamically load JSZip library
    if (typeof JSZip === 'undefined') {
        await new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';
            script.onload = resolve;
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }
    
    const zip = new JSZip();
    
    // Add each full API response as a separate file
    results.forEach(result => {
        if (result.success && result.apiResponse) {
            // Get filename without extension
            const filenameWithoutExt = result.filename.substring(0, result.filename.lastIndexOf('.'));
            const jsonFilename = `${filenameWithoutExt}.json`;
            
            zip.file(jsonFilename, JSON.stringify(result.apiResponse, null, 2));
        }
    });
    
    // Generate the zip file
    const content = await zip.generateAsync({type: 'blob'});
    return content;
}

// Create zip archive with OCR Markdown files for URL batch
async function createMdZipArchive(results) {
    if (typeof JSZip === 'undefined') {
        await new Promise((resolve, reject) => {
            const s = document.createElement('script');
            s.src = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';
            s.onload = resolve; s.onerror = reject; document.head.appendChild(s);
        });
    }

    const zip = new JSZip();

    results.forEach(result => {
        if (!result.success || !result.apiResponse) return;

        const md = (typeof result.apiResponse.formatted_md === 'string' && result.apiResponse.formatted_md.trim())
            ? result.apiResponse.formatted_md.trim()
            : (typeof result.apiResponse.ocr === 'string' ? result.apiResponse.ocr.trim() : '');

        if (!md) return;

        const jsonName = getFilenameFromUrl(result.url);    // e.g., something.json
        const mdName   = jsonName.replace(/\.json$/i, '.md');
        zip.file(mdName, md);
    });

    return await zip.generateAsync({ type: 'blob' });
}

// Create zip archive with OCR Markdown files for Image batch
async function createImageMdZipArchive(results) {
    if (typeof JSZip === 'undefined') {
        await new Promise((resolve, reject) => {
            const s = document.createElement('script');
            s.src = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';
            s.onload = resolve; s.onerror = reject; document.head.appendChild(s);
        });
    }

    const zip = new JSZip();

    results.forEach(result => {
        if (!result.success || !result.apiResponse) return;

        const md = (typeof result.apiResponse.formatted_md === 'string' && result.apiResponse.formatted_md.trim())
            ? result.apiResponse.formatted_md.trim()
            : (typeof result.apiResponse.ocr === 'string' ? result.apiResponse.ocr.trim() : '');

        if (!md) return;

        const base = result.filename.includes('.')
            ? result.filename.slice(0, result.filename.lastIndexOf('.'))
            : result.filename || 'ocr_result';

        zip.file(`${base}.md`, md);
    });

    return await zip.generateAsync({ type: 'blob' });
}

// Initialize event handlers for batch processing
$(document).ready(function() {
    // Load Papa Parse for CSV processing
    const papaParse = document.createElement('script');
    papaParse.src = 'https://cdnjs.cloudflare.com/ajax/libs/PapaParse/5.3.0/papaparse.min.js';
    document.head.appendChild(papaParse);
    
    // Update concurrency slider values
    $('#concurrencySlider').on('input', function() {
        $('#concurrencyValue').text($(this).val());
    });
    
    $('#imageConcurrencySlider').on('input', function() {
        $('#imageConcurrencyValue').text($(this).val());
    });
    
    // Handle URL batch file selection
    $('#batchUrlFileInput').change(async function(event) {
        const file = event.target.files[0];
        if (!file) return;
        
        $('#urlFilePreview').empty();
        
        try {
            const reader = new FileReader();
            
            reader.onload = async function(e) {
                const fileContent = e.target.result;
                let parsedData;
                
                try {
                    if (file.name.endsWith('.csv')) {
                        // Parse CSV file
                        const urlColumnName = $('#csvUrlColumn').val() || 'url';
                        parsedData = await parseCSV(fileContent, urlColumnName);
                        
                        // Show CSV preview
                        $('#urlFilePreview').html(`
                            <p><strong>CSV file loaded:</strong> ${file.name}</p>
                            <p><strong>URL column:</strong> ${urlColumnName}</p>
                            <p><strong>URLs found:</strong> ${parsedData.urls.length}</p>
                            <p><strong>Sample URLs:</strong></p>
                            <ul>
                                ${parsedData.urls.slice(0, 5).map(item => 
                                    `<li>${item.url}</li>`).join('')}
                                ${parsedData.urls.length > 5 ? '<li>...</li>' : ''}
                            </ul>
                        `);
                    } else {
                        // Parse TXT file (one URL per line)
                        parsedData = parseTXT(fileContent);
                        
                        // Show TXT preview
                        $('#urlFilePreview').html(`
                            <p><strong>Text file loaded:</strong> ${file.name}</p>
                            <p><strong>URLs found:</strong> ${parsedData.urls.length}</p>
                            <p><strong>Sample URLs:</strong></p>
                            <ul>
                                ${parsedData.urls.slice(0, 5).map(item => 
                                    `<li>${item.url}</li>`).join('')}
                                ${parsedData.urls.length > 5 ? '<li>...</li>' : ''}
                            </ul>
                        `);
                    }
                    
                    // Store parsed data for later use
                    $('#batchUrlFileInput')[0].parsedData = parsedData;
                    
                    // Enable the process button
                    $('#processBatchUrlsButton').prop('disabled', false);
                    
                } catch (parseError) {
                    $('#urlFilePreview').html(`
                        <p class="error"><strong>Error parsing file:</strong> ${parseError}</p>
                    `);
                    $('#processBatchUrlsButton').prop('disabled', true);
                }
            };
            
            reader.onerror = function() {
                $('#urlFilePreview').html(`
                    <p class="error"><strong>Error reading file</strong></p>
                `);
                $('#processBatchUrlsButton').prop('disabled', true);
            };
            
            if (file.name.endsWith('.csv') || file.name.endsWith('.txt')) {
                reader.readAsText(file);
            } else {
                $('#urlFilePreview').html(`
                    <p class="error"><strong>Unsupported file type:</strong> Please select a .csv or .txt file</p>
                `);
                $('#processBatchUrlsButton').prop('disabled', true);
            }
        } catch (error) {
            $('#urlFilePreview').html(`
                <p class="error"><strong>Error:</strong> ${error.message}</p>
            `);
            $('#processBatchUrlsButton').prop('disabled', true);
        }
    });
    
    // Handle folder/files drag and drop
    const dropZone = document.getElementById('imageFolderDropZone');
    
    // Prevent default drag behaviors
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
    });
    
    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }
    
    // Highlight drop zone when dragging over it
    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, highlight, false);
    });
    
    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, unhighlight, false);
    });
    
    function highlight() {
        dropZone.classList.add('drag-over');
    }
    
    function unhighlight() {
        dropZone.classList.remove('drag-over');
    }
    
    // Handle dropped files
    dropZone.addEventListener('drop', handleDrop, false);
    
    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        handleImageFiles(files);
    }
    
    // Handle folder input change
    $('#imageFolderInput').change(function(event) {
        handleImageFiles(event.target.files);
    });
    
    // Process image files (from drop or input)
    function handleImageFiles(files) {
        const imageFiles = Array.from(files).filter(file => {
            const fileType = file.type.toLowerCase();
            return fileType.startsWith('image/');
        });
        
        if (imageFiles.length === 0) {
            $('#selectedFilesList').html(`
                <p class="error">No image files found. Please select image files.</p>
            `);
            $('#processBatchImagesButton').prop('disabled', true);
            return;
        }
        
        // Store files for later processing
        $('#imageFolderInput')[0].imageFiles = imageFiles;
        
        // Display file list
        $('#selectedFilesList').html(`
            <p><strong>Selected ${imageFiles.length} image files:</strong></p>
            <ul>
                ${imageFiles.slice(0, 10).map(file => 
                    `<li>${file.name} (${(file.size / 1024).toFixed(2)} KB)</li>`).join('')}
                ${imageFiles.length > 10 ? `<li>...and ${imageFiles.length - 10} more</li>` : ''}
            </ul>
        `);
        
        // Enable the process button
        $('#processBatchImagesButton').prop('disabled', false);
    }
    
    // Process batch URLs button click
    $('#processBatchUrlsButton').off('click').on('click', async function() {
        // Get the parsed data
        const parsedData = $('#batchUrlFileInput')[0].parsedData;
        
        if (!parsedData || !parsedData.urls || parsedData.urls.length === 0) {
            alert('Please select a valid file with URLs first');
            return;
        }
        
        // Check authentication
        const authMethod = $('input[name="authMethod"]:checked').val();
        
        if (authMethod === 'apiKey') {
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
        
        // Disable the process button
        $(this).prop('disabled', true).text('Processing...');
        
        // Get concurrency setting
        const concurrency = parseInt($('#concurrencySlider').val(), 10);
        
        // Check if save to CSV is requested
        const saveToCSV = $('#saveBatchToCsv').is(':checked');
        
        try {
            // Process the URLs
            await processBatchUrls(parsedData.urls, concurrency, { saveToCSV });
        } catch (error) {
            logDebug('Batch processing error', error);
            alert(`Processing error: ${error.message}`);
        } finally {
            // Re-enable the process button
            $(this).prop('disabled', false).text('Process URLs');
        }
    });
    
    // Process batch images button click
    $('#processBatchImagesButton').off('click').on('click', async function() {
        // Get the image files
        const imageFiles = $('#imageFolderInput')[0].imageFiles;
        
        if (!imageFiles || imageFiles.length === 0) {
            alert('Please select image files first');
            return;
        }
        
        // Check authentication
        const authMethod = $('input[name="authMethod"]:checked').val();
        
        if (authMethod === 'apiKey') {
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
        
        // Disable the process button
        $(this).prop('disabled', true).text('Processing...');
        
        // Get concurrency setting
        const concurrency = parseInt($('#imageConcurrencySlider').val(), 10);
        
        // Check if save to CSV is requested
        const saveToCSV = $('#saveImageBatchToCsv').is(':checked');
        
        try {
            // Process the images
            await processBatchImages(imageFiles, concurrency, { saveToCSV });
        } catch (error) {
            logDebug('Batch processing error', error);
            alert(`Processing error: ${error.message}`);
        } finally {
            // Re-enable the process button
            $(this).prop('disabled', false).text('Process Images');
        }
    });
});