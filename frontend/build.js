const fs = require('fs');
const path = require('path');
const dotenv = require('dotenv');

const ROOT = __dirname;
const PUBLIC = path.join(ROOT, 'public');
const DIST = path.join(ROOT, 'dist');

dotenv.config({ path: path.join(ROOT, '.env') });

const configuredApiUrl = process.env.API_BASE_URL
  || (process.argv.includes('--dev') ? 'http://localhost:3000' : undefined);
if (!configuredApiUrl) {
  throw new Error('Set API_BASE_URL in frontend/.env or the frontend deployment environment.');
}

let apiBaseUrl;
try {
  const parsed = new URL(configuredApiUrl);
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password
    || parsed.pathname !== '/' || parsed.search || parsed.hash) {
    throw new Error();
  }
  apiBaseUrl = parsed.origin;
} catch {
  throw new Error('API_BASE_URL must be an http(s) origin without a path or credentials.');
}

fs.rmSync(DIST, { recursive: true, force: true });
fs.cpSync(PUBLIC, DIST, { recursive: true });
fs.writeFileSync(
  path.join(DIST, 'config.js'),
  `window.APP_CONFIG = Object.freeze({ API_BASE_URL: ${JSON.stringify(apiBaseUrl)} });\n`,
  'utf8',
);
console.log(`Built frontend for API origin ${apiBaseUrl}`);