// FOR RESTARTING
// pm2 restart vouchervisiongo

// Load environment variables (still useful for PORT potentially)
require('dotenv').config();
// console.log('MAPBOX_TOKEN loaded:', process.env.MAPBOX_TOKEN ? '✅ YES' : '❌ NO'); // No longer needed for map

const express = require('express');
const path = require('path'); // Needed for path.join
const app = express();
const port = process.env.PORT || 3001; // Use port from .env or default

// Serve static files (HTML, CSS, JS, images) from the current directory
// __dirname is the directory where server.js is located
app.use(express.static(__dirname));

// Optional: Explicitly serve index.html for the root path '/'
// This might be redundant with express.static but makes it clear.
app.get('/', function (req, res) {
    res.sendFile(path.join(__dirname, 'index.html'));
});

// Start the server
app.listen(port, function () {
    console.log(`Server running at http://localhost:${port}`);
    console.log(`Serving static files from: ${__dirname}`);
    // Removed Mapbox token warning as it's not used by server anymore
});