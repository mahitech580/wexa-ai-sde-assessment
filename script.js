(() => {
  'use strict';
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const state = {
    token: localStorage.getItem('stockflow_token'),
    user: null,
    page: 'dashboard',
    authMode: 'login',
    query: '',
    filter: 'all',
    products: [],
    modalBusy: false,
    renderSequence: 0
  };
  const pageContent = $('#page-content');
  const authView = $('#auth-view');
  const appShell = $('#app-shell');
  const modalRoot = $('#modal-root');
  const THEME_KEY = 'stockflow_theme';
  const API_BASE_URL = String(document.querySelector('meta[name="stockflow-api-base-url"]')?.content || '').trim().replace(/\/+$/, '');
  const API_PUBLIC_KEY = String(document.querySelector('meta[name="stockflow-api-key"]')?.content || '').trim();
  let modalTrigger = null;

  function applyTheme(theme, persist = false) {
    const activeTheme = theme === 'dark' ? 'dark' : 'light';
    document.documentElement.dataset.theme = activeTheme;
    if (persist) localStorage.setItem(THEME_KEY, activeTheme);
    const nextTheme = activeTheme === 'dark' ? 'light' : 'dark';
    ['#theme-toggle', '#auth-theme-toggle'].forEach((selector) => {
      const button = $(selector);
      if (!button) return;
      button.setAttribute('aria-label', 'Switch to ' + nextTheme + ' mode');
      button.title = 'Switch to ' + nextTheme + ' mode';
      const iconNode = $('.theme-toggle-icon', button);
      const labelNode = $('.theme-toggle-label', button);
      if (iconNode) iconNode.textContent = activeTheme === 'dark' ? '☀' : '☾';
      if (labelNode) labelNode.textContent = nextTheme[0].toUpperCase() + nextTheme.slice(1) + ' mode';
    });
    const themeColor = $('meta[name="theme-color"]');
    if (themeColor) themeColor.setAttribute('content', activeTheme === 'dark' ? '#0d1522' : '#f6f8fb');
  }
  function toggleTheme() {
    applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark', true);
  }
  applyTheme(localStorage.getItem(THEME_KEY) || 'light');

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (char) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[char]);
  }
  function money(value) {
    if (value === null || value === undefined || value === '') return '—';
    return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(Number(value));
  }
  function number(value) {
    return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(Number(value || 0));
  }
  function initials(value) {
    const parts = String(value || 'S').trim().split(/\s+/).filter(Boolean);
    return (parts.length > 1 ? parts[0][0] + parts[1][0] : (parts[0] || 'S').slice(0, 2)).toUpperCase();
  }
  async function api(path, options = {}) {
    const isApiRequest = path.startsWith('/api/');
    const isGitHubPages = window.location.hostname.toLowerCase().endsWith('.github.io');
    if (isApiRequest && isGitHubPages && !API_BASE_URL) {
      throw new Error('StockFlow sign-in is not connected to its backend on this preview. Configure the stockflow-api-base-url setting with your deployed FastAPI URL, or open StockFlow from its backend deployment.');
    }
    const requestUrl = API_BASE_URL && isApiRequest ? API_BASE_URL + path : path;
    const headers = new Headers(options.headers || {});
    if (API_PUBLIC_KEY && isApiRequest) headers.set('apikey', API_PUBLIC_KEY);
    if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    if (state.token) headers.set('Authorization', 'Bearer ' + state.token);
    let response;
    try { response = await fetch(requestUrl, { ...options, headers }); }
    catch (_) { throw new Error('Unable to reach StockFlow. Check the server and try again.'); }
    if (response.status === 204) return null;
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof data.detail === 'string' ? data.detail :
        Array.isArray(data.detail) ? data.detail.map((item) => item.msg).join(', ') : 'Something went wrong. Please try again.';
      if (response.status === 401 && state.token && !path.startsWith('/api/auth/')) {
        state.token = null;
        localStorage.removeItem('stockflow_token');
        showAuth('login');
      }
      const apiError = new Error(detail);
      apiError.status = response.status;
      throw apiError;
    }
    return data;
  }
  function toast(message, type = 'success', title = '') {
    const node = document.createElement('div');
    node.className = 'toast' + (type === 'error' ? ' error' : '');
    node.innerHTML = '<span class="toast-mark">' + (type === 'error' ? '!' : '✓') + '</span><div><strong>' +
      escapeHtml(title || (type === 'error' ? 'Something needs attention' : 'All set')) +
      '</strong><span>' + escapeHtml(message) + '</span></div>';
    $('#toast-stack').append(node);
    window.setTimeout(() => { node.classList.add('toast-out'); window.setTimeout(() => node.remove(), 250); }, 3600);
  }

  function closeMarketingNav() {
    const header = $('#marketing-view .marketing-header');
    const toggle = $('#marketing-menu-toggle');
    if (header) header.classList.remove('nav-open');
    if (toggle) {
      toggle.setAttribute('aria-expanded', 'false');
      toggle.setAttribute('aria-label', 'Open website navigation');
    }
  }
  function showLanding() {
    if ($('#marketing-view')) $('#marketing-view').classList.remove('hidden');
    authView.classList.add('hidden');
    appShell.classList.add('hidden');
    closeSidebar();
    closeMarketingNav();
    document.title = 'StockFlow — Inventory, in control';
  }
  function showAuth(mode = 'login', error = '') {
    state.authMode = mode;
    if ($('#marketing-view')) $('#marketing-view').classList.add('hidden');
    authView.classList.remove('hidden');
    appShell.classList.add('hidden');
    closeSidebar();
    closeMarketingNav();
    renderAuth(mode, error);
    window.scrollTo({ top: 0, behavior: 'auto' });
    window.setTimeout(() => {
      const field = $('#auth-email');
      if (field) field.focus({ preventScroll: true });
    }, 20);
  }
  function renderAuth(mode, error = '', values = {}) {
    state.authMode = mode;
    const signup = mode === 'signup';
    $('#auth-form-content').innerHTML =
      '<div class="auth-heading">' + (signup ? 'Create your workspace' : 'Welcome back') + '</div>' +
      '<p class="auth-subtitle">' + (signup ? 'Set up your account and bring inventory into focus.' : 'Sign in to pick up where your business left off.') + '</p>' +
      (error ? '<div class="auth-error" role="alert">' + escapeHtml(error) + '</div>' : '') +
      '<form id="' + (signup ? 'signup-form' : 'login-form') + '" novalidate>' +
      (signup ? '<div class="form-field"><label for="org-name">Organization name</label><input class="form-control" id="org-name" name="organization_name" value="' + escapeHtml(values.organization_name || '') + '" placeholder="e.g. Northstar Supply Co." maxlength="80" required autocomplete="organization"></div>' : '') +
      '<div class="form-field"><label for="auth-email">Email address</label><input class="form-control" id="auth-email" name="email" type="email" value="' + escapeHtml(values.email || '') + '" placeholder="you@company.com" maxlength="254" required autocomplete="email"></div>' +
      '<div class="form-field"><label for="auth-password">Password</label><input class="form-control" id="auth-password" name="password" type="password" placeholder="' + (signup ? 'At least 8 characters' : 'Enter your password') + '" minlength="' + (signup ? '8' : '1') + '" maxlength="128" required autocomplete="' + (signup ? 'new-password' : 'current-password') + '"></div>' +
      (signup ? '<div class="form-field"><label for="confirm-password">Confirm password</label><input class="form-control" id="confirm-password" name="confirm_password" type="password" minlength="8" maxlength="128" required autocomplete="new-password"></div>' : '') +
      '<button type="submit" class="auth-submit">' + (signup ? 'Create account' : 'Sign in to StockFlow') + ' <span aria-hidden="true">→</span></button></form>' +
      '<p class="auth-switch"><button class="text-button" type="button" data-action="demo-access">Try demo access — no account needed</button></p>' +
      '<p class="auth-switch">' + (signup ? 'Already have an account?' : 'New to StockFlow?') +
      ' <button class="text-button" type="button" data-auth-mode="' + (signup ? 'login' : 'signup') + '">' + (signup ? 'Sign in' : 'Create an account') + '</button></p>';
  }
  function showApp(user) {
    state.user = user;
    if ($('#marketing-view')) $('#marketing-view').classList.add('hidden');
    authView.classList.add('hidden');
    closeMarketingNav();
    appShell.classList.remove('hidden');
    $('#workspace-name').textContent = user.organization_name || 'My Workspace';
    $('#workspace-avatar').textContent = initials(user.organization_name);
    $('#user-email').textContent = user.email;
    const workspaceSubtitle = $('.workspace-info span');
    if (workspaceSubtitle) workspaceSubtitle.textContent = user.is_demo ? 'Demo workspace · isolated data' : 'Owner workspace';
    $('#user-avatar').textContent = initials(user.email);
    $('#today-label').textContent = new Intl.DateTimeFormat('en-IN', { weekday: 'short', month: 'short', day: 'numeric' }).format(new Date());
    $('#footer-year').textContent = new Date().getFullYear();
    renderPage('dashboard');
  }
  async function openDemoWorkspace() {
    let sessionId = localStorage.getItem('stockflow_demo_session_id');
    if (!sessionId) {
      sessionId = window.crypto && typeof window.crypto.randomUUID === 'function'
        ? window.crypto.randomUUID()
        : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
          const random = Math.floor(Math.random() * 16);
          return (char === 'x' ? random : (random & 3) | 8).toString(16);
        });
      localStorage.setItem('stockflow_demo_session_id', sessionId);
    }
    const data = await api('/api/auth/demo', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId })
    });
    state.token = data.access_token;
    state.user = data.user;
    localStorage.setItem('stockflow_token', state.token);
    showApp(data.user);
    toast('You are in a private demo workspace. No existing account is needed.', 'success', 'Demo mode');
  }
  function setActivePage(page) {
    state.page = page;
    $$('.nav-item').forEach((button) => button.classList.toggle('active', button.dataset.page === page));
    const labels = { dashboard: 'Dashboard', products: 'Products', settings: 'Settings' };
    $('#breadcrumb-current').textContent = labels[page] || 'Dashboard';
    if (page !== 'products') $('#global-search-input').value = '';
  }
  async function renderPage(page) {
    const renderId = ++state.renderSequence;
    state.page = page;
    setActivePage(page);
    closeSidebar();
    pageContent.setAttribute('aria-busy', 'true');
    pageContent.innerHTML = '<div class="panel loading-state"><span class="loader"></span><strong>Loading your workspace…</strong></div>';
    try {
      if (page === 'dashboard') await renderDashboard(renderId);
      else if (page === 'products') await renderProducts(state.query, renderId);
      else if (page === 'settings') await renderSettings(renderId);
      else await renderDashboard(renderId);
    } catch (error) {
      if (renderId !== state.renderSequence) return;
      pageContent.innerHTML = '<div class="panel empty-state"><div class="empty-state-icon">!</div><strong>We could not load this page</strong><p>' + escapeHtml(error.message) + '</p><button class="btn-secondary" data-action="retry-page">Try again</button></div>';
    } finally {
      if (renderId === state.renderSequence) pageContent.setAttribute('aria-busy', 'false');
    }
  }
  function sectionHead(kicker, title, copy, action) {
    const view = ['dashboard', 'products', 'settings'].includes(state.page) ? state.page : 'dashboard';
    return '<div class="section-head section-head-' + view + '" data-workspace-section="' + view + '"><div><span class="eyebrow">' + kicker + '</span><h1>' + title + '</h1><p>' + copy + '</p></div>' + (action || '') + '</div>';
  }
  function statCard(label, value, note, symbol, tone) {
    return '<article class="stat-card"><div class="stat-top"><span>' + label + '</span><span class="stat-icon ' + tone + '">' + symbol + '</span></div><strong class="stat-value">' + value + '</strong><span class="stat-note">' + note + '</span></article>';
  }
  function stockBadge(item) {
    return item.is_low_stock ? '<span class="badge badge-low">Low stock</span>' : '<span class="badge badge-good">In stock</span>';
  }
  function lowStockTable(items) {
    if (!items.length) return '<div class="empty-inline"><span class="empty-circle">✓</span><div><strong>Everything looks healthy</strong><p>No products are below their stock threshold.</p></div></div>';
    return '<div class="table-wrap"><table><thead><tr><th>Product</th><th>SKU</th><th>On hand</th><th>Threshold</th></tr></thead><tbody>' +
      items.map((p) => '<tr><td><strong class="product-name">' + escapeHtml(p.name) + '</strong></td><td><span class="sku">' + escapeHtml(p.sku) + '</span></td><td><span class="quantity-low">' + number(p.quantity_on_hand) + '</span></td><td>' + number(p.effective_low_stock_threshold) + '</td></tr>').join('') +
      '</tbody></table></div>';
  }
  async function renderDashboard(renderId) {
    const data = await api('/api/dashboard');
    if (renderId !== state.renderSequence) return;
    state.products = data.recent_products || [];
    const low = data.low_stock_items || [];
    pageContent.innerHTML = sectionHead('OVERVIEW', 'Your inventory, at a glance', 'A clear view of what is on your shelves and what needs attention.',
      '<button class="btn-primary" data-action="new-product">＋ Add product</button>') +
      '<div class="stats-grid">' +
      statCard('Total products', number(data.total_products), 'Items in your catalog', '▦', 'blue') +
      statCard('Units on hand', number(data.total_units), 'Across all products', '↗', 'violet') +
      statCard('Low-stock items', number(data.low_stock_count), 'At or below threshold', '!', 'amber') +
      '</div>' +
      '<div class="dashboard-grid"><section class="panel"><div class="panel-heading"><div><span class="eyebrow">NEEDS ATTENTION</span><h2>Low-stock items</h2><p>Products that need a restock soon.</p></div><button class="text-button" data-action="review-low-stock">View all →</button></div>' +
      lowStockTable(low) + '</section><aside class="panel quick-panel"><span class="eyebrow">QUICK ACTIONS</span><h2>Keep things moving</h2><p>Small, consistent updates make your inventory more reliable.</p><button class="quick-action" data-action="new-product"><span class="quick-icon">＋</span><span><strong>Add a product</strong><small>Record a new item</small></span><b>→</b></button>' +
      '<button class="quick-action" data-page="products"><span class="quick-icon">▦</span><span><strong>Browse catalog</strong><small>Search and update stock</small></span><b>→</b></button><button class="quick-action" data-page="settings"><span class="quick-icon">⚙</span><span><strong>Stock preferences</strong><small>Set the default threshold</small></span><b>→</b></button>' +
      (data.total_products === 0 ? '<div class="sample-card"><strong>Want to explore first?</strong><p>Load a small sample catalog to see how the dashboard works. You can edit or delete everything afterwards.</p><button class="btn-secondary" data-action="load-sample-data">Load sample catalog</button></div>' : '') +
      '</aside></div><section class="panel catalog-preview"><div class="panel-heading"><div><span class="eyebrow">RECENTLY UPDATED</span><h2>Recent products</h2></div><button class="text-button" data-page="products">Open catalog →</button></div>' +
      (state.products.length ? '<div class="recent-list">' + state.products.slice(0, 5).map((p) => '<div class="recent-item"><div class="product-tile">' + escapeHtml(initials(p.name)) + '</div><div class="recent-info"><strong>' + escapeHtml(p.name) + '</strong><span>' + escapeHtml(p.sku) + '</span></div><div class="recent-qty"><strong>' + number(p.quantity_on_hand) + '</strong><span>units</span></div>' + stockBadge(p) + '</div>').join('') + '</div>' : '<div class="empty-inline"><span class="empty-circle">＋</span><div><strong>Your catalog starts here</strong><p>Add your first product to bring this dashboard to life.</p></div></div>') + '</section>';
  }
  async function renderProducts(query = '', renderId) {
    const data = await api('/api/products?q=' + encodeURIComponent(query || ''));
    if (renderId !== state.renderSequence) return;
    state.products = data.items || [];
    let products = state.products;
    if (state.filter === 'low') products = products.filter((item) => item.is_low_stock);
    pageContent.innerHTML = sectionHead('CATALOG', 'Products', 'Manage names, SKUs, prices and quantities in one place.',
      '<button class="btn-primary" data-action="new-product">＋ Add product</button>') +
      '<section class="panel product-panel"><div class="catalog-toolbar"><div><h2>All products <span class="count-pill">' + number(products.length) + '</span></h2><p>Search by product name or SKU.</p></div><div class="filter-tabs"><button data-filter="all" class="' + (state.filter === 'all' ? 'selected' : '') + '">All items</button><button data-filter="low" class="' + (state.filter === 'low' ? 'selected' : '') + '">Low stock</button></div></div>' +
      (products.length ? '<div class="table-wrap"><table><thead><tr><th>Product</th><th>SKU</th><th>On hand</th><th>Stock status</th><th>Selling price</th><th>Actions</th></tr></thead><tbody>' +
      products.map((p) => '<tr data-product-row="' + p.id + '"><td><div class="product-cell"><div class="product-tile">' + escapeHtml(initials(p.name)) + '</div><div><strong class="product-name">' + escapeHtml(p.name) + '</strong><small>' + escapeHtml(p.description || 'Inventory item') + '</small></div></div></td><td><span class="sku">' + escapeHtml(p.sku) + '</span></td><td><strong class="' + (p.is_low_stock ? 'quantity-low' : '') + '">' + number(p.quantity_on_hand) + '</strong></td><td>' + stockBadge(p) + '</td><td>' + money(p.selling_price) + '</td><td><div class="table-actions"><button class="icon-button" title="Adjust stock" aria-label="Adjust stock for ' + escapeHtml(p.name) + '" data-action="stock-adjust" data-id="' + p.id + '">±</button><button class="icon-button" title="Edit product" aria-label="Edit ' + escapeHtml(p.name) + '" data-action="edit-product" data-id="' + p.id + '">✎</button><button class="icon-button danger" title="Delete product" aria-label="Delete ' + escapeHtml(p.name) + '" data-action="delete-product" data-id="' + p.id + '">×</button></div></td></tr>').join('') +
      '</tbody></table></div>' : '<div class="empty-state"><div class="empty-state-icon">▦</div><strong>' + (state.filter === 'low' ? 'No low-stock products' : (query ? 'No matching products' : 'Your catalog is empty')) + '</strong><p>' + (query ? 'Try a different product name or SKU.' : 'Add a product to begin tracking stock and prices.') + '</p>' +
      (query ? '<button class="btn-secondary" data-action="clear-search">Clear search</button>' : '<button class="btn-secondary" data-action="new-product">Add your first product</button>') + '</div>') + '</section>';
    $('#product-nav-count').textContent = number(data.count || 0);
    $('#product-nav-count').classList.toggle('hidden', !data.count);
  }
  async function renderSettings(renderId) {
    const data = await api('/api/settings');
    if (renderId !== state.renderSequence) return;
    pageContent.innerHTML = sectionHead('PREFERENCES', 'Settings', 'One simple default keeps low-stock alerts consistent across your workspace.') +
      '<div class="settings-layout"><section class="panel settings-card"><div class="panel-heading"><div><span class="eyebrow">INVENTORY RULES</span><h2>Low-stock threshold</h2><p>Used when an individual product has no custom threshold.</p></div></div>' +
      '<form id="settings-form"><div class="form-field"><label for="default-threshold">Default low-stock threshold</label><input class="form-control threshold-input" id="default-threshold" name="default_low_stock_threshold" type="number" min="0" max="2000000000" step="1" required value="' + Number(data.default_low_stock_threshold) + '"><small>Products at or below this quantity are marked low stock.</small></div><button type="submit" class="btn-primary">Save preferences</button></form></section>' +
      '<aside class="panel settings-note"><div class="note-mark">i</div><h3>How the threshold works</h3><p>A product-specific threshold overrides this default. When its threshold is blank, StockFlow uses the value saved here.</p><div class="threshold-example"><div><span>Default threshold</span><strong>' + number(data.default_low_stock_threshold) + ' units</strong></div><div><span>Example product quantity</span><strong>3 units</strong></div></div></aside></div>';
  }
  function openModal(markup) {
    modalTrigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    modalRoot.innerHTML = markup;
    document.body.classList.add('modal-open');
    const first = modalRoot.querySelector('input,button,textarea');
    if (first) first.focus();
  }
  function closeModal() {
    modalRoot.innerHTML = '';
    document.body.classList.remove('modal-open');
    state.modalBusy = false;
    const trigger = modalTrigger;
    modalTrigger = null;
    if (trigger && trigger.isConnected && typeof trigger.focus === 'function') trigger.focus();
  }
  function productFormValues(form) {
    const values = new FormData(form);
    const optionalNumber = (key) => {
      const v = String(values.get(key) || '').trim();
      return v === '' ? null : Number(v);
    };
    return {
      name: String(values.get('name') || '').trim(),
      sku: String(values.get('sku') || '').trim().toUpperCase(),
      description: String(values.get('description') || '').trim() || null,
      quantity_on_hand: Number(values.get('quantity_on_hand')),
      cost_price: optionalNumber('cost_price'),
      selling_price: optionalNumber('selling_price'),
      low_stock_threshold: optionalNumber('low_stock_threshold')
    };
  }
  function productFields(product = {}) {
    return '<div class="form-grid"><div class="form-field"><label for="product-name">Product name *</label><input class="form-control" id="product-name" name="name" maxlength="120" required value="' + escapeHtml(product.name || '') + '"></div>' +
      '<div class="form-field"><label for="product-sku">SKU *</label><input class="form-control" id="product-sku" name="sku" maxlength="64" required value="' + escapeHtml(product.sku || '') + '"></div>' +
      '<div class="form-field"><label for="product-quantity">Quantity on hand *</label><input class="form-control" id="product-quantity" name="quantity_on_hand" type="number" min="0" step="1" required value="' + Number(product.quantity_on_hand || 0) + '"></div>' +
      '<div class="form-field"><label for="product-threshold">Low-stock threshold</label><input class="form-control" id="product-threshold" name="low_stock_threshold" type="number" min="0" step="1" placeholder="Use workspace default" value="' + (product.low_stock_threshold == null ? '' : Number(product.low_stock_threshold)) + '"></div>' +
      '<div class="form-field"><label for="product-cost">Cost price</label><input class="form-control" id="product-cost" name="cost_price" type="number" min="0" step="0.01" value="' + (product.cost_price == null ? '' : Number(product.cost_price)) + '"></div>' +
      '<div class="form-field"><label for="product-selling">Selling price</label><input class="form-control" id="product-selling" name="selling_price" type="number" min="0" step="0.01" value="' + (product.selling_price == null ? '' : Number(product.selling_price)) + '"></div>' +
      '<div class="form-field full-field"><label for="product-description">Description (optional)</label><textarea class="form-control" id="product-description" name="description" rows="3" maxlength="2000">' + escapeHtml(product.description || '') + '</textarea></div></div>';
  }
  async function openProductModal(id = null) {
    let product = {};
    if (id != null) {
      try { product = (await api('/api/products/' + encodeURIComponent(id))).item; }
      catch (error) { toast(error.message, 'error'); return; }
    }
    openModal('<div class="modal-backdrop" data-action="backdrop-close"><section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="product-modal-title"><div class="modal-head"><div><span class="eyebrow">' + (id == null ? 'NEW ITEM' : 'EDIT ITEM') + '</span><h2 id="product-modal-title">' + (id == null ? 'Add a product' : 'Edit product') + '</h2><p>Enter the details you use to track this item.</p></div><button class="icon-button" data-action="close-modal" aria-label="Close">×</button></div><form id="product-form" data-product-id="' + (id == null ? '' : id) + '">' + productFields(product) + '<div id="product-form-error" class="auth-error hidden" role="alert"></div><div class="modal-actions"><button type="button" class="btn-secondary" data-action="close-modal">Cancel</button><button type="submit" class="btn-primary">' + (id == null ? 'Create product' : 'Save changes') + '</button></div></form></section></div>');
  }
  function openStockAdjustmentModal(id) {
    const product = state.products.find((item) => String(item.id) === String(id));
    openModal('<div class="modal-backdrop" data-action="backdrop-close"><section class="modal-card compact-modal" role="dialog" aria-modal="true" aria-labelledby="stock-adjust-modal-title"><div class="modal-head"><div><span class="eyebrow">INVENTORY UPDATE</span><h2 id="stock-adjust-modal-title">Adjust stock</h2><p>' + escapeHtml(product ? product.name : 'Product') + '</p></div><button class="icon-button" data-action="close-modal" aria-label="Close">×</button></div><form id="stock-adjust-form" data-product-id="' + id + '"><div class="form-field"><label for="stock-delta">Change in units</label><input id="stock-delta" class="form-control" name="delta" type="number" step="1" required placeholder="e.g. 12 or -3"></div><div class="form-field"><label for="stock-note">Reason</label><textarea id="stock-note" class="form-control" name="note" minlength="3" maxlength="300" required rows="3" placeholder="e.g. New delivery received"></textarea></div><div id="stock-adjust-error" class="auth-error hidden" role="alert"></div><div class="modal-actions"><button class="btn-secondary" type="button" data-action="close-modal">Cancel</button><button id="save-stock-adjustment" class="btn-primary" type="submit">Apply adjustment</button></div></form></section></div>');
  }
  function openDeleteModal(id, name) {
    openModal('<div class="modal-backdrop" data-action="backdrop-close"><section class="modal-card compact-modal" role="dialog" aria-modal="true" aria-labelledby="delete-product-modal-title"><div class="modal-head"><div><span class="eyebrow">CONFIRM ACTION</span><h2 id="delete-product-modal-title">Delete product?</h2><p>This removes <strong>' + escapeHtml(name) + '</strong> from your catalog.</p></div><button class="icon-button" data-action="close-modal" aria-label="Close">×</button></div><p class="modal-warning">This cannot be undone.</p><div class="modal-actions"><button class="btn-secondary" data-action="close-modal">Cancel</button><button class="btn-danger" data-action="confirm-delete" data-id="' + id + '">Delete product</button></div></section></div>');
  }
  async function handleProductSubmit(form) {
    const errorBox = $('#product-form-error');
    const button = form.querySelector('button[type="submit"]');
    const payload = productFormValues(form);
    if (!payload.name || !payload.sku || !Number.isInteger(payload.quantity_on_hand) || payload.quantity_on_hand < 0) {
      errorBox.textContent = 'Enter a name, SKU and non-negative whole-number quantity.';
      errorBox.classList.remove('hidden');
      return;
    }
    state.modalBusy = true;
    button.disabled = true;
    button.textContent = 'Saving…';
    errorBox.classList.add('hidden');
    try {
      const id = form.dataset.productId;
      await api(id ? '/api/products/' + encodeURIComponent(id) : '/api/products', {
        method: id ? 'PATCH' : 'POST', body: JSON.stringify(payload)
      });
      closeModal();
      toast(id ? 'Product details saved.' : 'Product added to your catalog.', 'success', id ? 'Changes saved' : 'Product created');
      await renderPage(state.page);
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove('hidden');
      button.disabled = false;
      button.textContent = form.dataset.productId ? 'Save changes' : 'Create product';
      state.modalBusy = false;
    }
  }
  async function loadSampleCatalog(triggerButton) {
    const samples = [
      { name: 'Organic Green Tea', sku: 'TEA-001', description: 'Loose-leaf green tea', quantity_on_hand: 3, cost_price: 80, selling_price: 125, low_stock_threshold: 5 },
      { name: 'Cotton Tote Bag', sku: 'BAG-042', description: 'Reusable everyday tote', quantity_on_hand: 18, cost_price: 90, selling_price: 199, low_stock_threshold: 5 },
      { name: 'A5 Notebook', sku: 'NOTE-006', description: 'A5 ruled notebook', quantity_on_hand: 54, cost_price: 65, selling_price: 129, low_stock_threshold: 12 }
    ];
    if (state.modalBusy) return;
    state.modalBusy = true;
    triggerButton.disabled = true;
    let created = 0;
    try {
      for (const item of samples) { await api('/api/products', { method: 'POST', body: JSON.stringify(item) }); created += 1; }
      toast(created + ' sample products added.');
      await renderPage(state.page);
    } catch (error) {
      toast(created + ' sample products added before the issue. ' + error.message, 'error');
    } finally {
      state.modalBusy = false;
      if (triggerButton.isConnected) triggerButton.disabled = false;
    }
    // Refresh after partial failure too, so the dashboard never shows stale totals.
    if (created > 0) await renderPage(state.page);
  }
  async function deleteProduct(id) {
    try {
      await api('/api/products/' + encodeURIComponent(id), { method: 'DELETE' });
      closeModal();
      toast('Product removed from your inventory.');
      await renderPage(state.page);
    } catch (error) { toast(error.message, 'error'); }
  }

  document.addEventListener('click', async (event) => {
    const target = event.target.closest('button, [data-action], [data-page], [data-filter], a[href^="#"]');
    if (!target) return;
    if (target.matches('.marketing-nav a, .marketing-footer nav a, .hero-scroll-cue, .feature-link, .marketing-brand')) {
      closeMarketingNav();
      return;
    }
    if (target.id === 'marketing-menu-toggle') {
      const header = $('#marketing-view .marketing-header');
      const toggle = $('#marketing-menu-toggle');
      const opened = header.classList.toggle('nav-open');
      toggle.setAttribute('aria-expanded', opened ? 'true' : 'false');
      toggle.setAttribute('aria-label', opened ? 'Close website navigation' : 'Open website navigation');
      return;
    }
    if (target.id === 'marketing-theme-toggle') { toggleTheme(); return; }
    if (target.dataset.authMode) { showAuth(target.dataset.authMode); return; }
    if (target.dataset.page) {
      if (target.tagName === 'A') event.preventDefault();
      window.clearTimeout(state.searchTimer);
      state.filter = 'all';
      state.query = '';
      $('#global-search-input').value = '';
      renderPage(target.dataset.page);
      return;
    }
    if (target.dataset.filter) { state.filter = target.dataset.filter; await renderPage('products'); return; }
    const action = target.dataset.action;
    if (!action) return;
    if (action === 'demo-access') { try { await openDemoWorkspace(); } catch (error) { showAuth(state.authMode, error.message); } return; }
    if (action === 'new-product') { await openProductModal(); return; }
    if (action === 'review-low-stock') { state.filter = 'low'; state.query = ''; $('#global-search-input').value = ''; await renderPage('products'); return; }
    if (action === 'load-sample-data') { await loadSampleCatalog(target); return; }
    if (action === 'edit-product') { await openProductModal(target.dataset.id); return; }
    if (action === 'stock-adjust') { openStockAdjustmentModal(target.dataset.id); return; }
    if (action === 'delete-product') {
      const row = target.closest('tr');
      openDeleteModal(target.dataset.id, row ? row.querySelector('.product-name').textContent : 'this product');
      return;
    }
    if (action === 'confirm-delete') { await deleteProduct(target.dataset.id); return; }
    if (action === 'close-modal') { closeModal(); return; }
    if (action === 'backdrop-close' && event.target === target) { closeModal(); return; }
    if (action === 'clear-search') { state.query = ''; $('#global-search-input').value = ''; await renderPage('products'); return; }
    if (action === 'retry-page') { await renderPage(state.page); return; }
  });

  document.addEventListener('submit', async (event) => {
    const form = event.target;
    if (form.id === 'login-form') {
      event.preventDefault();
      const values = new FormData(form);
      try {
        const data = await api('/api/auth/login', { method: 'POST', body: JSON.stringify({
          email: String(values.get('email') || '').trim(), password: String(values.get('password') || '')
        })});
        state.token = data.access_token;
        localStorage.setItem('stockflow_token', state.token);
        showApp(data.user);
        toast('Welcome back to your workspace.');
      } catch (error) {
        // Failed credentials must never silently switch the user into a demo account.
        renderAuth('login', error.message, { email: String(values.get('email') || '').trim() });
      }
    }
    if (form.id === 'signup-form') {
      event.preventDefault();
      const values = new FormData(form);
      const password = String(values.get('password') || '');
      const authValues = {
        organization_name: String(values.get('organization_name') || '').trim(),
        email: String(values.get('email') || '').trim()
      };
      if (password !== String(values.get('confirm_password') || '')) {
        renderAuth('signup', 'Passwords do not match.', authValues);
        return;
      }
      if (password.length < 8) {
        renderAuth('signup', 'Password must be at least 8 characters.', authValues);
        return;
      }
      try {
        const data = await api('/api/auth/signup', { method: 'POST', body: JSON.stringify({
          organization_name: authValues.organization_name,
          email: authValues.email, password
        })});
        state.token = data.access_token;
        localStorage.setItem('stockflow_token', state.token);
        showApp(data.user);
        toast('Your workspace is ready. Add your first product to begin.');
      } catch (error) {
        // Validation and duplicate-account errors should be visible, not redirected to demo mode.
        renderAuth('signup', error.message, authValues);
      }
    }
    if (form.id === 'product-form') { event.preventDefault(); await handleProductSubmit(form); }
    if (form.id === 'stock-adjust-form') {
      event.preventDefault();
      const values = new FormData(form);
      const delta = Number(values.get('delta'));
      const note = String(values.get('note') || '').trim();
      const errorBox = $('#stock-adjust-error');
      const button = $('#save-stock-adjustment');
      if (!Number.isInteger(delta) || delta === 0 || note.length < 3) {
        errorBox.textContent = 'Enter a non-zero whole-number adjustment and a short reason.';
        errorBox.classList.remove('hidden'); return;
      }
      button.disabled = true;
      try {
        const response = await api('/api/products/' + encodeURIComponent(form.dataset.productId) + '/adjust-stock', {
          method: 'POST', body: JSON.stringify({ delta, note })
        });
        closeModal();
        toast('Stock updated. New quantity: ' + number(response.item.quantity_on_hand));
        await renderPage(state.page);
      } catch (error) {
        errorBox.textContent = error.message;
        errorBox.classList.remove('hidden'); button.disabled = false;
      }
    }
    if (form.id === 'settings-form') {
      event.preventDefault();
      const value = Number($('#default-threshold').value);
      if (!Number.isInteger(value) || value < 0) { toast('Enter a non-negative whole number.', 'error'); return; }
      const button = form.querySelector('button[type="submit"]');
      button.disabled = true;
      try {
        await api('/api/settings', { method: 'PATCH', body: JSON.stringify({ default_low_stock_threshold: value }) });
        toast('Your default stock threshold has been updated.');
        await renderPage('settings');
      } catch (error) { toast(error.message, 'error'); button.disabled = false; }
    }
  });

  $('#global-search-input').addEventListener('input', () => {
    state.query = $('#global-search-input').value.trim();
    window.clearTimeout(state.searchTimer);
    state.searchTimer = window.setTimeout(() => {
      state.filter = state.filter || 'all';
      renderPage('products');
    }, 200);
  });
  $('#theme-toggle').addEventListener('click', toggleTheme);
  $('#auth-theme-toggle').addEventListener('click', toggleTheme);
  $('#mobile-menu-button').addEventListener('click', () => {
    if ($('#sidebar').classList.contains('sidebar-open')) closeSidebar();
    else openSidebar();
  });
  $('#sidebar-scrim').addEventListener('click', closeSidebar);
  $('#logout-button').addEventListener('click', () => {
    state.token = null; state.user = null; localStorage.removeItem('stockflow_token'); showAuth('login');
    toast('You have been signed out safely.');
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { closeModal(); closeSidebar(); closeMarketingNav(); return; }
    if (event.key !== 'Tab' || !modalRoot.querySelector('[role="dialog"]')) return;
    const focusable = [...modalRoot.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )].filter((element) => !element.hidden && element.getAttribute('aria-hidden') !== 'true');
    if (!focusable.length) { event.preventDefault(); return; }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || !modalRoot.contains(document.activeElement))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !modalRoot.contains(document.activeElement))) {
      event.preventDefault();
      first.focus();
    }
  });

  function openSidebar() {
    $('#sidebar').classList.add('sidebar-open');
    $('#sidebar-scrim').classList.remove('hidden');
    $('#mobile-menu-button').setAttribute('aria-expanded', 'true');
    $('#mobile-menu-button').setAttribute('aria-label', 'Close navigation');
  }
  function closeSidebar() {
    if ($('#sidebar')) $('#sidebar').classList.remove('sidebar-open');
    if ($('#sidebar-scrim')) $('#sidebar-scrim').classList.add('hidden');
    if ($('#mobile-menu-button')) {
      $('#mobile-menu-button').setAttribute('aria-expanded', 'false');
      $('#mobile-menu-button').setAttribute('aria-label', 'Open navigation');
    }
  }

  function setupRevealAnimations() {
    const elements = $('.reveal');
    if (!elements.length) return;
    if (!('IntersectionObserver' in window)) {
      elements.forEach((element) => element.classList.add('is-visible'));
      return;
    }
    document.documentElement.classList.add('motion-ready');
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -32px 0px' });
    elements.forEach((element) => observer.observe(element));
  }

  async function boot() {
    $('#footer-year').textContent = new Date().getFullYear();
    const marketingYear = $('#marketing-year');
    if (marketingYear) marketingYear.textContent = new Date().getFullYear();
    setupRevealAnimations();
    if (!state.token) { showLanding(); return; }
    try { const data = await api('/api/me'); showApp(data.user); }
    catch (_) { state.token = null; localStorage.removeItem('stockflow_token'); showLanding(); }
  }
  boot();
})();
