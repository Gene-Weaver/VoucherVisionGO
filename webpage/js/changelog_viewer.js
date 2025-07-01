function setupChangelogViewer() {
    const changelogContainer = document.getElementById('changelogContent');
    if (!changelogContainer) {
        console.error('Changelog container not found.');
        return;
    }

    // Function to render the changelog data into the DOM
    function renderChangelog(changelog) {
        changelogContainer.innerHTML = '<h1>VoucherVisionGO Changelog</h1>'; // Clear loading message and add title

        changelog.forEach(version => {
            const versionBlock = document.createElement('div');
            versionBlock.className = 'version-block';

            const header = document.createElement('div');
            header.className = 'version-header';
            header.innerHTML = `
                <h2>Version ${version.version}</h2>
                <span class="date">${version.date}</span>
            `;

            const changeList = document.createElement('ul');
            changeList.className = 'change-list';

            if (version.changes && Array.isArray(version.changes)) {
                version.changes.forEach(change => {
                    const changeItem = document.createElement('li');
                    changeItem.className = 'change-item';
                    
                    const tag = document.createElement('span');
                    const changeType = change.type || 'Update';
                    tag.className = `change-tag tag-${changeType}`;
                    tag.textContent = changeType;
                    
                    const description = document.createElement('div');
                    description.className = 'change-description';
                    description.textContent = change.description || 'No description.';

                    changeItem.appendChild(tag);
                    changeItem.appendChild(description);
                    changeList.appendChild(changeItem);
                });
            }

            versionBlock.appendChild(header);
            versionBlock.appendChild(changeList);
            changelogContainer.appendChild(versionBlock);
        });
    }

    // Function to show a status message (loading or error)
    function showStatus(message, isError = false) {
        changelogContainer.innerHTML = `
            <h1>VoucherVisionGO Changelog</h1>
            <p style="text-align: center; color: ${isError ? '#e74c3c' : '#7f8c8d'};">${message}</p>
        `;
    }

    // Function to fetch changelog data from the API
    function fetchChangelog() {
        showStatus('Loading changelog...');
        fetch('https://vouchervision-go-738307415303.us-central1.run.app/changelog')
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                if (data.status === 'success' && data.changelog) {
                    localStorage.setItem('vouchervision_changelog', JSON.stringify(data.changelog));
                    renderChangelog(data.changelog);
                } else {
                    throw new Error(data.error || 'Failed to load changelog data.');
                }
            })
            .catch(error => {
                console.error('Error fetching changelog:', error);
                showStatus(`Could not load changelog. ${error.message}`, true);
            });
    }

    // --- Main Logic ---
    // Try to load from cache first for instant display
    const cachedChangelog = localStorage.getItem('vouchervision_changelog');
    if (cachedChangelog) {
        try {
            renderChangelog(JSON.parse(cachedChangelog));
            // Then, fetch a fresh copy in the background
            fetchChangelog(); 
        } catch (e) {
            // If cache is invalid, fetch from network
            fetchChangelog();
        }
    } else {
        // If no cache, fetch from network
        fetchChangelog();
    }
}

document.addEventListener('DOMContentLoaded', setupChangelogViewer);