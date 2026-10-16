'use strict';

/**
 * Ecronx Manpower - Node.js integration server.
 *
 * Architecture (after the Django integration):
 *
 *   Browser (existing static frontend)
 *        |  same /api/* routes as before
 *        v
 *   Node.js (this file)  -> static hosting, CORS, uploads, and a thin proxy
 *        |
 *        v
 *   Django + database    -> system of record for accounts, attendance,
 *                           sites, corrections and website content.
 *
 * There is exactly ONE database and ONE authentication system (Django).
 * Nothing is persisted in backend/data/*.json any more.
 *
 * To let the browser talk to Django directly instead, build the frontend with
 * API_BASE_URL=http://localhost:8000 and run only Django - the routes match.
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const express = require('express');
const cors = require('cors');
require('dotenv').config();

const { djangoJson, djangoRaw, djangoHealth, DjangoError } = require('./djangoClient');

const UPLOADS = path.resolve(process.env.UPLOADS_DIR || path.join(__dirname, 'uploads'));
const SEED_UPLOADS = path.join(__dirname, 'uploads');
const PORT = process.env.PORT || 3000;
const SERVE_FRONTEND = process.env.SERVE_FRONTEND === 'true';
const FRONTEND_DIST = path.resolve(process.env.FRONTEND_DIST || path.join(__dirname, '../frontend/dist'));
const allowedOrigins = (
  process.env.CORS_ORIGINS
  || 'http://localhost:3000,http://127.0.0.1:3000,http://localhost:4173,http://127.0.0.1:4173'
).split(',').map((origin) => origin.trim()).filter(Boolean);

/** Copy any seed uploads into the persistent uploads folder on first run. */
function ensureUploads() {
  fs.mkdirSync(UPLOADS, { recursive: true });
  if (path.resolve(SEED_UPLOADS) === UPLOADS || !fs.existsSync(SEED_UPLOADS)) return;
  for (const name of fs.readdirSync(SEED_UPLOADS)) {
    const source = path.join(SEED_UPLOADS, name);
    const target = path.join(UPLOADS, name);
    if (fs.statSync(source).isFile() && !fs.existsSync(target)) fs.copyFileSync(source, target);
  }
}

/** Bearer token from the incoming request (forwarded verbatim to Django). */
function bearer(req) {
  return (req.headers.authorization || '').replace(/^Bearer\s+/i, '') || undefined;
}

/**
 * Forward a request to Django and relay its JSON response.
 * Django's own HTTP status and {"error": "..."} body are preserved so the
 * existing frontend error handling keeps working unchanged.
 */
async function proxy(req, res, pathname, options = {}) {
  try {
    const payload = await djangoJson(pathname, {
      method: options.method || req.method,
      body: options.body,
      query: options.query,
      token: bearer(req),
    });
    return res.status(200).json(payload ?? {});
  } catch (error) {
    if (error instanceof DjangoError) {
      return res.status(error.status).json({ error: error.message });
    }
    console.error('Unexpected proxy error:', error);
    return res.status(500).json({ error: 'The request could not be completed.' });
  }
}

const app = express();
app.use(cors({
  origin(origin, callback) {
    if (!origin || allowedOrigins.includes(origin)) return callback(null, true);
    return callback(new Error('This frontend origin is not allowed by CORS. Add it to CORS_ORIGINS.'));
  },
}));
app.use(express.json({ limit: '13mb' }));
app.use('/uploads', express.static(UPLOADS, { maxAge: '1h' }));

if (SERVE_FRONTEND) {
  app.get('/attendance', (req, res) => res.sendFile(path.join(FRONTEND_DIST, 'attendance.html')));
  app.use(express.static(FRONTEND_DIST));
}

// --- Health check -----------------------------------------------------------
app.get('/api/health', async (req, res) => {
  const django = await djangoHealth();
  res.status(django.reachable ? 200 : 503).json({
    ok: django.reachable,
    node: 'up',
    django: django.reachable ? 'up' : 'down',
    detail: django.reachable ? django.payload : django.error,
  });
});

// --- Website content & enquiries -------------------------------------------
app.get('/api/content', (req, res) => proxy(req, res, '/api/content'));
app.post('/api/enquiries', (req, res) => proxy(req, res, '/api/enquiries', { body: req.body }));

// --- Authentication --------------------------------------------------------
app.post('/api/admin/login', (req, res) => proxy(req, res, '/api/admin/login', { body: req.body }));
app.post('/api/admin/logout', (req, res) => proxy(req, res, '/api/admin/logout', { method: 'POST' }));
app.post('/api/attendance/employee/login', (req, res) =>
  proxy(req, res, '/api/attendance/employee/login', { body: req.body }));
app.post('/api/attendance/employee/logout', (req, res) =>
  proxy(req, res, '/api/attendance/employee/logout', { method: 'POST' }));
app.get('/api/attendance/me', (req, res) => proxy(req, res, '/api/attendance/me'));

// --- Password change / recovery --------------------------------------------
app.post('/api/password/change', (req, res) => proxy(req, res, '/api/password/change', { body: req.body }));
app.post('/api/password/reset/request', (req, res) =>
  proxy(req, res, '/api/password/reset/request', { body: req.body }));
app.post('/api/password/reset/verify', (req, res) =>
  proxy(req, res, '/api/password/reset/verify', { body: req.body }));
app.post('/api/password/reset/confirm', (req, res) =>
  proxy(req, res, '/api/password/reset/confirm', { body: req.body }));

// --- Employee attendance ----------------------------------------------------
app.post('/api/attendance/check-in', (req, res) =>
  proxy(req, res, '/api/attendance/check-in', { body: req.body }));
app.post('/api/attendance/check-out', (req, res) =>
  proxy(req, res, '/api/attendance/check-out', { body: req.body }));
app.post('/api/attendance/corrections', (req, res) =>
  proxy(req, res, '/api/attendance/corrections', { body: req.body }));

// --- Administrator attendance management ------------------------------------
app.get('/api/attendance/admin/dashboard', (req, res) =>
  proxy(req, res, '/api/attendance/admin/dashboard', { query: req.query }));
app.post('/api/attendance/admin/employees', (req, res) =>
  proxy(req, res, '/api/attendance/admin/employees', { body: req.body }));
app.patch('/api/attendance/admin/employees/:uuid', (req, res) =>
  proxy(req, res, `/api/attendance/admin/employees/${encodeURIComponent(req.params.uuid)}`, { body: req.body }));
app.delete('/api/attendance/admin/employees/:uuid', (req, res) =>
  proxy(req, res, `/api/attendance/admin/employees/${encodeURIComponent(req.params.uuid)}`, { method: 'DELETE' }));
app.post('/api/attendance/admin/employees/:uuid/password', (req, res) =>
  proxy(req, res, `/api/attendance/admin/employees/${encodeURIComponent(req.params.uuid)}/password`, { body: req.body }));
app.post('/api/attendance/admin/sites', (req, res) =>
  proxy(req, res, '/api/attendance/admin/sites', { body: req.body }));
app.post('/api/attendance/admin/leave', (req, res) =>
  proxy(req, res, '/api/attendance/admin/leave', { body: req.body }));
app.post('/api/attendance/admin/corrections/:uuid', (req, res) =>
  proxy(req, res, `/api/attendance/admin/corrections/${encodeURIComponent(req.params.uuid)}`, { body: req.body }));
app.get('/api/admin/enquiries', (req, res) => proxy(req, res, '/api/admin/enquiries'));

// --- Reports / backups (streamed, not JSON) ---------------------------------
app.get('/api/attendance/admin/backup', async (req, res) => {
  try {
    const upstream = await djangoRaw('/api/attendance/admin/backup', { token: bearer(req), query: req.query });
    if (!upstream.ok) {
      const text = await upstream.text();
      let message = `Report could not be generated (${upstream.status}).`;
      try { message = JSON.parse(text).error || message; } catch { /* keep default */ }
      return res.status(upstream.status).json({ error: message });
    }
    const buffer = Buffer.from(await upstream.arrayBuffer());
    res.status(200);
    res.set('Content-Type', upstream.headers.get('content-type') || 'application/octet-stream');
    const disposition = upstream.headers.get('content-disposition');
    if (disposition) res.set('Content-Disposition', disposition);
    res.set('Cache-Control', 'no-store');
    res.set('Content-Length', String(buffer.length));
    return res.end(buffer);
  } catch (error) {
    if (error instanceof DjangoError) return res.status(error.status).json({ error: error.message });
    console.error('Backup proxy error:', error);
    return res.status(500).json({ error: 'The report could not be downloaded.' });
  }
});

// --- Image uploads (kept local to Node; no account data involved) -----------
app.post('/api/admin/upload', (req, res) => {
  const match = String(req.body?.data || '').match(/^data:image\/(png|jpeg|jpg|webp);base64,([A-Za-z0-9+/=]+)$/);
  if (!match) return res.status(400).json({ error: 'Please choose a JPG, PNG or WebP image.' });
  const extension = match[1] === 'jpeg' ? 'jpg' : match[1];
  const name = `${crypto.randomUUID()}.${extension}`;
  const bytes = Buffer.from(match[2], 'base64');
  if (bytes.length > 8 * 1024 * 1024) {
    return res.status(413).json({ error: 'Image must be smaller than 8 MB.' });
  }
  fs.writeFileSync(path.join(UPLOADS, name), bytes);
  return res.status(201).json({ url: `/uploads/${name}` });
});

// --- Explicit "not found" for anything else under /api -----------------------
app.use('/api', (req, res) => res.status(404).json({ error: 'API route not found' }));

// --- Error handler (e.g. CORS rejections) ------------------------------------
app.use((error, req, res, next) => {
  if (res.headersSent) return next(error);
  const status = error.message && error.message.includes('CORS') ? 403 : (error.status || 500);
  return res.status(status).json({ error: status === 403 ? error.message : 'Request could not be processed.' });
});

ensureUploads();
app.listen(PORT, async () => {
  console.log(`Ecronx Node server running on port ${PORT}`);
  const django = await djangoHealth();
  if (django.reachable) {
    console.log('Connected to Django backend.');
  } else {
    console.warn(
      `WARNING: Django backend not reachable (${django.error})\n`
      + 'Start it with: .\\.venv\\Scripts\\python.exe django_backend\\manage.py runserver',
    );
  }
});
