const fs = require('fs');
const http = require('http');
const path = require('path');

const DIST = path.join(__dirname, 'dist');
const PORT = Number(process.env.FRONTEND_PORT || 4173);
const TYPES = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.js': 'text/javascript; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.webp': 'image/webp',
};

if (!fs.existsSync(DIST)) {
  throw new Error('Frontend output is missing. Run npm run build first.');
}

http.createServer((req, res) => {
  let requestPath;
  try {
    requestPath = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  } catch {
    res.writeHead(400).end('Bad request');
    return;
  }
  if (requestPath === '/') requestPath = '/index.html';
  if (requestPath === '/attendance') requestPath = '/attendance.html';

  const file = path.resolve(DIST, `.${requestPath}`);
  if (!file.startsWith(`${DIST}${path.sep}`) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    res.writeHead(404).end('Not found');
    return;
  }

  res.writeHead(200, { 'Content-Type': TYPES[path.extname(file).toLowerCase()] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
}).listen(PORT, () => console.log(`Frontend running at http://localhost:${PORT}`));