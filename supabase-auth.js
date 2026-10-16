/* Minimal Supabase Auth client using browser APIs; keeps the static app dependency-free. */
window.CrossplayAuth = (() => {
  const config = window.CROSSPLAY_SUPABASE_CONFIG || {};
  const storageKey = 'crossplay.supabase.session';
  const verifierKey = 'crossplay.supabase.pkce-verifier';
  let session = null;
  let refreshPromise = null;

  function configured() {
    return Boolean(config.url && config.publishableKey);
  }

  function readSession() {
    try {
      const value = JSON.parse(localStorage.getItem(storageKey) || 'null');
      return value && typeof value.access_token === 'string' && typeof value.refresh_token === 'string' ? value : null;
    } catch (_) { return null; }
  }

  function saveSession(value) {
    if (!value || !value.access_token || !value.refresh_token) throw new Error('Supabase returned an incomplete login session.');
    const expiresIn = Number(value.expires_in) || 3600;
    session = {
      access_token: value.access_token,
      refresh_token: value.refresh_token,
      token_type: value.token_type || 'bearer',
      expires_at: Number(value.expires_at) || Math.floor(Date.now() / 1000) + expiresIn,
      user: value.user || (session && session.user) || null
    };
    localStorage.setItem(storageKey, JSON.stringify(session));
    return session;
  }

  function clearSession() {
    session = null;
    localStorage.removeItem(storageKey);
  }

  async function authRequest(path, body, accessToken) {
    const response = await fetch(config.url.replace(/\/$/, '') + '/auth/v1/' + path, {
      method: 'POST',
      cache: 'no-store',
      headers: {
        apikey: config.publishableKey,
        'Content-Type': 'application/json',
        ...(accessToken ? { Authorization: 'Bearer ' + accessToken } : {})
      },
      body: JSON.stringify(body)
    });
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(data.msg || data.message || data.error_description || data.error || 'Supabase authentication failed.');
    return data;
  }

  function base64Url(bytes) {
    let binary = '';
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
  }

  async function createPkcePair() {
    const bytes = new Uint8Array(32);
    crypto.getRandomValues(bytes);
    const verifier = base64Url(bytes);
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
    return { verifier, challenge: base64Url(new Uint8Array(digest)) };
  }

  async function completeCallback() {
    const url = new URL(location.href);
    const fragment = new URLSearchParams(url.hash.replace(/^#/, ''));
    const code = url.searchParams.get('code') || fragment.get('code');
    const error = url.searchParams.get('error_description') || url.searchParams.get('error') ||
      fragment.get('error_description') || fragment.get('error');
    if (error) {
      url.searchParams.delete('error');
      url.searchParams.delete('error_description');
      url.hash = '';
      history.replaceState({}, '', url.pathname + url.search);
      sessionStorage.removeItem(verifierKey);
      throw new Error(error);
    }
    if (!code) return;
    const verifier = sessionStorage.getItem(verifierKey);
    sessionStorage.removeItem(verifierKey);
    url.searchParams.delete('code');
    url.hash = '';
    history.replaceState({}, '', url.pathname + url.search);
    if (!verifier) {
      throw new Error('The Google sign-in could not be verified. Please try again.');
    }
    const result = await authRequest('token?grant_type=pkce', { auth_code: code, code_verifier: verifier });
    saveSession(result);
  }

  async function refreshSession() {
    if (refreshPromise) return refreshPromise;
    refreshPromise = (async () => {
      const current = session || readSession();
      if (!current || !current.refresh_token) { clearSession(); return null; }
      try {
        const refreshed = await authRequest('token?grant_type=refresh_token', { refresh_token: current.refresh_token });
        return saveSession(refreshed);
      } catch (error) {
        clearSession();
        throw error;
      } finally {
        refreshPromise = null;
      }
    })();
    return refreshPromise;
  }

  async function initialize() {
    if (!configured()) return null;
    await completeCallback();
    session = readSession();
    if (session && Number(session.expires_at) <= Math.floor(Date.now() / 1000) + 60) {
      try { session = await refreshSession(); } catch (_) { session = null; }
    }
    return session;
  }

  async function accessToken(forceRefresh = false) {
    if (!configured()) return null;
    if (!session) session = readSession();
    if (!session) return null;
    if (forceRefresh || Number(session.expires_at) <= Math.floor(Date.now() / 1000) + 60) {
      session = await refreshSession();
    }
    return session && session.access_token;
  }

  async function signInWithGoogle() {
    if (!configured()) throw new Error('Supabase project configuration is missing.');
    const { verifier, challenge } = await createPkcePair();
    sessionStorage.setItem(verifierKey, verifier);
    const url = new URL(config.url.replace(/\/$/, '') + '/auth/v1/authorize');
    url.searchParams.set('provider', 'google');
    url.searchParams.set('redirect_to', location.origin + location.pathname);
    url.searchParams.set('code_challenge', challenge);
    url.searchParams.set('code_challenge_method', 's256');
    location.assign(url.toString());
  }

  async function signOut() {
    const token = await accessToken();
    try {
      if (token) {
        const response = await fetch(config.url.replace(/\/$/, '') + '/auth/v1/logout?scope=global', {
          method: 'POST',
          cache: 'no-store',
          headers: { apikey: config.publishableKey, Authorization: 'Bearer ' + token }
        });
        if (!response.ok) throw new Error('Supabase sign-out failed.');
      }
    } finally {
      clearSession();
    }
  }

  return {
    configured,
    initialize,
    accessToken,
    signInWithGoogle,
    signOut,
    getSession: () => session || readSession()
  };
})();
