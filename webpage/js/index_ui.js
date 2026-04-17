// ===================================================================
// index_ui.js — UI logic extracted from index.html inline scripts
// ===================================================================

// ---------- LLM Cost Calculator ----------
(function () {
    function getProvider(key) {
        if (key.startsWith('GPT_')) return 'OpenAI';
        if (key.startsWith('GEMINI_') || key.startsWith('PALM2_')) return 'Google';
        if (key.startsWith('Hyperbolic_')) return 'Hyperbolic';
        return 'Other';
    }
    function prettyNameFromKey(key) {
        let name = key.replace(/_/g, ' ');
        name = name.replace(/(\d{4}) (\d{2}) (\d{2})/, '$1-$2-$3');
        return name;
    }
    function formatPrice(v) {
        if (typeof v !== 'number' || isNaN(v)) return '';
        const s = v.toFixed(4).replace(/0+$/,'').replace(/\.$/,'');
        return '$' + s;
    }
    function initLlmCostUI(costData) {
        const ocrSelectEl = document.getElementById('ocrModelSelect');
        const ocrInEl = document.getElementById('ocrTokensIn');
        const ocrOutEl = document.getElementById('ocrTokensOut');
        const parseSelectEl = document.getElementById('parseModelSelect');
        const parseInEl = document.getElementById('parseTokensIn');
        const parseOutEl = document.getElementById('parseTokensOut');
        const imgEl = document.getElementById('llmNumImages');
        const totalEl = document.getElementById('llmTotalCost');
        const tablesEl = document.getElementById('llmCostTables');
        if (!ocrSelectEl || !parseSelectEl || !ocrInEl || !ocrOutEl || !parseInEl || !parseOutEl || !imgEl || !totalEl || !tablesEl) return;

        const models = [];
        for (const key in costData) {
            if (!Object.prototype.hasOwnProperty.call(costData, key)) continue;
            const entry = costData[key] || {};
            const priceIn = Number(entry.in);
            const priceOut = Number(entry.out);
            if (isNaN(priceIn) || isNaN(priceOut)) continue;
            models.push({ key, provider: getProvider(key), name: prettyNameFromKey(key), in: priceIn, out: priceOut });
        }
        if (!models.length) {
            ocrSelectEl.innerHTML = '<option value="">No models found</option>';
            parseSelectEl.innerHTML = '<option value="">No models found</option>';
            tablesEl.innerHTML = '<div class="vv-card llm-cost-card">No cost data loaded.</div>';
            return;
        }
        models.sort((a, b) => a.provider === b.provider ? a.name.localeCompare(b.name) : a.provider.localeCompare(b.provider));
        const modelMap = {};
        models.forEach(m => { modelMap[m.key] = m; });

        // Populate both dropdowns
        [ocrSelectEl, parseSelectEl].forEach(sel => {
            sel.innerHTML = '';
            models.forEach(m => {
                const opt = document.createElement('option');
                opt.value = m.key;
                opt.textContent = `${m.provider}: ${m.name}`;
                sel.appendChild(opt);
            });
        });

        // Default OCR model: heavier vision model
        const ocrDefault = models.find(m => m.key === 'GEMINI_3_1_PRO')?.key
            || models.find(m => m.key.includes('PRO'))?.key
            || models[0].key;
        ocrSelectEl.value = ocrDefault;

        // Default Parsing model: fast/cheap model
        const parseDefault = models.find(m => m.key === 'GEMINI_3_1_FLASH_LITE')?.key
            || models.find(m => m.key.includes('FLASH_LITE'))?.key
            || models[0].key;
        parseSelectEl.value = parseDefault;

        // Cost matrix table
        const byProvider = {};
        models.forEach(m => { if (!byProvider[m.provider]) byProvider[m.provider] = []; byProvider[m.provider].push(m); });
        const providerOrder = ['OpenAI','Azure OpenAI','Google','Mistral','Hyperbolic','Local','Other'];
        const htmlChunks = [];
        providerOrder.forEach(provider => {
            const list = byProvider[provider];
            if (!list || !list.length) return;
            list.sort((a, b) => a.name.localeCompare(b.name));
            htmlChunks.push(`<div class="vv-card llm-cost-card"><h4>${provider}</h4><table class="llm-cost-table"><thead><tr><th>Model</th><th>Input ($/1M)</th><th>Output ($/1M)</th></tr></thead><tbody>${list.map(m => `<tr><td>${m.name}</td><td>${formatPrice(m.in)}</td><td>${formatPrice(m.out)}</td></tr>`).join('')}</tbody></table></div>`);
        });
        tablesEl.innerHTML = htmlChunks.join('');

        // Check if a token field is at its default (high) value
        function isDefault(el) {
            return el.dataset.defaultHigh && Number(el.value) === Number(el.dataset.defaultHigh);
        }

        // Are ALL four token fields at their defaults?
        function allDefaults() {
            return isDefault(ocrInEl) && isDefault(ocrOutEl) && isDefault(parseInEl) && isDefault(parseOutEl);
        }

        function calcCostForStage(model, tokIn, tokOut) {
            if (!model) return 0;
            return (tokIn / 1_000_000 * model.in) + (tokOut / 1_000_000 * model.out);
        }

        function recomputeCost() {
            const ocrModel = modelMap[ocrSelectEl.value];
            const parseModel = modelMap[parseSelectEl.value];
            const nImg = Number(imgEl.value) || 0;

            if (allDefaults()) {
                // Range mode: low (typical) to high (worst-case)
                const lowOcrIn = Number(ocrInEl.dataset.defaultLow);
                const lowOcrOut = Number(ocrOutEl.dataset.defaultLow);
                const lowParseIn = Number(parseInEl.dataset.defaultLow);
                const lowParseOut = Number(parseOutEl.dataset.defaultLow);

                const highOcrIn = Number(ocrInEl.value);
                const highOcrOut = Number(ocrOutEl.value);
                const highParseIn = Number(parseInEl.value);
                const highParseOut = Number(parseOutEl.value);

                const costLow = (calcCostForStage(ocrModel, lowOcrIn, lowOcrOut) + calcCostForStage(parseModel, lowParseIn, lowParseOut)) * nImg;
                const costHigh = (calcCostForStage(ocrModel, highOcrIn, highOcrOut) + calcCostForStage(parseModel, highParseIn, highParseOut)) * nImg;

                totalEl.textContent = '$' + costLow.toFixed(2) + ' – $' + costHigh.toFixed(2);
            } else {
                // Exact mode: user changed at least one token field
                const cost = (calcCostForStage(ocrModel, Number(ocrInEl.value), Number(ocrOutEl.value))
                    + calcCostForStage(parseModel, Number(parseInEl.value), Number(parseOutEl.value))) * nImg;
                totalEl.textContent = '$' + cost.toFixed(2);
            }
        }

        const allInputs = [ocrSelectEl, ocrInEl, ocrOutEl, parseSelectEl, parseInEl, parseOutEl, imgEl];
        ['change','input'].forEach(evt => {
            allInputs.forEach(el => el.addEventListener(evt, recomputeCost));
        });
        recomputeCost();
    }

    document.addEventListener('DOMContentLoaded', function () {
        const section = document.getElementById('llmCostSection');
        if (!section) return;
        const apiBase = window.VVGO_API_BASE || location.origin;
        fetch(apiBase + '/api-costs', { method: 'GET', mode: 'cors', cache: 'no-cache' })
            .then(resp => { if (!resp.ok) throw new Error('Failed to load cost data: ' + resp.status); return resp.json(); })
            .then(data => { initLlmCostUI(data || {}); })
            .catch(err => {
                console.error('[LLM Cost] Error loading cost data:', err);
                const tablesEl = document.getElementById('llmCostTables');
                const ocrSel = document.getElementById('ocrModelSelect');
                const parseSel = document.getElementById('parseModelSelect');
                if (tablesEl) tablesEl.innerHTML = '<div class="vv-card llm-cost-card">Error loading cost data.</div>';
                if (ocrSel) ocrSel.innerHTML = '<option value="">Error loading cost data</option>';
                if (parseSel) parseSel.innerHTML = '<option value="">Error loading cost data</option>';
            });
    });
})();

// ---------- Main Tabs, Navigation, Impact, Image Preview ----------
document.addEventListener('DOMContentLoaded', function() {
    // Main settings tabs
    document.querySelectorAll('.main-tab').forEach(tab => {
        tab.addEventListener('click', function() {
            document.querySelectorAll('.main-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.main-tab-content').forEach(c => c.classList.remove('active'));
            this.classList.add('active');
            document.getElementById(this.dataset.mainTab).classList.add('active');
        });
    });

    // Helper: show an image in the Step 4 preview panel
    function showStep4Preview(src) {
        const previewArea = document.getElementById('step4ImagePreview');
        if (previewArea) {
            previewArea.innerHTML = '<img src="' + src + '" alt="Preview" onclick="openImageModal(this)" style="cursor:pointer;" title="Click to enlarge">';
        }
        // Show download button
        let actionsEl = document.getElementById('step4PreviewActions');
        if (!actionsEl) {
            actionsEl = document.createElement('div');
            actionsEl.id = 'step4PreviewActions';
            actionsEl.className = 'image-actions';
            const rightPanel = document.querySelector('.step4-right');
            if (rightPanel) rightPanel.appendChild(actionsEl);
        }
        actionsEl.innerHTML = '<button class="button" onclick="downloadPreviewImage()">Download Image</button>';
        actionsEl.style.display = 'flex';
        // Store src for download
        window._step4PreviewSrc = src;
    }
    // Make it globally accessible
    window.showStep4Preview = showStep4Preview;

    function clearStep4Preview() {
        const previewArea = document.getElementById('step4ImagePreview');
        if (previewArea) previewArea.innerHTML = '<p class="no-image-msg">No image selected</p>';
        const actionsEl = document.getElementById('step4PreviewActions');
        if (actionsEl) actionsEl.style.display = 'none';
        window._step4PreviewSrc = null;
    }

    function showStep4Unavailable() {
        const previewArea = document.getElementById('step4ImagePreview');
        if (previewArea) previewArea.innerHTML = '<p class="no-image-msg">Image not available</p>';
        const actionsEl = document.getElementById('step4PreviewActions');
        if (actionsEl) actionsEl.style.display = 'none';
        window._step4PreviewSrc = null;
    }

    // File upload preview in Step 4
    const fileInput = document.getElementById('fileInput');
    if (fileInput) {
        fileInput.addEventListener('change', function () {
            if (this.files && this.files[0]) {
                const reader = new FileReader();
                reader.onload = function (e) {
                    showStep4Preview(e.target.result);
                };
                reader.readAsDataURL(this.files[0]);
            } else {
                clearStep4Preview();
            }
        });
    }

    // URL input preview in Step 4
    const imageUrlInput = document.getElementById('imageUrl');
    if (imageUrlInput) {
        // Helper to preview a URL image
        function previewUrlImage() {
            const url = imageUrlInput.value.trim();
            if (!url) { clearStep4Preview(); return; }
            const img = new Image();
            img.onload = function () { showStep4Preview(url); };
            img.onerror = function () { showStep4Unavailable(); };
            img.src = url;
        }

        // Listen for typed/pasted input
        imageUrlInput.addEventListener('input', previewUrlImage);

        // Also watch for programmatic value changes (example links use .value = ...)
        // by observing clicks on the example link buttons
        document.querySelectorAll('[data-url]').forEach(function (el) {
            el.addEventListener('click', function () {
                setTimeout(previewUrlImage, 0);
            });
        });
        // Buttons that copy URL to the input (clipboard icons)
        document.querySelectorAll('button[onclick*="imageUrl"]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                setTimeout(previewUrlImage, 0);
            });
        });

        // Show preview for the default URL on page load
        previewUrlImage();
    }

    // Navigation functionality
    const homeLink = document.getElementById('homeLink');
    const readmeLink = document.getElementById('readmeLink');
    const promptsLink = document.getElementById('promptsLink');
    const impactLink = document.getElementById('impactLink');
    const changelogLink = document.getElementById('changelogLink');
    const signupLink = document.getElementById('signupLink');
    const mainContent = document.getElementById('mainContent');
    const readmeContent = document.getElementById('readmeContent');
    const promptsContent = document.getElementById('promptsContent');
    const changelogContent = document.getElementById('changelogContent');
    const signupContent = document.getElementById('signupContent');
    const promptsFrame = document.getElementById('promptsFrame');
    const signupFrame = document.getElementById('signupFrame');

    // Load README content
    fetch('./README.md')
        .then(response => { if (!response.ok) throw new Error('Network response was not ok'); return response.text(); })
        .then(data => {
            const converter = new showdown.Converter({ tables: true, tasklists: true, strikethrough: true, ghCodeBlocks: true });
            readmeContent.innerHTML = converter.makeHtml(data);
        })
        .catch(error => {
            console.error('Error fetching README:', error);
            readmeContent.innerHTML = '<div class="error">Error loading README file.</div>';
        });

    function loadImpact() {
        const impactContent = document.getElementById('impactContent');
        impactContent.classList.add('loading');
        fetch('./IMPACT.md')
            .then(response => { if (!response.ok) throw new Error('Network response was not ok'); return response.text(); })
            .then(data => {
                const converter = new showdown.Converter({ tables: true, tasklists: true, strikethrough: true, ghCodeBlocks: true });
                impactContent.innerHTML = converter.makeHtml(data);
            })
            .catch(error => {
                console.error('Error fetching IMPACT.md:', error);
                impactContent.innerHTML = '<div class="error">Error loading IMPACT.md.</div>';
            })
            .finally(() => { impactContent.classList.remove('loading'); });
    }

    function resetNavigation() {
        mainContent.style.display = 'none';
        readmeContent.style.display = 'none';
        promptsContent.style.display = 'none';
        document.getElementById('impactContent').style.display = 'none';
        changelogContent.style.display = 'none';
        signupContent.style.display = 'none';
        homeLink.classList.remove('active');
        readmeLink.classList.remove('active');
        promptsLink.classList.remove('active');
        if (impactLink) impactLink.classList.remove('active');
        changelogLink.classList.remove('active');
        signupLink.classList.remove('active');
        promptsFrame.src = 'about:blank';
        signupFrame.src = 'about:blank';
    }

    homeLink.addEventListener('click', function (e) {
        e.preventDefault(); resetNavigation();
        mainContent.style.display = 'block'; homeLink.classList.add('active');
    });
    readmeLink.addEventListener('click', function (e) {
        e.preventDefault(); resetNavigation();
        readmeContent.style.display = 'block'; readmeLink.classList.add('active');
    });
    promptsLink.addEventListener('click', function (e) {
        e.preventDefault(); resetNavigation();
        promptsContent.style.display = 'block'; promptsLink.classList.add('active');
        promptsFrame.src = 'https://vouchervision-go-738307415303.us-central1.run.app/prompts-ui' + (document.body.classList.contains('dark-mode') ? '?dark=1' : '');
        promptsContent.classList.add('loading');
        promptsFrame.onload = function () { promptsContent.classList.remove('loading'); };
    });
    if (impactLink) {
        impactLink.addEventListener('click', function (e) {
            e.preventDefault(); resetNavigation();
            document.getElementById('impactContent').style.display = 'block'; impactLink.classList.add('active');
            loadImpact();
        });
    }
    changelogLink.addEventListener('click', function (e) {
        e.preventDefault(); resetNavigation();
        changelogContent.style.display = 'block'; changelogLink.classList.add('active');
    });
    signupLink.addEventListener('click', function (e) {
        e.preventDefault(); resetNavigation();
        signupContent.style.display = 'block'; signupLink.classList.add('active');
        signupFrame.src = 'https://vouchervision-go-738307415303.us-central1.run.app/signup' + (document.body.classList.contains('dark-mode') ? '?dark=1' : '');
        signupContent.classList.add('loading');
        signupFrame.onload = function () { signupContent.classList.remove('loading'); };
    });

    // Load IMPACT.md into the Impact tab
    fetch('./IMPACT.md')
        .then(response => { if (!response.ok) throw new Error('Network response was not ok'); return response.text(); })
        .then(data => {
            const converter = new showdown.Converter({ tables: true, tasklists: true, strikethrough: true, ghCodeBlocks: true });
            document.getElementById('impactTabContent').innerHTML = converter.makeHtml(data);
        })
        .catch(error => {
            document.getElementById('impactTabContent').innerHTML = '<div class="error">Error loading IMPACT.md.</div>';
        });

    // LLM model change logging
    document.querySelectorAll('input[name="llm_model"]').forEach(radio => {
        radio.addEventListener('change', function() {
            console.log(`LLM model changed to: ${this.value}`);
            logDebug(`LLM model selection changed to: ${this.value}`);
        });
    });
});

// ---------- Mapbox Integration ----------
(function() {
    let MAPBOX_ACCESS_TOKEN = null;
    fetch('./secret_mapbox.yaml')
        .then(resp => { if (!resp.ok) throw new Error('Failed to load secret_mapbox.yaml: ' + resp.status); return resp.text(); })
        .then(text => { const parsed = jsyaml.load(text); MAPBOX_ACCESS_TOKEN = parsed.mapbox_access_token; logDebug('Mapbox token loaded from secret_mapbox.yaml'); })
        .catch(err => { console.error('[Map Error] Could not load secret_mapbox.yaml:', err); });

    let map = null;
    let mapboxLoaded = typeof mapboxgl !== 'undefined';

    function logDebugMap(message, ...args) { console.log(`[Map Debug] ${message}`, ...args); }
    function logErrorMap(message, ...args) { console.error(`[Map Error] ${message}`, ...args); }

    function createOrUpdateGlobalMap(data) {
        const mapContainerElement = document.getElementById('global-map-container');
        const statusElement = document.getElementById('global-map-coord-status');
        if (!mapContainerElement || !statusElement) return;
        if (typeof mapboxgl === 'undefined') { mapContainerElement.innerHTML = '<div style="padding: 20px; text-align: center; color: #d32f2f;">Mapbox GL JS library not loaded.</div>'; return; }
        mapboxLoaded = true;
        if (!MAPBOX_ACCESS_TOKEN) { mapContainerElement.innerHTML = '<div style="padding: 20px; text-align: center; color: #d32f2f;">Mapbox token missing.</div>'; return; }
        mapboxgl.accessToken = MAPBOX_ACCESS_TOKEN;

        let lat = 0, lng = 0, hasValidCoordinates = false;
        let sourceData = data;
        if (data && data.filename) { sourceData = data; }
        const formattedJson = sourceData ? sourceData.formatted_json || null : null;

        if (formattedJson && formattedJson.decimalLatitude && formattedJson.decimalLongitude) {
            lat = parseFloat(formattedJson.decimalLatitude);
            lng = parseFloat(formattedJson.decimalLongitude);
            hasValidCoordinates = !isNaN(lat) && !isNaN(lng) && lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180;
        }

        statusElement.className = 'coord-status ' + (hasValidCoordinates ? 'valid' : 'invalid');
        statusElement.innerHTML = hasValidCoordinates ? `Coordinates found: ${lat.toFixed(4)}, ${lng.toFixed(4)}` : (data ? 'No valid coordinates in last result.' : 'Waiting for results with coordinates...');

        if (map && typeof map.remove === 'function') {
            try {
                if (map.marker) { map.marker.remove(); map.marker = null; }
                map.flyTo({ center: hasValidCoordinates ? [lng, lat] : [0, 0], zoom: hasValidCoordinates ? 10 : 1, essential: true });
                if (hasValidCoordinates) {
                    const popupContent = createPopupContent(formattedJson);
                    setTimeout(() => {
                        if (map && map.addControl) {
                            map.marker = new mapboxgl.Marker({ color: '#4CAF50' }).setLngLat([lng, lat]).setPopup(new mapboxgl.Popup().setHTML(popupContent)).addTo(map);
                        }
                    }, 50);
                }
                requestAnimationFrame(() => { if (map && map.resize) map.resize(); });
            } catch(e) { logErrorMap("Error during map update:", e); }
        } else {
            if (mapContainerElement.classList.contains('mapboxgl-map')) return;
            mapContainerElement.innerHTML = '';
            try {
                map = new mapboxgl.Map({ container: 'global-map-container', style: 'mapbox://styles/mapbox/outdoors-v12', center: [0, 0], zoom: 1 });
                map.addControl(new mapboxgl.NavigationControl(), 'top-right');
                map.on('load', () => {
                    if (hasValidCoordinates) {
                        map.marker = new mapboxgl.Marker({ color: '#4CAF50' }).setLngLat([lng, lat]).setPopup(new mapboxgl.Popup().setHTML(createPopupContent(formattedJson))).addTo(map);
                    }
                    requestAnimationFrame(() => { if (map && map.resize) map.resize(); });
                });
                map.on('error', (e) => {
                    logErrorMap('Global Mapbox error:', e);
                    mapContainerElement.innerHTML = `<div style="padding: 20px; text-align: center; color: #d32f2f;">Error loading map: ${e.error ? e.error.message : 'Unknown error'}</div>`;
                    map = null;
                });
            } catch (initError) {
                logErrorMap('Error initializing global map:', initError);
                mapContainerElement.innerHTML = `<div style="padding: 20px; text-align: center; color: #d32f2f;">Error initializing map: ${initError.message}</div>`;
                map = null;
            }
        }
    }

    function createPopupContent(formattedJson) {
        if (!formattedJson) return 'No details available.';
        let content = `<strong>${formattedJson.scientificName || 'Unknown specimen'}</strong><br>`;
        if (formattedJson.collectionDate) content += `Date: ${formattedJson.collectionDate}<br>`;
        if (formattedJson.collectedBy) content += `Collector: ${formattedJson.collectedBy}<br>`;
        if (formattedJson.locality) content += `<small>Locality: ${formattedJson.locality.substring(0, 100)}...</small>`;
        return content;
    }

    function initializeGlobalMap() {
        if (!mapboxLoaded) return;
        createOrUpdateGlobalMap(null);
    }

    // Expose map update for result history switching
    window.updateMapFromData = function(data) {
        createOrUpdateGlobalMap(data);
    };

    function monitorResults() {
        ['singleResults', 'batchUrlResults', 'batchImageResults'].forEach(function(containerId) {
            const container = document.getElementById(containerId);
            if (container) watchContainer(container);
        });
    }

    function watchContainer(container) {
        const observer = new MutationObserver(function() {
            checkParentContainerForJson(container);
        });
        observer.observe(container, { childList: true, subtree: true });
    }

    function checkParentContainerForJson(parentContainer) {
        const jsonContentElement = parentContainer.querySelector('.json-content');
        if (jsonContentElement) {
            setTimeout(() => {
                try {
                    const currentContent = jsonContentElement.textContent;
                    if (!currentContent.trim()) return;
                    const jsonData = JSON.parse(currentContent);
                    createOrUpdateGlobalMap(jsonData);
                } catch (e) { logErrorMap('Could not parse JSON:', e); }
            }, 50);
        }
    }

    document.addEventListener('DOMContentLoaded', function() {
        fetch('./secret_mapbox.yaml')
            .then(resp => { if (!resp.ok) throw new Error('Failed to load secret_mapbox.yaml'); return resp.text(); })
            .then(text => {
                MAPBOX_ACCESS_TOKEN = jsyaml.load(text).mapbox_access_token;
                setTimeout(() => {
                    mapboxLoaded = typeof mapboxgl !== 'undefined';
                    if (!mapboxLoaded) return;
                    initializeGlobalMap();
                    monitorResults();
                }, 150);
            })
            .catch(err => { logErrorMap('Could not load Mapbox token:', err); });
    });
})();

// ---------- Impact Summary ----------
(function() {
    const API_BASE = window.VVGO_API_BASE || location.origin;

    // Formatters
    function fmtCO2(g){ if(g>=1e9)return(g/1e9).toFixed(2)+' kt CO\u2082e'; if(g>=1e6)return(g/1e6).toFixed(2)+' t CO\u2082e'; if(g>=1e3)return((g/1e3).toLocaleString(undefined,{maximumFractionDigits:1}))+' kg CO\u2082e'; return Math.round(g).toLocaleString()+' g CO\u2082e'; }
    function fmtWh(wh){ if(wh>=1e6)return(wh/1e6).toFixed(2)+' MWh'; if(wh>=1e3)return(wh/1e3).toFixed(2)+' kWh'; return (wh>=100?wh.toLocaleString(undefined,{maximumFractionDigits:0}):wh.toLocaleString(undefined,{maximumFractionDigits:1}))+' Wh'; }
    function fmtTokens(n){ if(n>=1e9)return(n/1e9).toFixed(2)+'B'; if(n>=1e6)return(n/1e6).toFixed(2)+'M'; if(n>=1e3)return(n/1e3).toFixed(2)+'K'; return String(n); }
    function fmtVolumeML(ml){ if(ml>=1e6)return(ml/1e6).toFixed(2)+' m\u00B3'; if(ml>=1e3)return(ml/1e3).toFixed(2)+' L'; return Math.round(ml).toLocaleString()+' mL'; }

    function renderSummary(t) {
        const items = [
            { label:'Images Processed', value:Number(t.total_images_processed||0).toLocaleString(), sub:'All time', icon:'\uD83D\uDDBC\uFE0F' },
            { label:'Total Tokens', value:fmtTokens(t.total_tokens_all||0), sub:'Prompt + completion', icon:'\uD83D\uDD20' },
            { label:'Energy Used', value:fmtWh(t.total_watt_hours||0), sub:'Aggregated Wh', icon:'\u26A1' },
            { label:'Estimated CO\u2082e', value:fmtCO2(t.total_grams_CO2||0), sub:'Sum across usage', icon:'\uD83C\uDF0D' },
            { label:'Water (est.)', value:fmtVolumeML(t.total_mL_water||0), sub:'Lifecycle estimate', icon:'\uD83D\uDCA7' },
        ];
        return '<div class="vv-grid">' + items.map(function(i){
            return '<div class="vv-card impact-tile"><div class="impact-icon">'+i.icon+'</div><div class="impact-label">'+i.label+'</div><div class="impact-value">'+i.value+'</div><div class="impact-sub">'+i.sub+'</div></div>';
        }).join('') + '</div>';
    }

    function getEffectiveApiKey(){
        var el = document.getElementById('apiKey');
        var fromDataset = (el && el.dataset.apiKey || '').trim();
        if (fromDataset) return fromDataset;
        return (localStorage.getItem('vouchervision_api_key') || '').trim();
    }
    function getEffectiveToken(){
        var el = document.getElementById('authToken');
        var fromDataset = (el && el.dataset.authToken || '').trim();
        if (fromDataset) return fromDataset;
        return (localStorage.getItem('vouchervision_auth_token') || '').trim();
    }

    function updateButtonState(){
        var btn = document.getElementById('showImpactBtn');
        if (!btn) return;
        var apiReady = (typeof isApiKeySet === 'function') ? isApiKeySet() : !!getEffectiveApiKey();
        var tokReady = (typeof isAuthTokenSet === 'function') ? isAuthTokenSet() : !!getEffectiveToken();
        btn.disabled = !(apiReady || tokReady);
    }

    function attachObservers(){
        ['apiKey','authToken'].forEach(function(id){
            var el = document.getElementById(id);
            if (!el) return;
            new MutationObserver(updateButtonState).observe(el, { attributes:true });
        });
        window.addEventListener('storage', updateButtonState);
        setTimeout(updateButtonState, 300);
    }

    async function fetchImpact(){
        var btn = document.getElementById('showImpactBtn');
        var status = document.getElementById('impactStatus');
        var out = document.getElementById('impactSummary');
        if (!btn || !status || !out) return;

        btn.disabled = true;
        status.textContent = 'Fetching impact summary\u2026';
        out.innerHTML = '';

        try {
            var headers = { 'Content-Type':'application/json' };
            var apiKey = getEffectiveApiKey();
            var token  = getEffectiveToken();
            if (apiKey) headers['X-API-Key'] = apiKey;
            else if (token) headers['Authorization'] = 'Bearer ' + token;

            var resp = await fetch(API_BASE + '/impact', { method:'GET', mode:'cors', cache:'no-cache', headers:headers });
            if (!resp.ok) {
                var text = await resp.text().catch(function(){ return ''; });
                throw new Error('HTTP ' + resp.status + ': ' + (text || resp.statusText));
            }
            var data = await resp.json();
            if (!data || !data.totals) throw new Error('Unexpected response shape.');
            status.textContent = 'Impact summary loaded';
            out.innerHTML = renderSummary(data.totals);
        } catch (err) {
            console.error('Impact fetch error:', err);
            status.textContent = (err && err.message) || 'Failed to fetch impact summary';
        } finally {
            updateButtonState();
        }
    }

    document.addEventListener('DOMContentLoaded', function(){
        var btn = document.getElementById('showImpactBtn');
        if (btn) btn.addEventListener('click', fetchImpact);
        attachObservers();
        updateButtonState();
    });
})();

// ---------- API Status Indicator ----------
const ENABLE_API_CHECK = false;
if (ENABLE_API_CHECK) {
    (function() {
        let statusCheckInterval;
        let isCheckingStatus = false;
        function createStatusIndicator() {
            const statusContainer = document.createElement('div');
            statusContainer.id = 'api-status-indicator';
            statusContainer.style.cssText = `position: fixed; top: 10px; right: 10px; background: rgba(255,255,255,0.95); border: 1px solid #ddd; border-radius: 20px; padding: 8px 12px; font-size: 12px; font-weight: 500; box-shadow: 0 2px 8px rgba(0,0,0,0.1); z-index: 1000; transition: all 0.3s ease; backdrop-filter: blur(5px); max-width: 200px; text-align: center; cursor: pointer;`;
            statusContainer.addEventListener('click', function() { if (!isCheckingStatus) checkAPIStatus(); });
            statusContainer.title = 'Click to refresh API status';
            document.body.insertBefore(statusContainer, document.body.firstChild);
            return statusContainer;
        }
        function updateStatusDisplay(isAvailable, isChecking) {
            if (isChecking === undefined) isChecking = false;
            const container = document.getElementById('api-status-indicator');
            if (!container) return;
            if (isChecking) { container.innerHTML = '<span style="color: #666;">Checking API...</span>'; container.style.borderColor = '#ccc'; return; }
            if (isAvailable) { container.innerHTML = '<span style="color: #4CAF50;">VVGO API: Available</span>'; container.style.borderColor = '#4CAF50'; container.style.backgroundColor = 'rgba(232, 245, 233, 0.95)'; }
            else { container.innerHTML = '<span style="color: #FF9800;">VVGO API: Down for Maintenance</span>'; container.style.borderColor = '#FF9800'; container.style.backgroundColor = 'rgba(255, 243, 224, 0.95)'; }
        }
        async function checkAPIStatus() {
            if (isCheckingStatus) return;
            isCheckingStatus = true;
            updateStatusDisplay(false, true);
            try {
                const healthResponse = await fetch('https://vouchervision-go-738307415303.us-central1.run.app/health', { method: 'GET', mode: 'cors', cache: 'no-cache', headers: { 'Content-Type': 'application/json' } });
                if (healthResponse.ok) {
                    const healthData = await healthResponse.json();
                    const corsResponse = await fetch('https://vouchervision-go-738307415303.us-central1.run.app/cors-test', { method: 'GET', mode: 'cors', cache: 'no-cache' });
                    updateStatusDisplay(corsResponse.ok);
                } else { updateStatusDisplay(false); }
            } catch (error) { updateStatusDisplay(false); }
            finally { isCheckingStatus = false; }
        }
        function startStatusMonitoring() {
            setTimeout(checkAPIStatus, 1500);
            statusCheckInterval = setInterval(checkAPIStatus, 30000);
        }
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function() { createStatusIndicator(); startStatusMonitoring(); });
        else { createStatusIndicator(); startStatusMonitoring(); }
    })();
}

// ===================================================================
// Dark Mode Toggle
// ===================================================================
(function () {
    function applyDarkMode(enabled) {
        document.body.classList.toggle('dark-mode', enabled);
        try { localStorage.setItem('vvgo-dark-mode', enabled ? '1' : '0'); } catch (e) {}
        // Sync dark mode to any loaded iframes via postMessage
        var iframes = document.querySelectorAll('iframe');
        for (var i = 0; i < iframes.length; i++) {
            try { iframes[i].contentWindow.postMessage({ vvgoDarkMode: enabled }, '*'); } catch (e) {}
        }
    }

    function initDarkMode() {
        var saved = null;
        try { saved = localStorage.getItem('vvgo-dark-mode'); } catch (e) {}
        var prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        var enabled = saved === '1' || (saved === null && prefersDark);
        applyDarkMode(enabled);

        var btn = document.getElementById('darkModeToggle');
        if (btn) {
            btn.addEventListener('click', function () {
                var isDark = document.body.classList.contains('dark-mode');
                applyDarkMode(!isDark);
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initDarkMode);
    } else {
        initDarkMode();
    }
})();
