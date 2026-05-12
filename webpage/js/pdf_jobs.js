const PDF_JOB_API_BASE = 'https://vouchervision-go-738307415303.us-central1.run.app';
let activePdfJobId = null;
let activePdfJobPoller = null;

function ensureWebsiteAuth() {
    const authMethod = $('input[name="authMethod"]:checked').val();
    if (authMethod === 'apiKey') {
        const apiKeyField = document.getElementById('apiKey');
        const apiKey = apiKeyField ? (apiKeyField.dataset.apiKey || apiKeyField.value.trim()) : '';
        if (!apiKey || apiKey === 'YOUR_API_KEY') {
            return false;
        }
        return true;
    }
    const authTokenField = document.getElementById('authToken');
    const authToken = authTokenField ? (authTokenField.dataset.authToken || authTokenField.value.trim()) : '';
    return Boolean(authToken);
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatPdfJobTime(value) {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
}

function buildPdfJobStatusCard(job, pages = []) {
    if (!job) {
        return '<p>No PDF job running right now.</p>';
    }

    const downloadUrl = job.download_url || '';
    const pageCount = Number(job.page_count || 0);
    const completedPages = Number(job.completed_pages || 0);
    const progressPercent = Number(job.progress_percent || 0);
    const hasDownload = Boolean(downloadUrl) && (job.status === 'completed' || job.status === 'completed_with_errors');

    let pageSummary = '';
    if (pages.length > 0) {
        pageSummary = `
            <div class="pdf-job-pages">
                <strong>Pages:</strong>
                <ul>
                    ${pages.slice(0, 8).map(page => `
                        <li>
                            <span>${escapeHtml(page.filename || `Page ${page.page_index}`)}</span>
                            <span>${escapeHtml(page.status || 'queued')}</span>
                        </li>
                    `).join('')}
                </ul>
                ${pages.length > 8 ? `<p class="pdf-job-pages-more">Showing 8 of ${pages.length} pages.</p>` : ''}
            </div>
        `;
    }

    return `
        <div class="pdf-job-status-card">
            <div class="pdf-job-status-top">
                <div>
                    <h4>${escapeHtml(job.source_pdf_filename || job.job_id)}</h4>
                    <p class="pdf-job-status-meta">Status: <strong>${escapeHtml(job.status || 'queued')}</strong> • Phase: ${escapeHtml(job.phase || 'queued')}</p>
                </div>
                <div class="pdf-job-status-actions">
                    ${hasDownload ? `<a class="button" href="${escapeHtml(downloadUrl)}">Download ZIP</a>` : '<span class="pdf-job-pill">Bundle not ready yet</span>'}
                </div>
            </div>
            <div class="pdf-job-progress">
                <div class="pdf-job-progress-bar">
                    <div class="pdf-job-progress-fill" style="width:${progressPercent}%"></div>
                </div>
                <p>${completedPages} of ${pageCount || '?'} pages finished • ${progressPercent}% complete</p>
            </div>
            <div class="pdf-job-status-grid">
                <div><strong>Email:</strong> ${escapeHtml(job.email_status || 'pending')}</div>
                <div><strong>Created:</strong> ${escapeHtml(formatPdfJobTime(job.created_at))}</div>
                <div><strong>Expires:</strong> ${escapeHtml(formatPdfJobTime(job.expires_at))}</div>
                <div><strong>Availability:</strong> 1 week</div>
            </div>
            ${job.error_summary ? `<p class="error">Latest issue: ${escapeHtml(job.error_summary)}</p>` : ''}
            ${pageSummary}
        </div>
    `;
}

function renderPdfJobTable(jobs) {
    const tbody = document.getElementById('pdfJobsTableBody');
    if (!tbody) return;

    if (!jobs || jobs.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="pdf-jobs-empty">No PDF jobs yet.</td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = jobs.map(job => {
        const isDownloadReady = job.status === 'completed' || job.status === 'completed_with_errors';
        const downloadLabel = isDownloadReady ? 'Download ZIP' : 'Waiting...';
        const downloadCell = isDownloadReady
            ? `<a href="${escapeHtml(job.download_url || `/pdf-jobs/${job.job_id}/download`)}">Download ZIP</a>`
            : `<span>${downloadLabel}</span>`;
        return `
            <tr data-job-id="${escapeHtml(job.job_id)}">
                <td>${escapeHtml(job.source_pdf_filename || job.job_id)}</td>
                <td>${escapeHtml(job.status || 'queued')}</td>
                <td>${escapeHtml(`${job.completed_pages || 0}/${job.page_count || 0}`)}</td>
                <td>${escapeHtml(job.email_status || 'pending')}</td>
                <td>${escapeHtml(formatPdfJobTime(job.expires_at))}</td>
                <td>${downloadCell}</td>
            </tr>
        `;
    }).join('');

    tbody.querySelectorAll('tr[data-job-id]').forEach(row => {
        row.addEventListener('click', function(event) {
            if (event.target.tagName.toLowerCase() === 'a') {
                return;
            }
            const jobId = this.dataset.jobId;
            if (jobId) {
                activePdfJobId = jobId;
                loadPdfJobDetail(jobId);
            }
        });
    });
}

async function fetchPdfJobs() {
    if (!ensureWebsiteAuth()) {
        return [];
    }
    const headers = getAuthHeaders();
    const response = await fetch(`${PDF_JOB_API_BASE}/pdf-jobs?limit=15`, {
        method: 'GET',
        headers,
    });
    if (!response.ok) {
        throw new Error(`Unable to load PDF jobs (${response.status})`);
    }
    const payload = await response.json();
    return payload.jobs || [];
}

async function refreshPdfJobsList() {
    try {
        const jobs = await fetchPdfJobs();
        renderPdfJobTable(jobs);
        if (!activePdfJobId && jobs.length > 0) {
            activePdfJobId = jobs[0].job_id;
            loadPdfJobDetail(activePdfJobId);
        }
    } catch (error) {
        logDebug('Error loading PDF jobs', error.message || error);
        renderPdfJobTable([]);
    }
}

async function loadPdfJobDetail(jobId) {
    const statusEl = document.getElementById('pdfJobStatus');
    if (!statusEl) return;

    try {
        const headers = getAuthHeaders();
        const response = await fetch(`${PDF_JOB_API_BASE}/pdf-jobs/${encodeURIComponent(jobId)}`, {
            method: 'GET',
            headers,
        });
        if (!response.ok) {
            throw new Error(`Unable to load PDF job (${response.status})`);
        }
        const payload = await response.json();
        const job = payload.job || {};
        if (payload.download_url) {
            job.download_url = payload.download_url;
        }
        statusEl.classList.remove('empty');
        statusEl.innerHTML = buildPdfJobStatusCard(job, payload.pages || []);

        if (job.status === 'queued' || job.status === 'running' || job.status === 'finalizing') {
            startPdfJobPolling(jobId);
        } else {
            stopPdfJobPolling();
        }
    } catch (error) {
        statusEl.classList.remove('empty');
        statusEl.innerHTML = `<p class="error">${escapeHtml(error.message || String(error))}</p>`;
        stopPdfJobPolling();
    }
}

function startPdfJobPolling(jobId) {
    stopPdfJobPolling();
    activePdfJobPoller = window.setInterval(async () => {
        await loadPdfJobDetail(jobId);
        await refreshPdfJobsList();
    }, 6000);
}

function stopPdfJobPolling() {
    if (activePdfJobPoller) {
        window.clearInterval(activePdfJobPoller);
        activePdfJobPoller = null;
    }
}

async function submitPdfJob() {
    const fileInput = document.getElementById('pdfJobFileInput');
    const statusEl = document.getElementById('pdfJobStatus');
    const button = document.getElementById('submitPdfJobButton');

    if (!ensureWebsiteAuth()) {
        alert('Please provide a valid API key or auth token first.');
        return;
    }

    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
        alert('Please choose a PDF file first.');
        return;
    }

    const file = fileInput.files[0];
    if (!file.name.toLowerCase().endsWith('.pdf')) {
        alert('Only PDF uploads are supported in the PDF Jobs tab.');
        return;
    }

    const formData = new FormData();
    formData.append('file', file);
    getSelectedEngines().forEach(engine => formData.append('engines', engine));

    const promptTemplate = $('#promptTemplate').val();
    const llmModel = getSelectedModel();
    if (promptTemplate) formData.append('prompt', promptTemplate);
    if (llmModel) formData.append('llm_model', llmModel);
    if ($('#ocrOnly').is(':checked')) formData.append('ocr_only', 'true');
    if ($('#notebookMode').is(':checked')) formData.append('notebook_mode', 'true');
    if ($('#includeWfo').is(':checked')) formData.append('include_wfo', 'true');
    if ($('#includeCop90').is(':checked')) formData.append('include_cop90', 'true');
    if ($('#skipLabelCollage').is(':checked')) formData.append('skip_label_collage', 'true');

    const headers = getAuthHeaders();
    delete headers['Content-Type'];

    button.disabled = true;
    button.textContent = 'Queueing PDF job...';
    statusEl.classList.remove('empty');
    statusEl.innerHTML = `
        <div class="pdf-job-status-card">
            <h4>${escapeHtml(file.name)}</h4>
            <p>Uploading PDF and queueing async processing...</p>
            <p class="pdf-routing-note">You will receive an email when the ZIP/XLSX bundle is ready. It will stay available for 1 week.</p>
        </div>
    `;

    try {
        const response = await fetch(`${PDF_JOB_API_BASE}/process-pdf-async`, {
            method: 'POST',
            headers,
            body: formData,
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.error || `Unable to queue PDF job (${response.status})`);
        }

        activePdfJobId = payload.job_id;
        logDebug('Queued async PDF job', payload);
        await refreshPdfJobsList();
        await loadPdfJobDetail(activePdfJobId);
    } catch (error) {
        logDebug('Error queueing PDF job', error.message || error);
        statusEl.innerHTML = `<p class="error">${escapeHtml(error.message || String(error))}</p>`;
        stopPdfJobPolling();
    } finally {
        button.disabled = false;
        button.textContent = 'Start PDF Job';
    }
}

$(document).ready(function() {
    const fileInput = document.getElementById('pdfJobFileInput');
    if (fileInput) {
        fileInput.addEventListener('change', async function() {
            const statusEl = document.getElementById('pdfJobStatus');
            if (!this.files || this.files.length === 0) {
                statusEl.classList.add('empty');
                statusEl.innerHTML = '<p>No PDF job running right now.</p>';
                return;
            }

            const file = this.files[0];
            let pageCount = '?';
            if (typeof countPdfPages === 'function') {
                const countedPages = await countPdfPages(file);
                if (countedPages > 0) {
                    pageCount = countedPages;
                }
            }

            statusEl.classList.remove('empty');
            statusEl.innerHTML = `
                <div class="pdf-job-status-card">
                    <h4>${escapeHtml(file.name)}</h4>
                    <p>Selected PDF with approximately <strong>${escapeHtml(pageCount)}</strong> page(s).</p>
                    <p class="pdf-routing-note">PDF jobs are processed asynchronously and emailed to you when ready. Downloads stay available for 1 week.</p>
                </div>
            `;
        });
    }

    $('#submitPdfJobButton').on('click', submitPdfJob);
    $('#refreshPdfJobsButton').on('click', refreshPdfJobsList);
    document.querySelectorAll('.tab[data-tab="PDFJobs"]').forEach(tab => {
        tab.addEventListener('click', function() {
            refreshPdfJobsList();
            if (activePdfJobId) {
                loadPdfJobDetail(activePdfJobId);
            }
        });
    });

    refreshPdfJobsList();
});
