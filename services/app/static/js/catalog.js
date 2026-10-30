// Раздел «Музыка»: каталог, поиск по названию и исполнителю, отправка трека в чат карточкой.
// Поиск выполняет сервер: GET /api/tracks?q=…

import { api } from './api.js';
import { h, icon, formatDuration } from './dom.js';
import { openModal, closeModal } from './modal.js';

const SEARCH_DEBOUNCE_MS = 250;

let timer = null;
let token = 0;
const tracksById = new Map();

const $ = (id) => document.getElementById(id);

export function mountCatalog() {
  const input = $('catalog-search');
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => load(input.value.trim()), SEARCH_DEBOUNCE_MS);
  });
  load(input.value.trim());
}

async function load(query) {
  const mine = ++token;
  let response;
  try { response = await api.tracks(query); } catch { response = null; }
  if (mine !== token || !$('catalog-list')) return;

  const empty = $('catalog-empty');
  if (!response || !response.ok) {
    $('catalog-list').replaceChildren();
    empty.textContent = 'Не удалось загрузить каталог';
    empty.hidden = false;
    return;
  }
  tracksById.clear();
  for (const track of response.data) tracksById.set(track.id, track);
  $('catalog-list').replaceChildren(...response.data.map(row));
  empty.textContent = query ? 'Ничего не найдено' : 'Каталог пуст';
  empty.hidden = response.data.length > 0;
}

function row(track) {
  return h('div', {
    class: 'track-row',
    dataset: { trackId: track.id, title: track.title, artist: track.artist, duration: track.duration_s },
  },
  h('button', { class: 'play-btn', type: 'button', dataset: { action: 'play-track' }, 'aria-label': `Воспроизвести ${track.title}` },
    icon('play'), icon('pause')),
  h('div', { class: 'track-meta' },
    h('div', { class: 'track-title', text: track.title }),
    h('div', { class: 'track-sub', text: `${track.artist} • ${formatDuration(track.duration_s)}` })),
  h('button', { class: 'btn', type: 'button', title: 'Отправить в чат', dataset: { action: 'share-track' } },
    icon('chat'), h('span', { class: 'btn-label', text: 'Отправить в чат' })));
}

// Выбор диалога для отправки карточки трека.
export function openShare(session, trackId) {
  const track = tracksById.get(trackId);
  if (!track) return;
  const convs = session.store.list();
  const body = convs.length === 0
    ? [h('p', { class: 'empty', text: 'Диалогов пока нет. Откройте диалог в разделе «Чаты».' })]
    : convs.map((conv) => {
      const button = h('button', { class: 'pick-item', type: 'button' },
        h('div', { class: 'avatar avatar-sm', 'aria-hidden': 'true', text: conv.peer.login.slice(0, 2) }),
        h('span', { text: conv.peer.login }));
      button.addEventListener('click', () => {
        session.sendTrack(conv.id, track);
        closeModal();
      });
      return button;
    });
  openModal(`Отправить «${track.title}»`, ...body);
}
