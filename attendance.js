const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const DATA_DIR = path.join(__dirname, 'data');
const FILES = {
  employees: path.join(DATA_DIR, 'attendance-employees.json'),
  attendance: path.join(DATA_DIR, 'attendance-records.json'),
  sites: path.join(DATA_DIR, 'attendance-sites.json'),
  corrections: path.join(DATA_DIR, 'attendance-corrections.json'),
  backups: path.join(DATA_DIR, 'attendance-backups.json'),
};
const DEFAULT_TIME_ZONE = process.env.ATTENDANCE_TIME_ZONE || 'Asia/Kolkata';
let writeQueue = Promise.resolve();

function json(res, status, value, extraHeaders = {}) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...extraHeaders });
  res.end(JSON.stringify(value));
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let raw = '';
    req.on('data', (chunk) => {
      raw += chunk;
      if (raw.length > 128 * 1024) {
        reject(new Error('Request is too large.'));
        req.destroy();
      }
    });
    req.on('end', () => {
      try { resolve(JSON.parse(raw || '{}')); } catch { reject(new Error('Request body must be valid JSON.')); }
    });
    req.on('error', reject);
  });
}

async function ensureFiles() {
  await fs.promises.mkdir(DATA_DIR, { recursive: true });
  for (const file of Object.values(FILES)) {
    try { await fs.promises.access(file); } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      await fs.promises.writeFile(file, '[]\n', { flag: 'wx' }).catch((writeError) => {
        if (writeError.code !== 'EEXIST') throw writeError;
      });
    }
  }
}

async function read(file) {
  const value = JSON.parse(await fs.promises.readFile(file, 'utf8'));
  if (!Array.isArray(value)) throw new Error(`Stored data is invalid: ${path.basename(file)} must contain a JSON array.`);
  return value;
}

async function write(file, value) {
  const temporary = `${file}.${process.pid}.${crypto.randomBytes(6).toString('hex')}.tmp`;
  try {
    await fs.promises.writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' });
    await fs.promises.rename(temporary, file);
  } catch (error) {
    await fs.promises.unlink(temporary).catch(() => {});
    throw error;
  }
}

function serialized(operation) {
  const result = writeQueue.then(operation);
  writeQueue = result.catch(() => {});
  return result;
}

function getSession(req, sessions) {
  const token = (req.headers.authorization || '').replace(/^Bearer\s+/i, '');
  const session = sessions.get(token);
  if (!session) return null;
  if (session.expiresAt < Date.now()) {
    sessions.delete(token);
    return null;
  }
  return session;
}

function requireRole(req, res, sessions, role) {
  const session = getSession(req, sessions);
  if (!session) {
    json(res, 401, { error: 'Your session has expired. Please log in again.' });
    return null;
  }
  if (session.role !== role) {
    json(res, 403, { error: 'You are not authorized to access this attendance data.' });
    return null;
  }
  return session;
}

function validDate(value) {
  return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && !Number.isNaN(Date.parse(`${value}T00:00:00Z`))
    && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
}

function localDate(timestamp = Date.now()) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: DEFAULT_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date(timestamp));
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function safeEmployee(employee) {
  return {
    id: employee.id, username: employee.username, name: employee.name,
    siteId: employee.siteId || '', active: employee.active !== false,
    createdAt: employee.createdAt,
  };
}

function validLocation(location) {
  return location && Number.isFinite(location.latitude) && location.latitude >= -90 && location.latitude <= 90
    && Number.isFinite(location.longitude) && location.longitude >= -180 && location.longitude <= 180
    && Number.isFinite(location.accuracy) && location.accuracy >= 0 && location.accuracy <= 100000;
}

function publicLocation(input) {
  return {
    latitude: input.latitude, longitude: input.longitude, accuracy: input.accuracy,
    address: typeof input.address === 'string' ? input.address.slice(0, 250) : null,
  };
}

function durationMinutes(record) {
  if (!record.checkIn || !record.checkOut) return null;
  return Math.max(0, Math.round((Date.parse(record.checkOut.timestamp) - Date.parse(record.checkIn.timestamp)) / 60000));
}

function filteredRecords(records, query) {
  const from = query.get('from') || query.get('date') || '';
  const to = query.get('to') || query.get('date') || '';
  const employeeId = query.get('employeeId') || '';
  const month = query.get('month') || '';
  if (from && !validDate(from) || to && !validDate(to) || month && !/^\d{4}-\d{2}$/.test(month)) {
    throw new Error('Use valid date filters in YYYY-MM-DD format.');
  }
  return records.filter((record) => (!from || record.date >= from)
    && (!to || record.date <= to)
    && (!employeeId || record.employeeId === employeeId)
    && (!month || record.date.startsWith(month)));
}

function csvCell(value) {
  const text = String(value ?? '');
  return `"${text.replace(/"/g, '""')}"`;
}

function makeCsv(records, sites) {
  const siteNames = new Map(sites.map((site) => [site.id, site.name]));
  const rows = [[
    'Date', 'Employee', 'Username', 'Site', 'Status', 'Check-in time', 'Check-in latitude',
    'Check-in longitude', 'Check-in accuracy (m)', 'Check-in address', 'Check-out time',
    'Check-out latitude', 'Check-out longitude', 'Check-out accuracy (m)', 'Check-out address',
    'Working hours', 'Overtime hours',
  ]];
  for (const item of records) {
    const minutes = durationMinutes(item);
    rows.push([
      item.date, item.employeeName, item.username, siteNames.get(item.siteId) || item.siteName || '',
      item.status, item.checkIn?.timestamp || '', item.checkIn?.latitude ?? '', item.checkIn?.longitude ?? '',
      item.checkIn?.accuracy ?? '', item.checkIn?.address || '', item.checkOut?.timestamp || '',
      item.checkOut?.latitude ?? '', item.checkOut?.longitude ?? '', item.checkOut?.accuracy ?? '',
      item.checkOut?.address || '', minutes === null ? '' : (minutes / 60).toFixed(2),
      minutes === null ? '' : (Math.max(0, minutes - 480) / 60).toFixed(2),
    ]);
  }
  return `\uFEFF${rows.map((row) => row.map(csvCell).join(',')).join('\r\n')}\r\n`;
}

function makePdf(lines) {
  const safeLines = lines.map((line) => String(line).replace(/[^\x20-\x7E]/g, '?').replace(/[()\\]/g, '\\$&'));
  const pages = [];
  for (let i = 0; i < safeLines.length || i === 0; i += 45) pages.push(safeLines.slice(i, i + 45));
  const objects = [];
  const pageIds = pages.map((_, index) => 4 + index * 2);
  objects[1] = '<< /Type /Catalog /Pages 2 0 R >>';
  objects[2] = `<< /Type /Pages /Kids [${pageIds.map((id) => `${id} 0 R`).join(' ')}] /Count ${pages.length} >>`;
  objects[3] = '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>';
  pages.forEach((page, index) => {
    const pageId = pageIds[index], streamId = pageId + 1;
    const content = `BT /F1 9 Tf 42 800 Td 13 TL ${page.map((line) => `(${line}) Tj T*`).join(' ')} ET`;
    objects[pageId] = `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Resources << /Font << /F1 3 0 R >> >> /Contents ${streamId} 0 R >>`;
    objects[streamId] = `<< /Length ${Buffer.byteLength(content, 'ascii')} >>\nstream\n${content}\nendstream`;
  });
  let output = '%PDF-1.4\n';
  const offsets = [0];
  for (let i = 1; i < objects.length; i += 1) {
    offsets[i] = Buffer.byteLength(output, 'ascii');
    output += `${i} 0 obj\n${objects[i]}\nendobj\n`;
  }
  const xrefOffset = Buffer.byteLength(output, 'ascii');
  output += `xref\n0 ${objects.length}\n0000000000 65535 f \n`;
  for (let i = 1; i < objects.length; i += 1) output += `${String(offsets[i]).padStart(10, '0')} 00000 n \n`;
  output += `trailer\n<< /Size ${objects.length} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`;
  return Buffer.from(output, 'ascii');
}

function filenameDate(value) { return value || localDate(); }

async function handle(req, res, url, sessions) {
  if (!url.pathname.startsWith('/api/attendance/')) return false;
  try {
    await ensureFiles();
    const { pathname, searchParams: query } = url;

    if (pathname === '/api/attendance/employee/login' && req.method === 'POST') {
      const body = await readBody(req);
      const username = String(body.username || '').trim().toLowerCase();
      const password = String(body.password || '');
      const employees = await read(FILES.employees);
      const employee = employees.find((item) => item.username === username && item.active !== false);
      if (!employee || password.length > 256 || !/^[a-f0-9]{128}$/.test(employee.passwordHash || '') || !/^[a-f0-9]{32}$/.test(employee.passwordSalt || '')) {
        return json(res, 401, { error: 'Invalid username or password.' }), true;
      }
      const supplied = crypto.scryptSync(password, employee.passwordSalt, 64).toString('hex');
      if (!crypto.timingSafeEqual(Buffer.from(supplied, 'hex'), Buffer.from(employee.passwordHash, 'hex'))) {
        return json(res, 401, { error: 'Invalid username or password.' }), true;
      }
      const token = crypto.randomBytes(32).toString('hex');
      sessions.set(token, { role: 'employee', employeeId: employee.id, expiresAt: Date.now() + 12 * 60 * 60 * 1000 });
      return json(res, 200, { token, employee: safeEmployee(employee) }), true;
    }

    if (pathname === '/api/attendance/employee/logout' && req.method === 'POST') {
      const token = (req.headers.authorization || '').replace(/^Bearer\s+/i, '');
      sessions.delete(token);
      return json(res, 200, { ok: true }), true;
    }

    if (pathname === '/api/attendance/me' && req.method === 'GET') {
      const session = requireRole(req, res, sessions, 'employee');
      if (!session) return true;
      const [employees, records, sites] = await Promise.all([read(FILES.employees), read(FILES.attendance), read(FILES.sites)]);
      const employee = employees.find((item) => item.id === session.employeeId && item.active !== false);
      if (!employee) return json(res, 401, { error: 'This employee account is no longer active.' }), true;
      const ownRecords = records.filter((record) => record.employeeId === employee.id)
        .sort((a, b) => b.date.localeCompare(a.date));
      return json(res, 200, {
        employee: safeEmployee(employee), site: sites.find((site) => site.id === employee.siteId) || null,
        today: ownRecords.find((record) => record.date === localDate()) || null,
        records: ownRecords.slice(0, 60),
      }), true;
    }

    if (pathname === '/api/attendance/check-in' && req.method === 'POST') {
      const session = requireRole(req, res, sessions, 'employee');
      if (!session) return true;
      const body = await readBody(req);
      if (!validLocation(body.location)) return json(res, 400, { error: 'A valid GPS location and accuracy are required to check in.' }), true;
      const result = await serialized(async () => {
        const [employees, records] = await Promise.all([read(FILES.employees), read(FILES.attendance)]);
        const employee = employees.find((item) => item.id === session.employeeId && item.active !== false);
        if (!employee) return { status: 401, body: { error: 'This employee account is no longer active.' } };
        const date = localDate();
        if (records.some((record) => record.employeeId === employee.id && record.date === date)) {
          return { status: 409, body: { error: 'An attendance entry already exists for today.' } };
        }
        const record = {
          id: crypto.randomUUID(), employeeId: employee.id, employeeName: employee.name, username: employee.username,
          siteId: employee.siteId || '', date, status: 'Present', checkIn: {
            ...publicLocation(body.location), timestamp: new Date().toISOString(),
          }, checkOut: null, source: 'gps',
        };
        records.push(record);
        await write(FILES.attendance, records);
        return { status: 201, body: { ok: true, record } };
      });
      return json(res, result.status, result.body), true;
    }

    if (pathname === '/api/attendance/check-out' && req.method === 'POST') {
      const session = requireRole(req, res, sessions, 'employee');
      if (!session) return true;
      const body = await readBody(req);
      if (!validLocation(body.location)) return json(res, 400, { error: 'A valid GPS location and accuracy are required to check out.' }), true;
      const result = await serialized(async () => {
        const records = await read(FILES.attendance);
        const record = records.find((item) => item.employeeId === session.employeeId && item.date === localDate());
        if (!record || !record.checkIn) return { status: 409, body: { error: 'You must check in before checking out.' } };
        if (record.checkOut) return { status: 409, body: { error: 'You have already checked out today.' } };
        const checkedOutAt = new Date().toISOString();
        record.checkOut = { ...publicLocation(body.location), timestamp: checkedOutAt };
        await write(FILES.attendance, records);
        return { status: 200, body: { ok: true, record, workingMinutes: durationMinutes(record) } };
      });
      return json(res, result.status, result.body), true;
    }

    if (pathname === '/api/attendance/corrections' && req.method === 'POST') {
      const session = requireRole(req, res, sessions, 'employee');
      if (!session) return true;
      const body = await readBody(req);
      const correctionDate = String(body.date || '');
      const checkIn = body.checkIn ? Date.parse(body.checkIn) : null;
      const checkOut = body.checkOut ? Date.parse(body.checkOut) : null;
      if (!validDate(correctionDate) || (!Number.isFinite(checkIn) && !Number.isFinite(checkOut))
        || (Number.isFinite(checkIn) && localDate(checkIn) !== correctionDate)
        || (Number.isFinite(checkOut) && localDate(checkOut) !== correctionDate)
        || (Number.isFinite(checkIn) && Number.isFinite(checkOut) && checkOut < checkIn)) {
        return json(res, 400, { error: 'Provide a valid date and at least one valid requested time for that date.' }), true;
      }
      const employees = await read(FILES.employees);
      const employee = employees.find((item) => item.id === session.employeeId);
      const note = String(body.note || '').trim().slice(0, 1000);
      if (!note) return json(res, 400, { error: 'Please explain the correction request.' }), true;
      const request = {
        id: crypto.randomUUID(), employeeId: employee.id, employeeName: employee.name,
        date: correctionDate, requestedCheckIn: Number.isFinite(checkIn) ? new Date(checkIn).toISOString() : null,
        requestedCheckOut: Number.isFinite(checkOut) ? new Date(checkOut).toISOString() : null,
        note, status: 'Pending', submittedAt: new Date().toISOString(),
      };
      await serialized(async () => write(FILES.corrections, [...await read(FILES.corrections), request]));
      return json(res, 201, { ok: true, request }), true;
    }

    if (pathname.startsWith('/api/attendance/admin/')) {
      const session = requireRole(req, res, sessions, 'admin');
      if (!session) return true;
    } else {
      const employeeOnly = pathname.startsWith('/api/attendance/');
      if (employeeOnly && ![
        '/api/attendance/employee/login', '/api/attendance/employee/logout', '/api/attendance/me',
        '/api/attendance/check-in', '/api/attendance/check-out', '/api/attendance/corrections',
      ].includes(pathname)) return json(res, 404, { error: 'Attendance API route not found.' }), true;
      return json(res, 405, { error: 'Method not allowed.' }), true;
    }

    if (pathname === '/api/attendance/admin/dashboard' && req.method === 'GET') {
      const [employees, corrections, sites] = await Promise.all([
        read(FILES.employees), read(FILES.corrections), read(FILES.sites),
      ]);
      const date = query.get('date') || localDate();
      if (!validDate(date)) return json(res, 400, { error: 'Use a valid date filter in YYYY-MM-DD format.' }), true;
      const allRecords = await read(FILES.attendance);
      const todays = filteredRecords(allRecords, new URLSearchParams({ date }));
      const activeEmployees = employees.filter((employee) => employee.active !== false);
      const present = todays.filter((record) => record.status === 'Present');
      const onLeave = todays.filter((record) => record.status === 'Leave');
      const currentRecords = filteredRecords(allRecords, new URLSearchParams({ from: query.get('from') || '', to: query.get('to') || '', employeeId: query.get('employeeId') || '', month: query.get('month') || '' }));
      const lastBackup = (await read(FILES.backups)).sort((a, b) => b.createdAt.localeCompare(a.createdAt))[0] || null;
      return json(res, 200, {
        employees: activeEmployees.map(safeEmployee), sites, records: currentRecords,
        today: todays, corrections: corrections.filter((item) => item.status === 'Pending'),
        counts: {
          employees: activeEmployees.length, present: present.length, leave: onLeave.length,
          absent: Math.max(0, activeEmployees.length - present.length - onLeave.length),
          checkedIn: present.filter((record) => record.checkIn && !record.checkOut).length,
        },
        lastBackup, date,
      }), true;
    }

    if (pathname === '/api/attendance/admin/employees' && req.method === 'POST') {
      const body = await readBody(req);
      const name = String(body.name || '').trim().slice(0, 100);
      const username = String(body.username || '').trim().toLowerCase();
      const password = String(body.password || '');
      if (name.length < 2 || !/^[a-z0-9._-]{3,40}$/.test(username) || password.length < 12 || password.length > 256) {
        return json(res, 400, { error: 'Enter a name, a username (3–40 letters, numbers, dots, underscores or hyphens), and a password of at least 12 characters.' }), true;
      }
      const result = await serialized(async () => {
        const employees = await read(FILES.employees);
        if (employees.some((item) => item.username === username)) return { status: 409, body: { error: 'That username is already in use.' } };
        const sites = await read(FILES.sites);
        const siteId = String(body.siteId || '');
        if (siteId && !sites.some((site) => site.id === siteId)) return { status: 400, body: { error: 'Select a valid client/site.' } };
        const passwordSalt = crypto.randomBytes(16).toString('hex');
        const employee = {
          id: crypto.randomUUID(), username, name, passwordSalt,
          passwordHash: crypto.scryptSync(password, passwordSalt, 64).toString('hex'),
          siteId, active: true, createdAt: new Date().toISOString(),
        };
        employees.push(employee);
        await write(FILES.employees, employees);
        return { status: 201, body: { ok: true, employee: safeEmployee(employee) } };
      });
      return json(res, result.status, result.body), true;
    }

    if (pathname === '/api/attendance/admin/sites' && req.method === 'POST') {
      const body = await readBody(req);
      const name = String(body.name || '').trim().slice(0, 120);
      const client = String(body.client || '').trim().slice(0, 120);
      if (name.length < 2 || !client) return json(res, 400, { error: 'Client and site names are required.' }), true;
      const result = await serialized(async () => {
        const sites = await read(FILES.sites);
        const site = { id: crypto.randomUUID(), name, client, address: String(body.address || '').trim().slice(0, 250), createdAt: new Date().toISOString() };
        sites.push(site);
        await write(FILES.sites, sites);
        return site;
      });
      return json(res, 201, { ok: true, site: result }), true;
    }

    if (pathname === '/api/attendance/admin/leave' && req.method === 'POST') {
      const body = await readBody(req);
      if (!validDate(body.date) || typeof body.employeeId !== 'string') return json(res, 400, { error: 'Choose an employee and valid leave date.' }), true;
      const result = await serialized(async () => {
        const employees = await read(FILES.employees);
        const employee = employees.find((item) => item.id === body.employeeId && item.active !== false);
        if (!employee) return { status: 404, body: { error: 'Employee not found.' } };
        const records = await read(FILES.attendance);
        let record = records.find((item) => item.employeeId === employee.id && item.date === body.date);
        if (record && record.checkIn) return { status: 409, body: { error: 'An employee who has checked in cannot be marked on leave.' } };
        if (!record) {
          record = { id: crypto.randomUUID(), employeeId: employee.id, employeeName: employee.name, username: employee.username, siteId: employee.siteId || '', date: body.date, checkIn: null, checkOut: null };
          records.push(record);
        }
        record.status = 'Leave';
        record.leaveNote = String(body.note || '').trim().slice(0, 300);
        await write(FILES.attendance, records);
        return { status: 200, body: { ok: true, record } };
      });
      return json(res, result.status, result.body), true;
    }

    const correctionMatch = pathname.match(/^\/api\/attendance\/admin\/corrections\/([^/]+)$/);
    if (correctionMatch && req.method === 'POST') {
      const body = await readBody(req);
      if (!['approve', 'reject'].includes(body.decision)) return json(res, 400, { error: 'Choose approve or reject.' }), true;
      const result = await serialized(async () => {
        const corrections = await read(FILES.corrections);
        const correction = corrections.find((item) => item.id === correctionMatch[1]);
        if (!correction) return { status: 404, body: { error: 'Correction request not found.' } };
        if (correction.status !== 'Pending') return { status: 409, body: { error: 'This correction request has already been reviewed.' } };
        if (body.decision === 'approve') {
          const records = await read(FILES.attendance);
          let record = records.find((item) => item.employeeId === correction.employeeId && item.date === correction.date);
          if (!record) {
            record = { id: crypto.randomUUID(), employeeId: correction.employeeId, employeeName: correction.employeeName, date: correction.date, status: 'Present', checkIn: null, checkOut: null, source: 'admin-correction' };
            records.push(record);
          }
          const proposedIn = correction.requestedCheckIn || record.checkIn?.timestamp;
          const proposedOut = correction.requestedCheckOut || record.checkOut?.timestamp;
          if (proposedIn && proposedOut && Date.parse(proposedOut) < Date.parse(proposedIn)) {
            return { status: 409, body: { error: 'The requested checkout is before check-in; reject this request or correct the submitted times.' } };
          }
          if (correction.requestedCheckIn) record.checkIn = { ...(record.checkIn || {}), timestamp: correction.requestedCheckIn, correctionApproved: true };
          if (correction.requestedCheckOut) record.checkOut = { ...(record.checkOut || {}), timestamp: correction.requestedCheckOut, correctionApproved: true };
          record.status = 'Present';
          await write(FILES.attendance, records);
          correction.status = 'Approved';
        } else correction.status = 'Rejected';
        correction.reviewedAt = new Date().toISOString();
        correction.reviewNote = String(body.note || '').trim().slice(0, 500);
        await write(FILES.corrections, corrections);
        return { status: 200, body: { ok: true, correction } };
      });
      return json(res, result.status, result.body), true;
    }

    if (pathname === '/api/attendance/admin/backup' && req.method === 'GET') {
      const from = query.get('from'), to = query.get('to'), format = query.get('format') || 'json';
      if (!validDate(from) || !validDate(to) || from > to || !['json', 'csv', 'pdf'].includes(format)) {
        return json(res, 400, { error: 'Select a valid date range and JSON, CSV or PDF format.' }), true;
      }
      const [employees, allRecords, sites, corrections, backups] = await Promise.all([
        read(FILES.employees), read(FILES.attendance), read(FILES.sites), read(FILES.corrections), read(FILES.backups),
      ]);
      const records = filteredRecords(allRecords, new URLSearchParams({ from, to }));
      const range = `${from}_to_${to}`;
      const filename = `attendance_${range}.${format}`;
      let payload, type;
      if (format === 'csv') {
        payload = Buffer.from(makeCsv(records, sites), 'utf8');
        type = 'text/csv; charset=utf-8';
      } else if (format === 'pdf') {
        const siteNames = new Map(sites.map((site) => [site.id, site.name]));
        const lines = [`Ecronx Technologies - Attendance report`, `Date range: ${from} to ${to}`, `Records: ${records.length}`, ''];
        for (const record of records) {
          const minutes = durationMinutes(record);
          lines.push(`${record.date} | ${record.employeeName} (${record.username}) | ${record.status} | Site: ${siteNames.get(record.siteId) || '-'}`);
          lines.push(`  In: ${record.checkIn?.timestamp || '-'} @ ${record.checkIn ? `${record.checkIn.latitude}, ${record.checkIn.longitude} +/-${record.checkIn.accuracy}m` : '-'}`);
          lines.push(`  Out: ${record.checkOut?.timestamp || '-'} @ ${record.checkOut ? `${record.checkOut.latitude}, ${record.checkOut.longitude} +/-${record.checkOut.accuracy}m` : '-'} | Hours: ${minutes === null ? '-' : (minutes / 60).toFixed(2)}`);
        }
        payload = makePdf(lines);
        type = 'application/pdf';
      } else {
        payload = Buffer.from(`${JSON.stringify({
          formatVersion: 1, createdAt: new Date().toISOString(), dateRange: { from, to },
          employees, attendance: records, sites,
          correctionRequests: corrections.filter((item) => item.date >= from && item.date <= to),
        }, null, 2)}\n`, 'utf8');
        type = 'application/json; charset=utf-8';
      }
      await serialized(async () => write(FILES.backups, [...backups, { createdAt: new Date().toISOString(), from, to, format }]));
      res.writeHead(200, {
        'Content-Type': type, 'Content-Disposition': `attachment; filename="${filename}"`,
        'Content-Length': payload.length, 'Cache-Control': 'no-store',
      });
      res.end(payload);
      return true;
    }

    if (pathname.startsWith('/api/attendance/admin/') && req.method === 'GET') {
      return json(res, 404, { error: 'Attendance admin API route not found.' }), true;
    }
    return json(res, 405, { error: 'Method not allowed.' }), true;
  } catch (error) {
    console.error('Attendance API error:', error);
    if (!res.headersSent) json(res, 500, { error: 'Attendance request could not be completed. Check server data files and try again.' });
    return true;
  }
}

module.exports = { handle };
