// Define the list of prompt templates optimized for Gemini-3
const optimized_for_gemini_3 = [
    "SLTPvM_full.yaml",
    "SLTPvM_geolocate.yaml",
    "SLTPvM_geolocate_flag_multispecimen.yaml"
    // Add more files here as needed
];

function setupPromptTemplates() {
    console.log('Prompt templates script loaded');

    const promptArea = document.getElementById('promptButtonsArea');
    if (!promptArea) {
        console.error('Could not find promptButtonsArea. Retrying...');
        setTimeout(setupPromptTemplates, 200);
        return;
    }

    console.log('Found prompt buttons area, injecting buttons');

    promptArea.innerHTML = `
        <div id="promptCount" style="font-size: 14px; margin-bottom: 5px; display:flex; justify-content:space-between; align-items:center;"></div>
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

    function createButtons(prompts) {
        buttonsContainer.innerHTML = '';
        countDisplay.innerHTML = `<span>Available Prompts: ${prompts.length}</span><span style="font-size:0.85em;"><span style="color:#6a0dad; font-weight:bold;">Gemini-3 optimized</span> &middot; <span style="color:#000; background-color:#DAA520; font-weight:bold; padding: 1px 4px; border-radius: 3px;">User-generated</span></span>`;

        // Sort: built-ins first (alpha), then user-generated (alpha)
        prompts.sort((a, b) => {
            const aUser = a && a.is_user_generated ? 1 : 0;
            const bUser = b && b.is_user_generated ? 1 : 0;
            if (aUser !== bUser) return aUser - bUser;
            return (a.filename || '').localeCompare(b.filename || '');
        });

        prompts.forEach(prompt => {
            const filename = prompt.filename || '';
            const promptRef = prompt.prompt_ref || filename;
            const isUserGenerated = !!prompt.is_user_generated;
            const environment = prompt.environment;

            const button = document.createElement('button');
            button.textContent = filename;
            // Tooltip shows the underlying ref + environment for user-generated prompts
            button.title = isUserGenerated
                ? `${filename}\n[user-generated, ${environment}]\n${promptRef}`
                : filename;

            button.classList.add('prompt-template-btn');
            button.style.cursor = 'pointer';
            button.dataset.promptRef = promptRef;

            if (isUserGenerated) {
                button.classList.add('user-generated-btn');
            } else if (optimized_for_gemini_3.some(opt =>
                filename.trim().toLowerCase().endsWith(opt.toLowerCase())
            )) {
                button.classList.add('gemini-optimized-btn');
            }

            button.addEventListener('click', function () {
                // Send the prompt_ref (which is the filename for builtins, UGP__... for user prompts)
                document.getElementById('promptTemplate').value = promptRef;

                const originalText = button.textContent;

                // Temporary green flash
                button.classList.add('selected-flash');
                button.textContent = 'Selected!';

                setTimeout(() => {
                    button.classList.remove('selected-flash');
                    button.textContent = originalText;
                }, 1000);
            });

            buttonsContainer.appendChild(button);
        });
    }

    function buildPromptsRequestHeaders() {
        const headers = {};
        try {
            const apiKey = (localStorage.getItem('vouchervision_api_key') || '').trim();
            if (apiKey) headers['X-API-Key'] = apiKey;
            else {
                const authToken = (localStorage.getItem('vouchervision_auth_token') || '').trim();
                if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
            }
        } catch (e) { /* localStorage unavailable */ }
        return headers;
    }

    function fetchTemplates(showStatusOnError = false, retries = 5) {
        if (showStatusOnError) {
            showStatus('Loading prompts...');
        }

        console.log('Fetching prompts from API...');

        fetch('https://vouchervision-go-738307415303.us-central1.run.app/prompts', {
            headers: buildPromptsRequestHeaders()
        })
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
                    const prompts = data.prompts
                        .filter(p => p && (p.filename || p.prompt_ref));

                    console.log(`Parsed ${prompts.length} prompts`);
                    try {
                        localStorage.setItem('vouchervision_templates_v2', JSON.stringify(prompts));
                    } catch (e) { /* quota / private mode */ }

                    createButtons(prompts);
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

    const cached = localStorage.getItem('vouchervision_templates_v2');

    if (cached) {
        try {
            const prompts = JSON.parse(cached);
            if (Array.isArray(prompts)) {
                createButtons(prompts);
            }

            fetchTemplates(false);
        } catch (e) {
            console.error('Failed to parse cache, fetching from server');
            fetchTemplates(true);
        }
    } else {
        fetchTemplates(true);
    }

    refreshButton.addEventListener('click', function () {
        console.log('Manual refresh clicked');
        fetchTemplates(true);
    });

    console.log('Prompt templates setup complete');
}

// === Still important: DOMContentLoaded, not window.load
document.addEventListener('DOMContentLoaded', setupPromptTemplates);
