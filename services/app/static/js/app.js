// Точка входа оболочки. Загружается один раз и не заменяется HTMX, поэтому сессия, соединение
// и плеер живут при переходах между разделами.

import { api } from './api.js';
import { Session } from './session.js';
import { Player } from './player.js';
import { initModal, closeModal } from './modal.js';
import { mountChats, unmountChats, openDialog, closeChat, openUserSearch, openAttachTrack } from './chat.js';
import { mountCatalog, openShare } from './catalog.js';

const root = document.getElementById('app');
const session = new Session(Number(root.dataset.userId));
const player = new Player();

initModal();
const BANNER_TEXT = {
  reconnecting: 'Переподключение…',
  rejected: 'Сервер отклонил подключение: адрес сайта не разрешён. Откройте сайт по разрешённому адресу.',
};
session.onState((state) => {
  const banner = document.getElementById('conn-banner');
  banner.hidden = !(state in BANNER_TEXT);
  if (!banner.hidden) banner.textContent = BANNER_TEXT[state];
});

function mountView() {
  if (document.getElementById('chats-root')) mountChats(session);
  else unmountChats();
  if (document.getElementById('catalog-root')) mountCatalog();
  markNav();
  markPlaying();
}

function markNav() {
  for (const link of document.querySelectorAll('[data-nav]')) {
    if (location.pathname === link.dataset.nav) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
}

// Подсвечивает строки каталога и карточки в чате, которые сейчас играют.
function markPlaying() {
  const playingId = player.playing ? player.track.id : null;
  for (const el of document.querySelectorAll('[data-track-id]')) {
    el.classList.toggle('is-playing', playingId !== null && el.dataset.trackId === playingId);
  }
}

function trackFrom(el) {
  const card = el.closest('[data-track-id]');
  return {
    id: card.dataset.trackId,
    title: card.dataset.title,
    artist: card.dataset.artist,
    duration_s: Number(card.dataset.duration),
  };
}

const actions = {
  'play-track': (el) => player.play(trackFrom(el)),
  'share-track': (el) => openShare(session, el.closest('[data-track-id]').dataset.trackId),
  'open-dialog': (el) => openDialog(Number(el.dataset.id)),
  'close-chat': () => closeChat(),
  'find-user': () => openUserSearch(),
  'attach-track': () => openAttachTrack(),
  'close-modal': () => closeModal(),
  logout: async () => {
    await api.logout();
    location.href = '/login';
  },
};

document.addEventListener('click', (event) => {
  const el = event.target.closest('[data-action]');
  if (el && actions[el.dataset.action]) actions[el.dataset.action](el);
});

player.onChange(markPlaying);
// Чат перерисовывает карточки при каждом изменении, поэтому отметку «играет» ставим после него.
session.store.onChange(() => queueMicrotask(markPlaying));

document.body.addEventListener('htmx:afterSwap', (event) => {
  if (event.detail.target.id === 'main') mountView();
});
document.body.addEventListener('htmx:historyRestore', mountView);

mountView();
session.start();
