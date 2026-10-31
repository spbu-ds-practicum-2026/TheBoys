// Раздел «Чаты»: список диалогов, окно переписки, поиск собеседника, отправка трека.
// Данные берёт из хранилища сессии и перерисовывается при каждом изменении.

import { api } from './api.js';
import { h, icon, formatDuration, formatTime, initials } from './dom.js';
import { openModal, closeModal } from './modal.js';

const STATUS_POLL_MS = 20000;
const SCROLL_LOAD_THRESHOLD_PX = 40;
const SEARCH_DEBOUNCE_MS = 250;

let session = null;
let unsubscribe = null;
let statusTimer = null;
let renderedConvId = null;
let renderedFirstSeq = null;

const $ = (id) => document.getElementById(id);

export function mountChats(activeSession) {
  unmountChats();
  session = activeSession;
  unsubscribe = session.store.onChange(render);

  $('messages').addEventListener('scroll', onScroll);
  $('composer').addEventListener('submit', onSubmit);

  render();
  startStatusPolling();
}

export function unmountChats() {
  if (unsubscribe) unsubscribe();
  unsubscribe = null;
  clearInterval(statusTimer);
  if (session) session.closeConversation();
  renderedConvId = null;
  renderedFirstSeq = null;
}

export function openDialog(id) {
  session.openConversation(id);
  startStatusPolling();
  $('composer')?.elements.text.focus();
}

export function closeChat() {
  session.closeConversation();
  render();
}

// ---------- отрисовка ----------

function render() {
  if (!$('chats-root')) return;
  renderDialogs();
  renderChat();
}

function renderDialogs() {
  const list = $('dialogs-list');
  const convs = session.store.visibleList(session.currentId);
  $('dialogs-empty').hidden = convs.length > 0;
  list.replaceChildren(...convs.map((conv) => dialogItem(conv)));
}

function dialogItem(conv) {
  const timeline = session.store.timeline(conv);
  return h('li', {}, h('button', {
    class: 'dialog-item', type: 'button', dataset: { action: 'open-dialog', id: conv.id },
    'aria-current': conv.id === session.currentId ? 'true' : null,
  },
  h('div', { class: 'avatar', 'aria-hidden': 'true', text: initials(conv.peer.login) }),
  h('div', { class: 'dialog-body' },
    h('div', { class: 'dialog-name', text: conv.peer.login }),
    h('div', { class: 'dialog-preview', text: preview(timeline.at(-1)) })),
  conv.unread > 0 ? h('span', { class: 'unread-badge', text: String(conv.unread), 'aria-label': `Непрочитанных: ${conv.unread}` }) : null));
}

function preview(item) {
  if (!item) return '';
  if (item.kind === 'track') return `♪ ${item.payload.title ?? 'трек'}`;
  return item.payload.text ?? '';
}

function renderChat() {
  const conv = session.store.get(session.currentId);
  $('chats-root').classList.toggle('has-open-chat', Boolean(conv));
  $('chat-placeholder').hidden = Boolean(conv);
  $('chat-active').hidden = !conv;
  if (!conv) { renderedConvId = null; return; }

  $('chat-avatar').textContent = initials(conv.peer.login);
  $('chat-title').textContent = conv.peer.login;
  renderMessages(conv);
}

function renderMessages(conv) {
  const box = $('messages');
  const opened = renderedConvId !== conv.id;
  const wasNearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
  const previousHeight = box.scrollHeight;
  const previousTop = box.scrollTop;

  const timeline = session.store.timeline(conv);
  const nodes = timeline.map(messageNode);
  if (conv.loaded && !conv.hasOlder) nodes.unshift(h('div', { class: 'msg-history-end', text: 'Начало переписки' }));
  box.replaceChildren(...nodes);

  const firstSeq = session.store.windowStart(conv);
  if (opened || wasNearBottom) {
    box.scrollTop = box.scrollHeight;
  } else if (renderedFirstSeq !== null && firstSeq < renderedFirstSeq) {
    // Подгрузили старые сообщения — остаёмся на том же месте.
    box.scrollTop = previousTop + (box.scrollHeight - previousHeight);
  }
  renderedConvId = conv.id;
  renderedFirstSeq = firstSeq;
}

function messageNode(item) {
  const meta = {
    sending: 'отправляется…',
    sent: formatTime(item.createdAt),
    failed: 'не отправлено',
    ok: formatTime(item.createdAt),
  }[item.state];
  return h('div', { class: `msg ${item.own ? 'out' : 'in'}${item.state === 'failed' ? ' is-failed' : ''}` },
    item.kind === 'track' ? trackCard(item.payload) : h('div', { class: 'msg-bubble', text: item.payload.text }),
    h('div', { class: 'msg-meta', text: meta }));
}

function trackCard(track) {
  return h('div', {
    class: 'track-card',
    dataset: { trackId: track.track_id, title: track.title, artist: track.artist, duration: track.duration_s },
  },
  h('button', { class: 'play-btn', type: 'button', dataset: { action: 'play-track' }, 'aria-label': `Воспроизвести ${track.title}` },
    icon('play'), icon('pause')),
  h('div', { class: 'track-meta' },
    h('div', { class: 'track-title', text: track.title }),
    h('div', { class: 'track-sub', text: `${track.artist} • ${formatDuration(track.duration_s)}` })));
}

// ---------- события ----------

function onScroll(event) {
  const conv = session.store.get(session.currentId);
  if (conv && event.target.scrollTop < SCROLL_LOAD_THRESHOLD_PX) session.loadOlder(conv);
}

function onSubmit(event) {
  event.preventDefault();
  const input = event.currentTarget.elements.text;
  const text = input.value.trim();
  if (!text || session.currentId === null) return;
  session.sendText(session.currentId, text);
  input.value = '';
}

// ---------- онлайн-статус собеседника ----------

function startStatusPolling() {
  clearInterval(statusTimer);
  refreshStatus();
  statusTimer = setInterval(refreshStatus, STATUS_POLL_MS);
}

async function refreshStatus() {
  const conv = session?.store.get(session.currentId);
  const el = $('chat-status');
  if (!conv || !el) return;
  try {
    const response = await api.userStatus(conv.peer.id);
    if (session.currentId !== conv.id) return;
    const online = response.ok && response.data.online;
    el.textContent = response.ok ? (online ? 'в сети' : 'не в сети') : '';
    el.classList.toggle('is-online', Boolean(online));
  } catch {
    el.textContent = '';
  }
}

// ---------- окна ----------

const SEARCH_ERRORS = {
  USER_NOT_FOUND: 'Пользователь не найден',
  INVALID_INPUT: 'Введите логин другого пользователя',
};
const SEARCH_FAILED = 'Не удалось выполнить поиск';

// Окно «Найти собеседника»: запрос уходит только по кнопке или Enter, поиска по мере ввода нет.
// Узел ищет логин целиком и сразу открывает диалог (ТР, технический сценарий 4, п. 1).
export function openUserSearch() {
  const input = h('input', {
    class: 'field', name: 'login', placeholder: 'Логин собеседника', 'aria-label': 'Логин собеседника',
    autocomplete: 'off', autocapitalize: 'none',
  });
  const submit = h('button', { class: 'btn btn-primary', type: 'submit', text: 'Найти' });
  const message = h('p', { class: 'form-error', role: 'alert' });
  const form = h('form', { class: 'user-search' }, h('div', { class: 'user-search-row' }, input, submit), message);

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    message.textContent = '';
    submit.disabled = true;
    const result = await session.openByLogin(input.value);
    submit.disabled = false;
    if (!result.ok) {
      message.textContent = SEARCH_ERRORS[result.code] ?? SEARCH_FAILED;
      return;
    }
    closeModal();
    openDialog(result.id);
  });

  openModal('Найти собеседника', form);
  input.focus();
}

export function openAttachTrack() {
  const conv = session.store.get(session.currentId);
  if (!conv) return;
  const input = h('input', { class: 'field', type: 'search', placeholder: 'Название или исполнитель', 'aria-label': 'Поиск треков', autocomplete: 'off' });
  const results = h('div', { class: 'track-list', 'aria-live': 'polite' });
  let timer = null;
  let token = 0;

  async function load() {
    const mine = ++token;
    let response;
    try { response = await api.tracks(input.value.trim()); } catch { response = null; }
    if (mine !== token) return;
    if (!response || !response.ok) {
      results.replaceChildren(h('p', { class: 'empty', text: 'Не удалось загрузить каталог' }));
    } else if (response.data.length === 0) {
      results.replaceChildren(h('p', { class: 'empty', text: 'Ничего не найдено' }));
    } else {
      results.replaceChildren(...response.data.map((track) => {
        const button = h('button', { class: 'pick-item', type: 'button' },
          h('div', { class: 'track-meta' },
            h('div', { class: 'track-title', text: track.title }),
            h('div', { class: 'track-sub', text: track.artist })));
        button.addEventListener('click', () => {
          session.sendTrack(conv.id, track);
          closeModal();
        });
        return button;
      }));
    }
  }

  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(load, SEARCH_DEBOUNCE_MS);
  });
  openModal(`Отправить трек: ${conv.peer.login}`, input, results);
  input.focus();
  load();
}
