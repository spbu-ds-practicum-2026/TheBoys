// Обёртки над REST API узла приложения. Формат ответов описан в services/app/README.md.

async function request(method, url, body) {
  const options = { method, credentials: 'same-origin', headers: {} };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const response = await fetch(url, options);
  let data = null;
  if (response.status !== 204) {
    try { data = await response.json(); } catch { data = null; }
  }
  return { status: response.status, ok: response.ok, data };
}

export const api = {
  register: (login, password) => request('POST', '/api/register', { login, password }),
  login: (login, password) => request('POST', '/api/login', { login, password }),
  logout: () => request('POST', '/api/logout'),
  tracks: (q = '') => request('GET', `/api/tracks?q=${encodeURIComponent(q)}`),
  users: (login) => request('GET', `/api/users?login=${encodeURIComponent(login)}`),
  userStatus: (id) => request('GET', `/api/users/${id}/status`),
  conversations: () => request('GET', '/api/conversations'),
  openConversation: (peerId) => request('POST', '/api/conversations', { peer_id: peerId }),
};
