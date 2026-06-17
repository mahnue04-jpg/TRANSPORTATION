(function () {
  'use strict';

  let token = localStorage.getItem('amicor_token') || '';
  let user = null;
  try {
    const raw = localStorage.getItem('amicor_user');
    user = raw ? JSON.parse(raw) : null;
  } catch (_) {
    localStorage.removeItem('amicor_user');
    user = null;
  }
  let socket = null;

  function toast(msg) {
    const el = document.getElementById('toast');
    if (!el) return alert(msg);
    el.textContent = msg;
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, 2800);
  }

  async function api(path, opts) {
    const res = await fetch('/api' + path, {
      ...opts,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: 'Bearer ' + token } : {}),
        ...(opts && opts.headers ? opts.headers : {}),
      },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  }

  function saveSession(nextToken, nextUser) {
    token = nextToken;
    user = nextUser;
    localStorage.setItem('amicor_token', token);
    localStorage.setItem('amicor_user', JSON.stringify(user));
  }

  function clearSession() {
    token = '';
    user = null;
    localStorage.removeItem('amicor_token');
    localStorage.removeItem('amicor_user');
  }

  function connectSocket(handlers) {
    if (typeof io === 'undefined') return;
    if (typeof AmicorStable !== 'undefined' && handlers && handlers.refresh) {
      socket = AmicorStable.connectStableSocket(handlers, handlers.refresh, { debounceMs: 2500 });
      return;
    }
    socket = io();
    Object.entries(handlers || {}).forEach(([event, fn]) => socket.on(event, fn));
    let debounced = () => { if (handlers && handlers.refresh) handlers.refresh(); };
    if (typeof AmicorStable !== 'undefined') debounced = AmicorStable.debounce(debounced, 2500);
    socket.on('ops:update', debounced);
  }

  async function login(email, password) {
    const data = await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    saveSession(data.token, data.user);
    return data.user;
  }

  function requireAuth(allowedRoles) {
    if (!token || !user) {
      window.location.href = '/?redirect=' + encodeURIComponent(window.location.pathname);
      return false;
    }
    if (allowedRoles && allowedRoles.length && !allowedRoles.includes(user.role) && user.role !== 'admin') {
      toast('Access denied for role: ' + user.role);
      return false;
    }
    return true;
  }

  function renderUserBar() {
    const bar = document.getElementById('userBar');
    const label = document.getElementById('userLabel');
    if (bar && label && user) {
      bar.classList.remove('hidden');
      const display = user.name || [user.first_name, user.last_name].filter(Boolean).join(' ') || user.email || 'User';
      label.textContent = display + ' (' + user.role + ')';
    }
    const logout = document.getElementById('logoutBtn');
    if (logout) logout.onclick = () => { clearSession(); location.href = '/'; };
  }

  window.Amicor = { api, toast, login, saveSession, clearSession, connectSocket, requireAuth, renderUserBar, get user() { return user; }, get token() { return token; } };
})();
