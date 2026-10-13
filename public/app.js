const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
let adminToken = '';
let content = null;
const API_BASE_URL = String(window.APP_CONFIG?.API_BASE_URL || '').replace(/\/+$/, '');
const apiUrl = (url) => `${API_BASE_URL}${url.startsWith('/') ? url : `/${url}`}`;

const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));

function imageSource(value) {
  if (!value) return 'https://images.unsplash.com/photo-1521737711867-e3b97375f902?auto=format&fit=crop&w=900&q=80';
  return value.startsWith('/uploads/') ? apiUrl(value) : value;
}

async function api(url, options = {}) {
  const headers = {
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...(adminToken ? { Authorization: `Bearer ${adminToken}` } : {}),
    ...(options.headers || {}),
  };
  const response = await fetch(apiUrl(url), { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || 'Request failed. Please try again.');
  return data;
}

function renderSite() {
  if (!content) return;
  const settings = content.settings;
  $('#servicesGrid').innerHTML = content.services.length
    ? content.services.map((service, index) => `
      <article class="service-card">
        <img src="${esc(imageSource(service.image))}" alt="${esc(service.name)}" loading="lazy">
        <span class="service-number">${String(index + 1).padStart(2, '0')} / SERVICE</span>
        <h3>${esc(service.name)}</h3>
        <p>${esc(service.description)}</p>
        <a class="learn" href="#enquiry" data-service="${esc(service.name)}">Discuss this service <span aria-hidden="true">↗</span></a>
      </article>`).join('')
    : '<p class="empty-state">Please contact us to discuss your workforce requirements.</p>';
  $('#galleryGrid').innerHTML = content.gallery.length
    ? content.gallery.map((item) => `
      <article class="gallery-item">
        <img src="${esc(imageSource(item.image))}" alt="${esc(item.title)}" loading="lazy">
        <span>${esc(item.title)}<small>${esc(item.category || 'Ecronx')}</small></span>
      </article>`).join('')
    : '<p class="empty-state">Gallery images will be added soon.</p>';
  $('#serviceSelect').innerHTML = '<option value="">Select a service</option>'
    + content.services.map((service) => `<option value="${esc(service.name)}">${esc(service.name)}</option>`).join('')
    + '<option value="Other manpower requirement">Other manpower requirement</option>';

  $('#contactPhone').textContent = settings.phone || '';
  $('#contactPhoneLink').href = `tel:${String(settings.phone || '').replace(/[^\d+]/g, '')}`;
  $('#contactEmail').textContent = settings.email || '';
  $('#contactEmailLink').href = `mailto:${settings.email || ''}`;
  $('#contactAddress').textContent = settings.address || '';
  $('#footerAddress').textContent = settings.address || '';
  $('#footerPhone').textContent = settings.phone || '';
  $('#footerPhone').href = `tel:${String(settings.phone || '').replace(/[^\d+]/g, '')}`;
  $('#footerEmail').textContent = settings.email || '';
  $('#footerEmail').href = `mailto:${settings.email || ''}`;

  $$('[data-service]').forEach((link) => link.addEventListener('click', () => {
    $('#serviceSelect').value = link.dataset.service;
  }));
  observeReveals();
}

async function loadContent() {
  try {
    content = await api('/api/content');
    renderSite();
  } catch (error) {
    console.error('Unable to load website content:', error);
    $('#formStatus').textContent = 'Website content could not be loaded. Please refresh and try again.';
  }
}

const menuToggle = $('#menuToggle');
menuToggle.addEventListener('click', () => {
  const expanded = menuToggle.getAttribute('aria-expanded') === 'true';
  menuToggle.setAttribute('aria-expanded', String(!expanded));
  menuToggle.setAttribute('aria-label', expanded ? 'Open navigation' : 'Close navigation');
  $('#primaryNav').classList.toggle('is-open', !expanded);
  document.body.classList.toggle('menu-open', !expanded);
});
$$('.primary-nav a').forEach((link) => link.addEventListener('click', () => {
  menuToggle.setAttribute('aria-expanded', 'false');
  menuToggle.setAttribute('aria-label', 'Open navigation');
  $('#primaryNav').classList.remove('is-open');
  document.body.classList.remove('menu-open');
}));

let revealObserver;
function observeReveals() {
  if (!('IntersectionObserver' in window)) return;
  if (!revealObserver) {
    revealObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
  }
  $$('.section-heading, .intro-copy, .intro-aside, .service-card, .about-copy, .difference-card, .gallery-item, .process-steps article, .enquiry-copy, .enquiry-form')
    .forEach((element) => {
      if (element.classList.contains('reveal')) return;
      element.classList.add('reveal');
      revealObserver.observe(element);
    });
}

$('#enquiryForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form).entries());
  const status = $('#formStatus');
  status.textContent = 'Sending your enquiry…';
  try {
    const result = await api('/api/enquiries', { method: 'POST', body: JSON.stringify(values) });
    const settings = result.settings || content.settings;
    const message = `Hello Ecronx Technologies, I would like to enquire about manpower services.\n\nName: ${values.name}\nMobile: ${values.mobile}\nEmail: ${values.email || 'Not provided'}\nService: ${values.service}\nRequirement: ${values.message || 'Please contact me to discuss.'}`;
    const number = String(settings.whatsapp || '').replace(/\D/g, '');
    if (number.length >= 10) {
      const whatsappWindow = window.open(`https://wa.me/${number}?text=${encodeURIComponent(message)}`, '_blank', 'noopener');
      status.textContent = whatsappWindow
        ? 'Enquiry saved. WhatsApp opened with your message—please press Send there.'
        : 'Enquiry saved. Your browser blocked the WhatsApp window; please contact the office directly.';
    } else {
      status.textContent = 'Enquiry saved. Our team will follow up using the contact details you provided.';
    }
    form.reset();
  } catch (error) {
    status.textContent = error.message;
  }
});

const adminModal = $('#adminModal');
$('#adminOpen').addEventListener('click', (event) => {
  event.preventDefault();
  adminModal.classList.remove('hidden');
  $('#adminLoginView').classList.remove('hidden');
  $('#adminPanel').classList.add('hidden');
  $('#adminModal input[name="password"]').focus();
});
function closeAdmin() {
  adminModal.classList.add('hidden');
  document.getElementById('adminOpen').focus();
}
$('#closeAdmin').addEventListener('click', closeAdmin);
adminModal.addEventListener('click', (event) => {
  if (event.target === adminModal) closeAdmin();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !adminModal.classList.contains('hidden')) closeAdmin();
});

$('#loginForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget).entries());
  try {
    const result = await api('/api/admin/login', { method: 'POST', body: JSON.stringify(values) });
    adminToken = result.token;
    $('#loginStatus').textContent = '';
    $('#adminLoginView').classList.add('hidden');
    $('#adminPanel').classList.remove('hidden');
    await loadAdmin();
  } catch (error) {
    $('#loginStatus').textContent = error.message;
  }
});

$('#logoutAdmin').addEventListener('click', () => {
  adminToken = '';
  $('#adminPanel').classList.add('hidden');
  $('#adminLoginView').classList.remove('hidden');
});

$$('.tab').forEach((tab) => tab.addEventListener('click', () => {
  $$('.tab').forEach((item) => item.classList.toggle('active', item === tab));
  $$('.admin-pane').forEach((pane) => pane.classList.toggle('hidden', pane.id !== tab.dataset.tab));
  if (tab.dataset.tab === 'manageEnquiries') loadEnquiries();
  if (tab.dataset.tab === 'manageSettings') fillSettings();
}));

async function loadAdmin() {
  const data = await api('/api/admin/content');
  renderAdminServices(data.services);
  renderAdminGallery(data.gallery);
  fillSettings(data.settings);
}

function renderAdminServices(items) {
  $('#adminServicesList').innerHTML = '<h3>Current services</h3>' + items.map((item) => `
    <div class="admin-row">
      <img src="${esc(imageSource(item.image))}" alt="">
      <div class="row-copy"><b>${esc(item.name)}</b><small>${esc(item.description)}</small></div>
      <div class="row-actions"><button class="edit" type="button" data-edit-service="${esc(item.id)}">Edit</button><button class="delete" type="button" data-del-service="${esc(item.id)}">Delete</button></div>
    </div>`).join('');
  $$('[data-edit-service]').forEach((button) => button.addEventListener('click', () => {
    const service = items.find((item) => item.id === button.dataset.editService);
    if (!service) return;
    const form = $('#addServiceForm');
    form.elements.id.value = service.id;
    form.elements.name.value = service.name;
    form.elements.description.value = service.description || '';
    $('#serviceFormTitle').textContent = 'Edit service';
    $('#cancelServiceEdit').classList.remove('hidden');
    form.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));
  $$('[data-del-service]').forEach((button) => button.addEventListener('click', async () => {
    if (!window.confirm('Delete this service?')) return;
    try {
      await api(`/api/admin/services/${encodeURIComponent(button.dataset.delService)}`, { method: 'DELETE' });
      await loadAdmin();
      await loadContent();
    } catch (error) { window.alert(error.message); }
  }));
}

function renderAdminGallery(items) {
  $('#adminGalleryList').innerHTML = '<h3>Current gallery images</h3>' + items.map((item) => `
    <div class="admin-row">
      <img src="${esc(imageSource(item.image))}" alt="">
      <div class="row-copy"><b>${esc(item.title)}</b><small>${esc(item.category)}</small></div>
      <div class="row-actions"><button class="edit" type="button" data-edit-gallery="${esc(item.id)}">Edit</button><button class="delete" type="button" data-del-gallery="${esc(item.id)}">Delete</button></div>
    </div>`).join('');
  $$('[data-edit-gallery]').forEach((button) => button.addEventListener('click', () => {
    const item = items.find((entry) => entry.id === button.dataset.editGallery);
    if (!item) return;
    const form = $('#addGalleryForm');
    form.elements.id.value = item.id;
    form.elements.title.value = item.title;
    form.elements.category.value = item.category || '';
    $('#galleryFormTitle').textContent = 'Edit gallery image';
    $('#cancelGalleryEdit').classList.remove('hidden');
    form.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }));
  $$('[data-del-gallery]').forEach((button) => button.addEventListener('click', async () => {
    if (!window.confirm('Delete this gallery image?')) return;
    try {
      await api(`/api/admin/gallery/${encodeURIComponent(button.dataset.delGallery)}`, { method: 'DELETE' });
      await loadAdmin();
      await loadContent();
    } catch (error) { window.alert(error.message); }
  }));
}

async function imageToUrl(file) {
  if (!file) return '';
  if (!file.type.startsWith('image/')) throw new Error('Please select an image file.');
  if (file.size > 8 * 1024 * 1024) throw new Error('Image must be smaller than 8 MB.');
  const data = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('The selected image could not be read.'));
    reader.readAsDataURL(file);
  });
  const result = await api('/api/admin/upload', { method: 'POST', body: JSON.stringify({ data }) });
  return result.url;
}

$('#addServiceForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form).entries());
  try {
    const uploadedImage = await imageToUrl(form.elements.image.files[0]);
    delete values.image;
    if (uploadedImage) values.image = uploadedImage;
    const isEdit = Boolean(values.id);
    await api(isEdit ? `/api/admin/services/${encodeURIComponent(values.id)}` : '/api/admin/services', {
      method: isEdit ? 'PUT' : 'POST',
      body: JSON.stringify(values),
    });
    form.reset();
    $('#serviceFormTitle').textContent = 'Add a service';
    $('#cancelServiceEdit').classList.add('hidden');
    await loadAdmin();
    await loadContent();
  } catch (error) { window.alert(error.message); }
});

$('#addGalleryForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form).entries());
  try {
    const uploadedImage = await imageToUrl(form.elements.image.files[0]);
    delete values.image;
    if (uploadedImage) values.image = uploadedImage;
    const isEdit = Boolean(values.id);
    if (!isEdit && !values.image) throw new Error('Please choose an image.');
    await api(isEdit ? `/api/admin/gallery/${encodeURIComponent(values.id)}` : '/api/admin/gallery', {
      method: isEdit ? 'PUT' : 'POST',
      body: JSON.stringify(values),
    });
    form.reset();
    $('#galleryFormTitle').textContent = 'Add a gallery image';
    $('#cancelGalleryEdit').classList.add('hidden');
    await loadAdmin();
    await loadContent();
  } catch (error) { window.alert(error.message); }
});

$('#cancelServiceEdit').addEventListener('click', () => {
  $('#addServiceForm').reset();
  $('#serviceFormTitle').textContent = 'Add a service';
  $('#cancelServiceEdit').classList.add('hidden');
});
$('#cancelGalleryEdit').addEventListener('click', () => {
  $('#addGalleryForm').reset();
  $('#galleryFormTitle').textContent = 'Add a gallery image';
  $('#cancelGalleryEdit').classList.add('hidden');
});

function fillSettings(settings) {
  const current = settings || content?.settings;
  if (!current) return;
  const form = $('#settingsForm');
  Object.keys(current).forEach((key) => {
    if (form.elements[key]) form.elements[key].value = current[key] || '';
  });
}

$('#settingsForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget).entries());
  try {
    await api('/api/admin/settings', { method: 'PUT', body: JSON.stringify(values) });
    await loadContent();
    window.alert('Contact details saved.');
  } catch (error) { window.alert(error.message); }
});

async function loadEnquiries() {
  try {
    const items = await api('/api/admin/enquiries');
    $('#adminEnquiriesList').innerHTML = items.length ? items.map((item) => `
      <div class="admin-row enq-row">
        <b>${esc(item.name)} · ${esc(item.service)}</b>
        <p>Mobile: ${esc(item.mobile)} · Email: ${esc(item.email || '—')}</p>
        <p>${esc(item.message || 'No additional details')}</p>
        <small>${new Date(item.date).toLocaleString()}</small>
      </div>`).join('') : '<p class="muted">No enquiries received yet.</p>';
  } catch (error) {
    $('#adminEnquiriesList').textContent = error.message;
  }
}

$('#year').textContent = new Date().getFullYear();
loadContent();
