function setupPromptTemplates() {
    console.log('Prompt templates script loaded');

    const promptTemplateGroup = document.querySelector('.form-group h3[for="promptTemplate"]')?.parentElement;
    if (!promptTemplateGroup) {
        console.error('Could not find prompt template group on first try. Retrying...');
        setTimeout(setupPromptTemplates, 200);  // retry slightly slower
        return;
    }

    console.log('Found prompt template group, injecting buttons');

    // 🛠️ Instead of overwriting the whole promptTemplateGroup, we now find the new #promptButtonsArea inside it
    const promptArea = document.getElementById('promptButtonsArea');
    if (!promptArea) {
        console.error('Prompt Buttons Area not found!');
        return;
    }

    promptArea.innerHTML = `
        <button id="refreshPromptsBtn" class="button" style="margin-bottom: 10px;">Refresh Prompts</button>
        <div id="promptCount" style="font-size: 14px; margin-bottom: 5px;"></div>
        <div id="templateButtonsContainer" style="display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 15px;
             max-height: 150px; overflow-y: auto; padding: 5px; border: 1px solid #eee; border-radius: 4px;"></div>
    `;

    const refreshButton = document.getElementById('refreshPromptsBtn');
    const countDisplay = document.getElementById('promptCount');
    const buttonsContainer = document.getElementById('templateButtonsContainer');

    function showStatus(message, isError = false) {
        const statusElem = document.createElement('p');
        statusElem.textContent = message;
        statusElem.style.margin = '5px 0';
        statusElem.style.fontSize = '12px';
        statusElem.style.color = isError ? '#f44336' : '#666';
        statusElem.style.fontStyle = 'italic';

        buttonsContainer.innerHTML = '';
        buttonsContainer.appendChild(statusElem);
        countDisplay.textContent = '';
    }

    function createButtons(templates) {
        buttonsContainer.innerHTML = '';
        countDisplay.textContent = `Available Prompts: ${templates.length}`;

        templates.sort((a, b) => a.localeCompare(b));

        templates.forEach(template => {
            const button = document.createElement('button');
            button.textContent = template;
            button.title = template;
            button.style.padding = '6px 12px';
            button.style.borderRadius = '4px';
            button.style.border = '1px solid #ddd';
            button.style.backgroundColor = '#f8f8f8';
            button.style.cursor = 'pointer';
            button.style.transition = 'all 0.2s ease';

            button.addEventListener('click', function() {
                document.getElementById('promptTemplate').value = template;

                const originalBg = button.style.backgroundColor;
                const originalText = button.textContent;

                button.style.backgroundColor = '#4CAF50';
                button.style.color = 'white';
                button.textContent = 'Selected!';

                setTimeout(() => {
                    button.style.backgroundColor = originalBg;
                    button.style.color = '';
                    button.textContent = originalText;
                }, 1000);
            });

            buttonsContainer.appendChild(button);
        });
    }

    function fetchTemplates(showStatusOnError = false, retries = 5) {
        if (showStatusOnError) {
            showStatus('Loading prompts...');
        }

        console.log('Fetching prompts from API...');

        fetch('https://vouchervision-go-738307415303.us-central1.run.app/prompts')
            .then(response => {
                console.log('Fetch response:', response);
                if (!response.ok) {
                    throw new Error(`Error: ${response.status} ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                console.log('Received data from server:', data);

                if (data && data.prompts && Array.isArray(data.prompts)) {
                    const templates = data.prompts
                        .map(p => p.filename || '')
                        .filter(name => name.trim() !== '');

                    console.log(`Parsed ${templates.length} prompt templates`);
                    localStorage.setItem('vouchervision_templates', JSON.stringify(templates));

                    createButtons(templates);
                } else {
                    console.error('Invalid data structure:', data);
                    throw new Error('Invalid response format from API');
                }
            })
            .catch(error => {
                console.error('Error fetching prompts:', error);

                if (retries > 0) {
                    console.warn(`Retrying fetchTemplates... (${retries} retries left)`);
                    setTimeout(() => fetchTemplates(showStatusOnError, retries - 1), 1000);
                } else if (showStatusOnError) {
                    console.error('Out of retries fetching prompts.');
                    showStatus('Error loading prompts. Please click Refresh.', true);
                }
            });
    }

    const cached = localStorage.getItem('vouchervision_templates');

    if (cached) {
        try {
            const templates = JSON.parse(cached);
            createButtons(templates);

            fetchTemplates(false);
        } catch (e) {
            console.error('Failed to parse cache, fetching from server');
            fetchTemplates(true);
        }
    } else {
        fetchTemplates(true);
    }

    refreshButton.addEventListener('click', function() {
        console.log('Manual refresh clicked');
        fetchTemplates(true);
    });

    console.log('Prompt templates setup complete');
}

// === Still important: DOMContentLoaded, not window.load
document.addEventListener('DOMContentLoaded', setupPromptTemplates);
