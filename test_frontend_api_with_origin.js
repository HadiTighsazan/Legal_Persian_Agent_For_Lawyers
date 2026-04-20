// Test script to simulate browser fetch to API with Origin header
const https = require('https');
const http = require('http');

const url = 'http://localhost/api/health/';

console.log('Testing API endpoint with Origin header:', url);

const options = {
  headers: {
    'Origin': 'http://localhost:5173'
  }
};

const req = http.get(url, options, (res) => {
  console.log('Status:', res.statusCode);
  console.log('Headers:', JSON.stringify(res.headers, null, 2));
  
  let data = '';
  res.on('data', (chunk) => {
    data += chunk;
  });
  
  res.on('end', () => {
    console.log('Response body (first 500 chars):', data.substring(0, 500));
    
    // Try to parse as JSON
    try {
      const json = JSON.parse(data);
      console.log('Successfully parsed as JSON:', json);
    } catch (e) {
      console.log('Failed to parse as JSON:', e.message);
      console.log('Response starts with:', data.substring(0, 50));
    }
  });
});

req.on('error', (err) => {
  console.error('Request error:', err);
});

req.end();