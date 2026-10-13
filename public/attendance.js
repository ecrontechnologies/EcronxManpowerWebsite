const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
let token = '';
let accessRole = '';
let adminData = null;

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));

function setStatus(selector, message, type = '') {
  const element = $(selector);
  element.textContent = message;
  element.className = `portal-status${type ? ` ${type}` : ''}${element.classList.contains('wide-label') ? ' wide-label' : ''}`;
}

async function api(url, options = {}) {
  const headers = {
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };
  const response = await fetch(url, { ...options, headers, cache: 'no-store' });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || 'Request failed. Please try again.');
  return data;
}

function currentDate() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date());
  const map = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${map.year}-${map.month}-${map.day}`;
}

function dateOffset(date, days) {
  const [year, month, day] = date.split('-').map(Number);
  return new Date(Date.UTC(year, month - 1, day + days, 12)).toISOString().slice(0, 10);
}

function formatTime(value) {
  return value ? new Intl.DateTimeFormat(undefined, {
    dateStyle: 'medium', timeStyle: 'short',
  }).format(new Date(value)) : '—';
}

function formatHours(record, ongoing = false) {
  if (!record?.checkIn) return '—';
  const end = record.checkOut ? Date.parse(record.checkOut.timestamp) : (ongoing ? Date.now() : null);
  if (end === null) return 'In progress';
  const mins = Math.max(0, Math.round((end - Date.parse(record.checkIn.timestamp)) / 60000));
  return `${Math.floor(mins / 60)}h ${mins % 60}m`;
}

function mapLink(location) {
  if (!location || !Number.isFinite(location.latitude) || !Number.isFinite(location.longitude)) return '';
  const target = `https://www.google.com/maps?q=${encodeURIComponent(`${location.latitude},${location.longitude}`)}`;
  return `<a class="map-link" href="${target}" target="_blank" rel="noopener noreferrer">View map ↗</a>`;
}

function showPortal(role) {
  accessRole = role;
  $('#loginCard').classList.add('hidden');
  $('#employeeDashboard').classList.toggle('hidden', role !== 'employee');
  $('#adminDashboard').classList.toggle('hidden', role !== 'admin');
  $('#portalLogout').classList.remove('hidden');
}

$$('.login-tab').forEach((tab) => tab.addEventListener('click', () => {
  $$('.login-tab').forEach((item) => {
    const active = item === tab;
    item.classList.toggle('active', active);
    item.setAttribute('aria-selected', String(active));
  });
  const employee = tab.dataset.login === 'employee';
  $('#employeeLoginForm').classList.toggle('hidden', !employee);
  $('#adminLoginForm').classList.toggle('hidden', employee);
}));

$('#employeeLoginForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  setStatus('#employeeLoginStatus', 'Signing in…');
  try {
    const result = await api('/api/attendance/employee/login', {
      method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form).entries())),
    });
    token = result.token;
    form.reset();
    await loadEmployeeDashboard();
    showPortal('employee');
  } catch (error) { setStatus('#employeeLoginStatus', error.message, 'error'); }
});

$('#adminLoginForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  setStatus('#adminLoginStatus', 'Verifying administrator access…');
  try {
    const result = await api('/api/admin/login', {
      method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form).entries())),
    });
    token = result.token;
    form.reset();
    setAdminDefaults();
    await loadAdminDashboard();
    showPortal('admin');
  } catch (error) { setStatus('#adminLoginStatus', error.message, 'error'); }
});

function setAdminDefaults() {
  const today = currentDate();
  const filter = $('#filterForm');
  filter.elements.date.value = today;
  filter.elements.from.value = dateOffset(today, -6);
  filter.elements.to.value = today;
  filter.elements.month.value = '';
  filter.elements.employeeId.value = '';
  $('#leaveForm').elements.date.value = today;
}

async function loadEmployeeDashboard() {
  const data = await api('/api/attendance/me');
  $('#employeeName').textContent = data.employee.name;
  $('#employeeSite').textContent = data.site ? `${data.site.client} · ${data.site.name}${data.site.address ? ` · ${data.site.address}` : ''}` : 'No client or site assigned';
  $('#todayDate').textContent = new Intl.DateTimeFormat(undefined, { dateStyle: 'full', timeZone: 'Asia/Kolkata' }).format(new Date());
  const record = data.today;
  $('#attendancePill').textContent = record?.status === 'Leave' ? 'On leave' : record?.checkOut ? 'Completed' : record?.checkIn ? 'Checked in' : 'Not checked in';
  $('#attendancePill').className = `status-pill${record?.status === 'Leave' ? ' leave' : record?.checkIn ? ' present' : ''}`;
  $('#todayCheckIn').textContent = formatTime(record?.checkIn?.timestamp);
  $('#todayCheckOut').textContent = formatTime(record?.checkOut?.timestamp);
  $('#todayHours').textContent = formatHours(record, true);
  $('#checkInButton').disabled = Boolean(record);
  $('#checkOutButton').disabled = !record?.checkIn || Boolean(record.checkOut);
  $('#employeeRecords').innerHTML = data.records.length ? data.records.map((item) => `
    <tr><td>${esc(item.date)}</td><td class="record-status${item.status === 'Leave' ? ' leave' : ''}">${esc(item.status || 'Present')}</td>
    <td>${esc(formatTime(item.checkIn?.timestamp))}</td><td>${esc(formatTime(item.checkOut?.timestamp))}</td><td>${esc(formatHours(item))}</td></tr>`).join('')
    : '<tr><td colspan="5">No attendance records have been recorded yet.</td></tr>';
}

function locateOnce() {
  return new Promise((resolve, reject) => {
    if (!window.isSecureContext) {
      reject(new Error('Location access requires HTTPS or http://localhost. Open this site securely and retry.'));
      return;
    }
    if (!navigator.geolocation) {
      reject(new Error('This browser does not support location. Use a current browser and retry.'));
      return;
    }
    navigator.geolocation.getCurrentPosition((position) => resolve({
      latitude: position.coords.latitude,
      longitude: position.coords.longitude,
      accuracy: position.coords.accuracy,
      address: null,
    }), (error) => {
      const messages = {
        1: 'Location permission was denied. Allow location access in your browser settings, then retry.',
        2: 'Your location could not be determined. Check GPS/network availability and retry.',
        3: 'Location request timed out. Move to a place with a clearer GPS signal and retry.',
      };
      reject(new Error(messages[error.code] || 'Location could not be obtained. Please retry.'));
    }, { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 });
  });
}

async function submitGpsAction(button, endpoint, action) {
  button.disabled = true;
  const otherButton = action === 'check in' ? $('#checkOutButton') : $('#checkInButton');
  otherButton.disabled = true;
  setStatus('#gpsStatus', `Requesting a one-time GPS location for ${action}…`);
  try {
    const location = await locateOnce();
    const result = await api(endpoint, { method: 'POST', body: JSON.stringify({ location }) });
    setStatus('#gpsStatus', `${action === 'check in' ? 'Check-in' : 'Check-out'} saved at ${formatTime(result.record[action === 'check in' ? 'checkIn' : 'checkOut'].timestamp)}. GPS accuracy: ±${Math.round(location.accuracy)} m.`, 'success');
    await loadEmployeeDashboard();
  } catch (error) {
    setStatus('#gpsStatus', error.message, 'error');
    button.disabled = false;
  }
}

$('#checkInButton').addEventListener('click', (event) => submitGpsAction(event.currentTarget, '/api/attendance/check-in', 'check in'));
$('#checkOutButton').addEventListener('click', (event) => submitGpsAction(event.currentTarget, '/api/attendance/check-out', 'check out'));

$('#correctionForm').elements.date.value = currentDate();
$('#correctionForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form).entries());
  const body = {
    date: values.date, note: values.note,
    ...(values.checkIn ? { checkIn: new Date(values.checkIn).toISOString() } : {}),
    ...(values.checkOut ? { checkOut: new Date(values.checkOut).toISOString() } : {}),
  };
  setStatus('#correctionStatus', 'Submitting your request…');
  try {
    await api('/api/attendance/corrections', { method: 'POST', body: JSON.stringify(body) });
    form.reset();
    form.elements.date.value = currentDate();
    setStatus('#correctionStatus', 'Your correction request was submitted for administrator approval.', 'success');
  } catch (error) { setStatus('#correctionStatus', error.message, 'error'); }
});

function buildDashboardUrl() {
  const values = Object.fromEntries(new FormData($('#filterForm')).entries());
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value) params.set(key, value);
  return `/api/attendance/admin/dashboard?${params}`;
}

function renderLocation(location, fallback) {
  if (!location) return `<div class="time-location">${esc(fallback || '—')}</div>`;
  if (!Number.isFinite(location.latitude) || !Number.isFinite(location.longitude)) {
    return `<div class="time-location">${esc(formatTime(location.timestamp))}<small>Time correction approved; no GPS fix was recorded.</small></div>`;
  }
  const accuracy = Number.isFinite(location.accuracy) ? `±${Math.round(location.accuracy)} m` : '';
  return `<div class="time-location">${esc(formatTime(location.timestamp))}<small>${esc(location.latitude)}, ${esc(location.longitude)} · ${esc(accuracy)}</small>${location.address ? `<small>${esc(location.address)}</small>` : ''}${mapLink(location)}</div>`;
}

function renderAdminRecords(records, sites) {
  const siteMap = new Map(sites.map((site) => [site.id, site]));
  $('#adminRecords').innerHTML = records.length ? records.map((record) => {
    const minutes = record.checkIn && record.checkOut
      ? Math.max(0, Math.round((Date.parse(record.checkOut.timestamp) - Date.parse(record.checkIn.timestamp)) / 60000))
      : null;
    const site = siteMap.get(record.siteId);
    return `<tr><td>${esc(record.date)}<small>${esc(record.employeeName)} · ${esc(record.username)}</small></td>
      <td class="record-status${record.status === 'Leave' ? ' leave' : ''}">${esc(record.status || 'Present')}<small>${esc(site ? `${site.client} · ${site.name}` : record.siteName || 'No site assigned')}</small></td>
      <td>${renderLocation(record.checkIn, '—')}</td><td>${renderLocation(record.checkOut, '—')}</td>
      <td>${minutes === null ? (record.checkIn ? 'In progress' : '—') : `${(minutes / 60).toFixed(2)} h`}<small>${minutes === null ? '' : `${(Math.max(0, minutes - 480) / 60).toFixed(2)} h overtime`}</small></td></tr>`;
  }).join('') : '<tr><td colspan="5">No attendance records match these filters.</td></tr>';
}

function renderAdminLists(data) {
  const selectedEmployee = $('#filterForm').elements.employeeId.value;
  const employeeOptions = '<option value="">All employees</option>' + data.employees
    .map((employee) => `<option value="${esc(employee.id)}">${esc(employee.name)} (${esc(employee.username)})</option>`).join('');
  $('#filterForm').elements.employeeId.innerHTML = employeeOptions;
  if (data.employees.some((employee) => employee.id === selectedEmployee)) {
    $('#filterForm').elements.employeeId.value = selectedEmployee;
  }
  $('#leaveForm').elements.employeeId.innerHTML = '<option value="">Choose employee</option>' + data.employees
    .map((employee) => `<option value="${esc(employee.id)}">${esc(employee.name)} (${esc(employee.username)})</option>`).join('');
  const siteOptions = '<option value="">No site assigned</option>' + data.sites
    .map((site) => `<option value="${esc(site.id)}">${esc(site.client)} · ${esc(site.name)}</option>`).join('');
  $('#employeeCreateForm').elements.siteId.innerHTML = siteOptions;
  $('#employeeList').innerHTML = data.employees.length ? `<h4>Employee accounts</h4>${data.employees.map((employee) => {
    const site = data.sites.find((item) => item.id === employee.siteId);
    return `<div class="compact-item"><span><b>${esc(employee.name)}</b><small>@${esc(employee.username)}${site ? ` · ${esc(site.client)} / ${esc(site.name)}` : ''}</small></span><span class="record-status">Active</span></div>`;
  }).join('')}` : '<p class="muted">No employee accounts have been created.</p>';
  $('#siteList').innerHTML = data.sites.length ? `<h4>Saved client / sites</h4>${data.sites.map((site) => `<div class="compact-item"><span><b>${esc(site.client)} · ${esc(site.name)}</b><small>${esc(site.address || 'No site address supplied')}</small></span></div>`).join('')}` : '<p class="muted">No client/site details added yet.</p>';
  $('#correctionRequests').innerHTML = data.corrections.length ? data.corrections.map((item) => `
    <div class="compact-item"><span><b>${esc(item.employeeName)} · ${esc(item.date)}</b>
      <small>Requested in: ${esc(formatTime(item.requestedCheckIn))} · out: ${esc(formatTime(item.requestedCheckOut))}</small>
      <small>${esc(item.note)}</small></span>
      <span class="compact-actions"><button class="approve" type="button" data-review="${esc(item.id)}" data-decision="approve">Approve</button><button class="reject" type="button" data-review="${esc(item.id)}" data-decision="reject">Reject</button></span></div>`).join('')
    : '<p class="muted">There are no pending correction requests.</p>';
  $$('[data-review]').forEach((button) => button.addEventListener('click', async () => {
    const decision = button.dataset.decision;
    if (decision === 'reject' && !window.confirm('Reject this attendance correction request?')) return;
    try {
      await api(`/api/attendance/admin/corrections/${encodeURIComponent(button.dataset.review)}`, {
        method: 'POST', body: JSON.stringify({ decision }),
      });
      await loadAdminDashboard();
    } catch (error) { window.alert(error.message); }
  }));
}

async function loadAdminDashboard() {
  adminData = await api(buildDashboardUrl());
  $('#metricEmployees').textContent = adminData.counts.employees;
  $('#metricPresent').textContent = adminData.counts.present;
  $('#metricAbsent').textContent = adminData.counts.absent;
  $('#metricLeave').textContent = adminData.counts.leave;
  $('#metricCheckedIn').textContent = adminData.counts.checkedIn;
  $('#metricPresentLabel').textContent = adminData.date;
  renderAdminLists(adminData);
  renderAdminRecords(adminData.records, adminData.sites);
  const backup = adminData.lastBackup
    ? `Last backup downloaded ${formatTime(adminData.lastBackup.createdAt)} (${adminData.lastBackup.from} to ${adminData.lastBackup.to}).`
    : 'No backup has been downloaded yet. Create a weekly JSON backup and store it somewhere secure.';
  $('#backupReminder').innerHTML = `<span>${esc(backup)}</span><span>Choose dates below, then use Download Weekly Backup.</span>`;
}

$('#filterForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try { await loadAdminDashboard(); } catch (error) { window.alert(error.message); }
});
$('#filterForm').elements.month.addEventListener('change', (event) => {
  const month = event.currentTarget.value;
  if (!month) return;
  const [year, number] = month.split('-').map(Number);
  const end = new Date(Date.UTC(year, number, 0)).toISOString().slice(0, 10);
  $('#filterForm').elements.from.value = `${month}-01`;
  $('#filterForm').elements.to.value = end;
  $('#filterForm').elements.date.value = end < currentDate() ? end : currentDate();
});

$('#employeeCreateForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  setStatus('#employeeCreateStatus', 'Creating employee account…');
  try {
    await api('/api/attendance/admin/employees', {
      method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form).entries())),
    });
    form.reset();
    setStatus('#employeeCreateStatus', 'Employee account created. Share the username and initial password securely with the employee.', 'success');
    await loadAdminDashboard();
  } catch (error) { setStatus('#employeeCreateStatus', error.message, 'error'); }
});

$('#siteCreateForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  setStatus('#siteCreateStatus', 'Saving client/site…');
  try {
    await api('/api/attendance/admin/sites', {
      method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form).entries())),
    });
    form.reset();
    setStatus('#siteCreateStatus', 'Client/site saved.', 'success');
    await loadAdminDashboard();
  } catch (error) { setStatus('#siteCreateStatus', error.message, 'error'); }
});

$('#leaveForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  setStatus('#leaveStatus', 'Saving leave…');
  try {
    await api('/api/attendance/admin/leave', {
      method: 'POST', body: JSON.stringify(Object.fromEntries(new FormData(form).entries())),
    });
    setStatus('#leaveStatus', 'Employee marked on leave.', 'success');
    await loadAdminDashboard();
  } catch (error) { setStatus('#leaveStatus', error.message, 'error'); }
});

async function downloadReport(format) {
  const filters = $('#filterForm').elements;
  const from = filters.from.value || filters.date.value;
  const to = filters.to.value || filters.date.value;
  const query = new URLSearchParams({ from, to, format });
  const response = await fetch(`/api/attendance/admin/backup?${query}`, {
    headers: { Authorization: `Bearer ${token}` }, cache: 'no-store',
  });
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    throw new Error(result.error || 'The report could not be downloaded.');
  }
  const blob = await response.blob();
  const filename = `attendance_${from}_to_${to}.${format}`;
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
  if (format === 'json') await loadAdminDashboard();
}

$$('[data-export]').forEach((button) => button.addEventListener('click', async () => {
  button.disabled = true;
  try { await downloadReport(button.dataset.export); }
  catch (error) { window.alert(error.message); }
  finally { button.disabled = false; }
}));

async function logout() {
  const oldToken = token;
  token = '';
  try {
    if (oldToken) await fetch(accessRole === 'admin' ? '/api/admin/logout' : '/api/attendance/employee/logout', {
      method: 'POST', headers: { Authorization: `Bearer ${oldToken}` }, cache: 'no-store',
    });
  } finally {
    accessRole = '';
    $('#employeeDashboard').classList.add('hidden');
    $('#adminDashboard').classList.add('hidden');
    $('#loginCard').classList.remove('hidden');
    $('#portalLogout').classList.add('hidden');
    $('#employeeLoginForm').reset();
    $('#adminLoginForm').reset();
    setStatus('#employeeLoginStatus', 'You have been securely logged out.', 'success');
  }
}
$('#portalLogout').addEventListener('click', logout);

if (!window.isSecureContext) {
  $('#employeeLoginStatus').textContent = 'GPS attendance requires HTTPS or http://localhost.';
}
