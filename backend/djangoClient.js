'use strict';

/**
 * Small HTTP client that forwards requests from the Node.js server to the
 * Django backend (the system of record for accounts, attendance and content).
 *
 * Kept dependency-free: uses Node's global fetch (Node 18+).
 */

const DJANGO_BASE_URL = String(process.env.DJANGO_BASE_URL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
const DJANGO_TIMEOUT_MS = Number(process.env.DJANGO_TIMEOUT_MS || 15000);

class DjangoError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = 'DjangoError';
    this.status = status || 502;
    this.payload = payload || null;
  }
}

/**
 * Call a Django API path and return the parsed JSON body.
 * Throws DjangoError carrying Django's own error message + HTTP status.
 */
async function djangoJson(pathname, { method = 'GET', body, token, query } = {}) {
  const url = new URL(`${DJANGO_BASE_URL}${pathname.startsWith('/') ? pathname : `/${pathname}`}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, value);
    }
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), DJANGO_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: {
        ...(body ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (error) {
    clearTimeout(timer);
    const reason = error.name === 'AbortError'
      ? 'The Django backend did not respond in time.'
      : 'The Django backend is not reachable. Start it with: .\\.venv\\Scripts\\python.exe django_backend\\manage.py runserver';
    throw new DjangoError(reason, 503);
  }
  clearTimeout(timer);

  const text = await response.text();
  let payload = null;
  if (text) {
    try { payload = JSON.parse(text); } catch { payload = text; }
  }
  if (!response.ok) {
    const message = (payload && typeof payload === 'object' && payload.error)
      || (typeof payload === 'string' && payload)
      || `Django request failed (${response.status}).`;
    throw new DjangoError(String(message), response.status, payload);
  }
  return payload;
}

/**
 * Call a Django API path and return the raw Response (for file downloads such
 * as JSON/CSV/PDF backups) so the Node layer can stream bytes through.
 */
async function djangoRaw(pathname, { method = 'GET', token, query } = {}) {
  const url = new URL(`${DJANGO_BASE_URL}${pathname.startsWith('/') ? pathname : `/${pathname}`}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, value);
    }
  }
  try {
    return await fetch(url, {
      method,
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      redirect: 'manual',
    });
  } catch {
    throw new DjangoError(
      'The Django backend is not reachable. Start it with: .\\.venv\\Scripts\\python.exe django_backend\\manage.py runserver',
      503,
    );
  }
}

/** Quick readiness probe used by /api/health. */
async function djangoHealth() {
  try {
    const payload = await djangoJson('/api/health');
    return { reachable: true, payload };
  } catch (error) {
    return { reachable: false, error: error.message };
  }
}

module.exports = { djangoJson, djangoRaw, djangoHealth, DjangoError, DJANGO_BASE_URL };
