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

// Function to render hierarchical data
function renderHierarchical(data, level = 0) {
    if (data === null) return '<span class="tree-value">null</span>';
    if (typeof data !== 'object') {
        if (typeof data === 'string') {
            return `<span class="tree-value">"${data}"</span>`;
        }
        return `<span class="tree-value">${data}</span>`;
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
            
            html += '<div>';
            if (isComplex) {
                const id = `tree-${level}-${key.replace(/[^a-z0-9]/gi, '')}`;
                html += `<span class="tree-toggle" data-target="${id}">+</span> `;
                html += `<span class="tree-key">${key}:</span> `;
                html += `<div id="${id}" style="display: none;">`;
                html += renderHierarchical(value, level + 1);
                html += '</div>';
            } else {
                html += `<span class="tree-key">${key}:</span> ${renderHierarchical(value, level + 1)}`;
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
function loadPromptDetails(filename, rowId) {
    // Highlight the selected row
    removeAllHighlights();
    const selectedRow = document.getElementById(rowId);
    if (selectedRow) {
        selectedRow.classList.add('highlight');
    }
    
    // Show loading in the panel
    const detailsPanel = document.getElementById('detailsPanel');
    detailsPanel.style.display = 'block';
    document.getElementById('detailsTitle').textContent = `Prompt: ${filename}`;
    document.getElementById('promptDetails').innerHTML = '<p>Loading prompt details...</p>';
    document.getElementById('sectionNav').innerHTML = '';
    
    // Scroll to top to show the panel
    window.scrollTo({top: 0, behavior: 'smooth'});
    
    fetch(`/prompts?prompt=${filename}`)
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                const prompt = data.prompt;
                document.getElementById('detailsTitle').textContent = `Prompt: ${filename}`;
                
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
                        detailsHTML += `<tr><td><strong>${field.label}:</strong></td><td>${value}</td></tr>`;
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
                            detailsHTML += `<pre>${parsedData[section.key]}</pre>`;
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
                        
                        const sectionId = `section-${key}`;
                        const sectionLabel = key.replace(/_/g, ' ')
                            .replace(/\b\w/g, l => l.toUpperCase());
                        
                        detailsHTML += `<div id="${sectionId}">`;
                        detailsHTML += `<h3 class="section-heading">${sectionLabel}</h3>`;
                        
                        if (typeof parsedData[key] === 'object') {
                            detailsHTML += `<div class="tree-view">`;
                            detailsHTML += renderHierarchical(parsedData[key]);
                            detailsHTML += `</div>`;
                        } else {
                            detailsHTML += `<pre>${parsedData[key]}</pre>`;
                        }
                        
                        detailsHTML += `</div>`;
                        sectionLinks.push({id: sectionId, label: sectionLabel});
                    }
                });
                
                // Add raw content section
                const rawSectionId = 'section-raw';
                detailsHTML += `<div id="${rawSectionId}">`;
                detailsHTML += `<h3 class="section-heading">Raw Content</h3>`;
                detailsHTML += `<pre>${rawContent}</pre>`;
                detailsHTML += `</div>`;
                sectionLinks.push({id: rawSectionId, label: 'Raw Content'});
                
                // Create section navigation
                let navHtml = '';
                sectionLinks.forEach((link, index) => {
                    navHtml += `<a href="#${link.id}">${link.label}</a>`;
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
                document.getElementById('promptDetails').innerHTML = `<div class="error">Error: ${data.message}</div>`;
            }
        })
        .catch(error => {
            console.error('Error fetching prompt details:', error);
            document.getElementById('promptDetails').innerHTML = `<div class="error">Error loading details: ${error.message}</div>`;
        });
}

// Fetch and display the prompt list when the page loads
document.addEventListener('DOMContentLoaded', function() {
    fetch('/prompts')
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
                    
                    row.innerHTML = `
                        <td>${index + 1}</td>
                        <td>${prompt.filename}</td>
                        <td>${name}</td>
                        <td class="description">${description}</td>
                        <td>${version}</td>
                        <td>${author}</td>
                        <td><button class="details-btn" data-filename="${prompt.filename}" data-row-id="${row.id}">View Details</button></td>
                    `;
                    
                    promptList.appendChild(row);
                });
                
                // Add event listeners to the buttons
                document.querySelectorAll('.details-btn').forEach(button => {
                    button.addEventListener('click', () => {
                        const filename = button.getAttribute('data-filename');
                        const rowId = button.getAttribute('data-row-id');
                        loadPromptDetails(filename, rowId);
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