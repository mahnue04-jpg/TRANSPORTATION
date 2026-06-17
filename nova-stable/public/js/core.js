(function () {
  'use strict';

  var token = localStorage.getItem('amicor_token') || '';
  var user = null;
  try {
    var raw = localStorage.getItem('amicor_user');
    user = raw ? JSON.parse(raw) : null;
  } catch (_) {
    localStorage.removeItem('amicor_user');
    user = null;
  }

  function toast(msg) {
    var el = document.getElementById('toast');
    if (!el) return alert(msg);
    el.textContent = msg;
    el.style.display = 'block';
    setTimeout(function () { el.style.display = 'none'; }, 2800);
  }

  function api(path, opts) {
    opts = opts || {};
    var headers = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = 'Bearer ' + token;
    if (opts.headers) {
      Object.keys(opts.headers).forEach(function (k) { headers[k] = opts.headers[k]; });
    }
    return fetch('/api' + path, {
      method: opts.method || 'GET',
      body: opts.body,
      headers: headers,
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) throw new Error(data.error || res.statusText);
        return data;
      });
    });
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

  function login(email, password) {
    return api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email: email, password: password }),
    }).then(function (data) {
      saveSession(data.token, data.user);
      return data.user;
    });
  }

  function requireAuth(allowedRoles) {
    if (!token || !user) {
      window.location.href = '/?redirect=' + encodeURIComponent(window.location.pathname);
      return false;
    }
    if (allowedRoles && allowedRoles.length && allowedRoles.indexOf(user.role) === -1 && user.role !== 'admin') {
      toast('Access denied for role: ' + user.role);
      return false;
    }
    return true;
  }

  function renderUserBar() {
    var bar = document.getElementById('userBar');
    var label = document.getElementById('userLabel');
    if (bar && label && user) {
      bar.classList.remove('hidden');
      var display = user.name || [user.first_name, user.last_name].filter(Boolean).join(' ') || user.email || 'User';
      label.textContent = display + ' (' + user.role + ')';
    }
    var logout = document.getElementById('logoutBtn');
    if (logout) logout.onclick = function () { clearSession(); location.href = '/'; };
  }

  window.Amicor = {
    api: api,
    toast: toast,
    login: login,
    saveSession: saveSession,
    clearSession: clearSession,
    requireAuth: requireAuth,
    renderUserBar: renderUserBar,
    get user: function () { return user; },
    get token: function () { return token; },
  };
})();
