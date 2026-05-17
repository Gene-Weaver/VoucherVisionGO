// Helper function to safely get nested properties
function getNestedValue(obj, path, defaultValue = "") {
    if (!obj) return defaultValue;
    
    const keys = path.split('.');
    let current = obj;
    
    for (const key of keys) {
        if (current && typeof current === 'object' && key in current) {
            current = current[key];
        } else {
            return defaultValue;
        }
    }
    
    return current ?? defaultValue;
}

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function safeDomId(prefix, value) {
    const cleaned = String(value ?? "")
        .replace(/[^a-z0-9_-]/gi, "-")
        .replace(/-+/g, "-")
        .replace(/^-|-$/g, "");
    return `${prefix}${cleaned || 'value'}`;
}

function buildPromptsRequestHeaders() {
    const headers = {};
    try {
        const apiKey = (localStorage.getItem('vouchervision_api_key') || '').trim();
        if (apiKey) {
            headers['X-API-Key'] = apiKey;
        } else {
            const authToken = (localStorage.getItem('vouchervision_auth_token') || '').trim();
            if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
        }
    } catch (e) {
        // localStorage may be unavailable in some embedded contexts
    }
    return headers;
}

// Function to render hierarchical data
function renderHierarchical(data, level = 0) {
    if (data === null) return '<span class="tree-value">null</span>';
    if (typeof data !== 'object') {
        if (typeof data === 'string') {
            return `<span class="tree-value">"${escapeHtml(data)}"</span>`;
        }
        return `<span class="tree-value">${escapeHtml(data)}</span>`;
    }
    
    let html = '';
    
    if (Array.isArray(data)) {
        html += '<div class="tree-array">';
        data.forEach((item, index) => {
            html += `<div>[${index}]: ${renderHierarchical(item, level + 1)}</div>`;
        });
        html += '</div>';
    } else {
        html += '<div class="tree-object">';
        Object.keys(data).forEach(key => {
            const value = data[key];
            const isComplex = value !== null && typeof value === 'object';
            const safeKey = escapeHtml(key);
            
            html += '<div>';
            if (isComplex) {
                const id = `tree-${level}-${key.replace(/[^a-z0-9]/gi, '')}`;
                html += `<span class="tree-toggle" data-target="${id}">+</span> `;
                html += `<span class="tree-key">${safeKey}:</span> `;
                html += `<div id="${id}" style="display: none;">`;
                html += renderHierarchical(value, level + 1);
                html += '</div>';
            } else {
                html += `<span class="tree-key">${safeKey}:</span> ${renderHierarchical(value, level + 1)}`;
            }
            html += '</div>';
        });
        html += '</div>';
    }
    
    return html;
}

// Function to remove highlight from all rows
function removeAllHighlights() {
    document.querySelectorAll('tr.highlight').forEach(row => {
        row.classList.remove('highlight');
    });
}

// Load prompt details
function loadPromptDetails(promptRef, rowId, promptLabel) {
    // Highlight the selected row
    removeAllHighlights();
    const selectedRow = document.getElementById(rowId);
    if (selectedRow) {
        selectedRow.classList.add('highlight');
    }
    
    // Show loading in the panel
    const detailsPanel = document.getElementById('detailsPanel');
    detailsPanel.style.display = 'block';
    document.getElementById('detailsTitle').textContent = `Prompt: ${promptLabel}`;
    document.getElementById('promptDetails').innerHTML = '<p>Loading prompt details...</p>';
    document.getElementById('sectionNav').innerHTML = '';
    
    // Scroll to top to show the panel
    window.scrollTo({top: 0, behavior: 'smooth'});
    
    fetch(`/prompts?prompt=${encodeURIComponent(promptRef)}`, {
        headers: buildPromptsRequestHeaders()
    })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                const prompt = data.prompt;
                document.getElementById('detailsTitle').textContent = `Prompt: ${promptLabel}`;
                
                // Get the parsed YAML data or raw content
                let parsedData = null;
                let rawContent = '';
                
                if (prompt.details && prompt.details.parsed_data) {
                    parsedData = prompt.details.parsed_data;
                    rawContent = prompt.details.raw_content || '';
                } else if (prompt.details) {
                    // Fallback if structure is different
                    parsedData = prompt.details;
                    rawContent = JSON.stringify(prompt.details, null, 2);
                } else {
                    // Last resort
                    parsedData = prompt;
                    rawContent = JSON.stringify(prompt, null, 2);
                }
                
                // Start building the details HTML
                let detailsHTML = '';
                let sectionLinks = [];
                
                // Build the metadata section
                const metaFields = [
                    {key: 'prompt_name', label: 'Name'},
                    {key: 'prompt_description', label: 'Description'},
                    {key: 'prompt_version', label: 'Version'},
                    {key: 'prompt_author', label: 'Author'},
                    {key: 'prompt_author_institution', label: 'Institution'},
                    {key: 'LLM', label: 'LLM Type'}
                ];
                
                detailsHTML += `<div id="section-metadata">`;
                detailsHTML += `<h3 class="section-heading">Metadata</h3>`;
                detailsHTML += `<table class="metadata-table">`;
                
                metaFields.forEach(field => {
                    const value = parsedData[field.key] || '';
                    if (value) {
                        detailsHTML += `<tr><td><strong>${escapeHtml(field.label)}:</strong></td><td>${escapeHtml(value)}</td></tr>`;
                    }
                });
                
                detailsHTML += `</table></div>`;
                sectionLinks.push({id: 'section-metadata', label: 'Metadata'});
                
                // Add common sections that most prompts would have
                const commonSections = [
                    {key: 'instructions', label: 'Instructions'},
                    {key: 'json_formatting_instructions', label: 'JSON Formatting'},
                    {key: 'rules', label: 'Rules'},
                    {key: 'mapping', label: 'Mapping'},
                    {key: 'examples', label: 'Examples'}
                ];
                
                commonSections.forEach(section => {
                    if (parsedData[section.key]) {
                        const sectionId = `section-${section.key}`;
                        detailsHTML += `<div id="${sectionId}">`;
                        detailsHTML += `<h3 class="section-heading">${section.label}</h3>`;
                        
                        if (typeof parsedData[section.key] === 'object') {
                            detailsHTML += `<div class="tree-view">`;
                            detailsHTML += renderHierarchical(parsedData[section.key]);
                            detailsHTML += `</div>`;
                        } else {
                            detailsHTML += `<pre>${escapeHtml(parsedData[section.key])}</pre>`;
                        }
                        
                        detailsHTML += `</div>`;
                        sectionLinks.push({id: sectionId, label: section.label});
                    }
                });
                
                // Add other sections not included in commonSections
                Object.keys(parsedData).forEach(key => {
                    // Skip metadata fields and already processed common sections
                    if (!metaFields.some(field => field.key === key) && 
                        !commonSections.some(section => section.key === key)) {
                        
                        const sectionId = safeDomId('section-', key);
                        const sectionLabel = key.replace(/_/g, ' ')
                            .replace(/\b\w/g, l => l.toUpperCase());
                        
                        detailsHTML += `<div id="${sectionId}">`;
                        detailsHTML += `<h3 class="section-heading">${escapeHtml(sectionLabel)}</h3>`;
                        
                        if (typeof parsedData[key] === 'object') {
                            detailsHTML += `<div class="tree-view">`;
                            detailsHTML += renderHierarchical(parsedData[key]);
                            detailsHTML += `</div>`;
                        } else {
                            detailsHTML += `<pre>${escapeHtml(parsedData[key])}</pre>`;
                        }
                        
                        detailsHTML += `</div>`;
                        sectionLinks.push({id: sectionId, label: sectionLabel});
                    }
                });
                
                // Add raw content section
                const rawSectionId = 'section-raw';
                detailsHTML += `<div id="${rawSectionId}">`;
                detailsHTML += `<h3 class="section-heading">Raw Content</h3>`;
                detailsHTML += `<pre>${escapeHtml(rawContent)}</pre>`;
                detailsHTML += `</div>`;
                sectionLinks.push({id: rawSectionId, label: 'Raw Content'});
                
                // Create section navigation
                let navHtml = '';
                sectionLinks.forEach((link, index) => {
                    navHtml += `<a href="#${escapeHtml(link.id)}">${escapeHtml(link.label)}</a>`;
                    if (index < sectionLinks.length - 1) {
                        navHtml += ' | ';
                    }
                });
                document.getElementById('sectionNav').innerHTML = navHtml;
                
                // Update the details content
                document.getElementById('promptDetails').innerHTML = detailsHTML;
                
                // Add event listeners for tree toggles
                document.querySelectorAll('.tree-toggle').forEach(toggle => {
                    toggle.addEventListener('click', function() {
                        const targetId = this.getAttribute('data-target');
                        const targetElement = document.getElementById(targetId);
                        
                        if (targetElement.style.display === 'none') {
                            targetElement.style.display = 'block';
                            this.textContent = '-';
                        } else {
                            targetElement.style.display = 'none';
                            this.textContent = '+';
                        }
                    });
                });
            } else {
                document.getElementById('promptDetails').innerHTML = `<div class="error">Error: ${escapeHtml(data.message || 'Unable to load prompt details.')}</div>`;
            }
        })
        .catch(error => {
            console.error('Error fetching prompt details:', error);
            document.getElementById('promptDetails').innerHTML = `<div class="error">Error loading details: ${escapeHtml(error.message || 'Unknown error')}</div>`;
        });
}

// Fetch and display the prompt list when the page loads
document.addEventListener('DOMContentLoaded', function() {
    fetch('/prompts', {
        headers: buildPromptsRequestHeaders()
    })
        .then(response => response.json())
        .then(data => {
            document.getElementById('loading').style.display = 'none';
            document.getElementById('promptTable').style.display = 'table';
            
            if (data.status === 'success') {
                const promptList = document.getElementById('promptList');
                
                data.prompts.forEach((prompt, index) => {
                    const row = document.createElement('tr');
                    row.id = `prompt-row-${index}`;
                    
                    // Extract prompt metadata
                    const name = getNestedValue(prompt, 'name');
                    const description = getNestedValue(prompt, 'description');
                    const version = getNestedValue(prompt, 'version');
                    const author = getNestedValue(prompt, 'author');

                    const values = [
                        index + 1,
                        prompt.filename || '',
                        name,
                        description,
                        version,
                        author,
                    ];
                    values.forEach((value, cellIndex) => {
                        const cell = document.createElement('td');
                        if (cellIndex === 3) cell.className = 'description';
                        cell.textContent = String(value ?? '');
                        row.appendChild(cell);
                    });

                    const actionsCell = document.createElement('td');
                    const detailsButton = document.createElement('button');
                    detailsButton.className = 'details-btn';
                    detailsButton.textContent = 'View Details';
                    detailsButton.dataset.promptRef = prompt.prompt_ref || prompt.filename || '';
                    detailsButton.dataset.promptLabel = prompt.filename || prompt.prompt_ref || '';
                    detailsButton.dataset.rowId = row.id;
                    actionsCell.appendChild(detailsButton);
                    row.appendChild(actionsCell);

                    promptList.appendChild(row);
                });
                
                // Add event listeners to the buttons
                document.querySelectorAll('.details-btn').forEach(button => {
                    button.addEventListener('click', () => {
                        const promptRef = button.getAttribute('data-prompt-ref');
                        const promptLabel = button.getAttribute('data-prompt-label');
                        const rowId = button.getAttribute('data-row-id');
                        loadPromptDetails(promptRef, rowId, promptLabel);
                    });
                });
            } else {
                alert('Error: ' + data.message);
            }
        })
        .catch(error => {
            console.error('Error fetching prompts:', error);
            document.getElementById('loading').textContent = 'Error loading prompts: ' + error.message;
        });
    
    // Close the details panel
    document.getElementById('closePanel').addEventListener('click', () => {
        document.getElementById('detailsPanel').style.display = 'none';
        removeAllHighlights();
    });
});
