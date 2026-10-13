/**
 * Boysic Messenger — Ultra-Transparent Liquid Glass & Interactive Engine
 */

// Global State Store
const CHATS_STORE = {
  1: {
    id: 1,
    name: 'Алиса Смирнова',
    status: 'online',
    statusText: 'в сети (узел app-2)',
    avatarText: 'АС',
    avatarBg: 'var(--gradient-ice-accent)',
    listening: 'Midnight Echoes',
    messages: [
      {
        id: 'msg-1-1',
        sender: 'incoming',
        type: 'text',
        text: 'Привет! Послушай новый трек — он только что отреплицировался на storage-2 и доступен для стриминга.',
        time: '19:40'
      },
      {
        id: 'msg-1-2',
        sender: 'incoming',
        type: 'track',
        track: {
          title: 'Midnight Echoes',
          artist: 'The Boys Band',
          duration: '3:42'
        },
        time: '19:41'
      },
      {
        id: 'msg-1-3',
        sender: 'outgoing',
        type: 'text',
        text: 'Звук отличный! Плеер играет прямо из карточки, и воспроизведение не прерывается.',
        time: '19:42',
        delivered: true
      },
      {
        id: 'msg-1-4',
        sender: 'outgoing',
        type: 'text',
        text: 'Межузловая пересылка через POST /internal/deliver отработала за 18 миллисекунд.',
        time: '19:43',
        delivered: true
      }
    ]
  },
  2: {
    id: 2,
    name: 'Олег Иванов',
    status: 'online',
    statusText: 'в сети (узел app-1)',
    avatarText: 'ОИ',
    avatarBg: '#141824',
    listening: null,
    messages: [
      {
        id: 'msg-2-1',
        sender: 'incoming',
        type: 'text',
        text: 'Привет, Дмитрий! Я заканчиваю верстку экранов каталога музыки.',
        time: '19:28'
      },
      {
        id: 'msg-2-2',
        sender: 'incoming',
        type: 'text',
        text: 'Слушай, а трек синхронизируется между вкладками?',
        time: '19:30'
      },
      {
        id: 'msg-2-3',
        sender: 'outgoing',
        type: 'text',
        text: 'Да! Плеер вынесен в независимый глобальный модуль и играет бесшовно через общий аудио-движок.',
        time: '19:32',
        delivered: true
      },
      {
        id: 'msg-2-4',
        sender: 'incoming',
        type: 'text',
        text: 'Супер, проверяю адаптивность интерфейса на экранах разной ширины 👍',
        time: '19:34'
      }
    ]
  },
  3: {
    id: 3,
    name: 'Павел Григорьев',
    status: 'offline',
    statusText: 'был(а) в сети 45 мин назад',
    avatarText: 'ПГ',
    avatarBg: '#10141e',
    listening: null,
    messages: [
      {
        id: 'msg-3-1',
        sender: 'incoming',
        type: 'text',
        text: 'Привет! Схему БД зафиксировал: conversations, messages, sessions, replicas.',
        time: '18:10'
      },
      {
        id: 'msg-3-2',
        sender: 'incoming',
        type: 'text',
        text: 'Поле direct_key = min_id:max_id для личных диалогов, и монотонный seq.',
        time: '18:12'
      },
      {
        id: 'msg-3-3',
        sender: 'outgoing',
        type: 'text',
        text: 'Отлично! Тогда seq генерируем строго в транзакции диалога для защиты от гонок.',
        time: '18:15',
        delivered: true
      }
    ]
  },
  4: {
    id: 4,
    name: 'Артём Еременко',
    status: 'online',
    statusText: 'в сети (узел app-1)',
    avatarText: 'АЕ',
    avatarBg: '#121c2a',
    listening: 'Neon Sunset Drive',
    messages: [
      {
        id: 'msg-4-1',
        sender: 'incoming',
        type: 'text',
        text: 'Docker Compose стенд поднят! Nginx балансирует трафик между app-1 и app-2.',
        time: '17:50'
      },
      {
        id: 'msg-4-2',
        sender: 'incoming',
        type: 'track',
        track: {
          title: 'Neon Sunset Drive',
          artist: 'Synthesia Core',
          duration: '4:15'
        },
        time: '17:52'
      },
      {
        id: 'msg-4-3',
        sender: 'incoming',
        type: 'text',
        text: 'Запустил сценарий Т-1 на доставку сообщения на другой узел — уложились в 300 мс!',
        time: '17:55'
      }
    ]
  }
};

let currentActiveChatId = 1;
let isCurrentTrackPlaying = false;

// 1. Navigation Tab Switching (Плеер, Чаты, Импорт, Параметры)
function switchNavTab(tabName) {
  const tabs = ['player', 'chats', 'import', 'settings'];
  
  tabs.forEach(name => {
    const btn = document.getElementById(`btn-tab-${name}`);
    const view = document.getElementById(`view-${name}`);

    if (name === tabName) {
      if (btn) btn.classList.add('active');
      if (view) view.style.display = 'flex';
    } else {
      if (btn) btn.classList.remove('active');
      if (view) view.style.display = 'none';
    }
  });

  // If opening chats, ensure active chat is focused and scrolled
  if (tabName === 'chats') {
    const flow = document.getElementById('spatial-messages-flow');
    if (flow) flow.scrollTop = flow.scrollHeight;
  }
}

// Interactive helper for player console placeholder
let isConsolePlaying = false;
function toggleConsolePlay(button) {
  const vinyl = document.querySelector('.turntable-vinyl');
  const svg = button.querySelector('svg');
  isConsolePlaying = !isConsolePlaying;

  if (isConsolePlaying) {
    if (vinyl) vinyl.style.animationPlayState = 'running';
    button.style.boxShadow = '0 0 24px rgba(56, 189, 248, 0.8)';
    svg.innerHTML = `
      <rect x="6" y="4" width="4" height="16" fill="currentColor"></rect>
      <rect x="14" y="4" width="4" height="16" fill="currentColor"></rect>
    `;
  } else {
    if (vinyl) vinyl.style.animationPlayState = 'paused';
    button.style.boxShadow = 'var(--shadow-ice-glow)';
    svg.innerHTML = `
      <polygon points="5 3 19 12 5 21 5 3"></polygon>
    `;
  }
}

// Interactive helper for import dropzone placeholder
function simulateFileUpload() {
  const textEl = document.querySelector('.import-drop-text');
  const origText = textEl ? textEl.textContent : '';
  if (textEl) {
    textEl.textContent = '⏳ Файл выбран: track_demo_320kbps.mp3 (запуск извлечения тегов mutagen)...';
    textEl.style.color = 'var(--slate-ice-light)';
    setTimeout(() => {
      textEl.textContent = '✅ Теги извлечены: "Midnight Echoes — The Boys Band" (готово к репликации)';
      setTimeout(() => {
        textEl.textContent = origText;
        textEl.style.color = 'var(--text-pure)';
      }, 3500);
    }, 1500);
  }
}

// 2. Guaranteed Chat Switching Function
function selectChat(chatId) {
  const targetId = parseInt(chatId, 10);
  if (!targetId || !CHATS_STORE[targetId]) return;

  currentActiveChatId = targetId;
  const chatData = CHATS_STORE[targetId];

  // Update .active class on the list items
  document.querySelectorAll('.deck-item').forEach(item => {
    const itemChatId = parseInt(item.getAttribute('data-chat-id'), 10);
    if (itemChatId === targetId) {
      item.classList.add('active');
      // Clear unread badge
      const badge = item.querySelector('.deck-item-badge');
      if (badge) {
        badge.remove();
        updateUnreadCounterBadge();
      }
    } else {
      item.classList.remove('active');
    }
  });

  // Re-render chat header
  renderChatHeader(chatData);

  // Re-render chat messages
  renderChatMessages(chatData);

  // Update composer input placeholder
  const input = document.getElementById('composer-input');
  if (input) {
    const firstName = chatData.name.split(' ')[0];
    input.placeholder = `Написать сообщение ${firstName}...`;
    input.focus();
  }
}

// Legacy alias to support any remaining onclick references
window.selectSpatialDialog = function(element, userName, status, initials) {
  const chatId = element ? element.getAttribute('data-chat-id') : null;
  if (chatId) {
    selectChat(chatId);
  }
};
window.selectChat = selectChat;

// Helper: Render Chat Header
function renderChatHeader(chat) {
  const nameEl = document.getElementById('active-recipient-name');
  const statusEl = document.getElementById('active-recipient-status');
  const avatarEl = document.getElementById('active-recipient-avatar');
  const listeningEl = document.querySelector('.listening-ticker');

  if (nameEl) nameEl.textContent = chat.name;
  if (avatarEl) {
    avatarEl.textContent = chat.avatarText;
    avatarEl.style.background = chat.avatarBg;
  }

  if (statusEl) {
    if (chat.status === 'online') {
      statusEl.className = 'chat-recipient-status online';
      statusEl.innerHTML = `<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:currentColor;"></span> ${chat.statusText}`;
    } else {
      statusEl.className = 'chat-recipient-status';
      statusEl.textContent = chat.statusText;
    }
  }

  if (listeningEl) {
    if (chat.listening) {
      listeningEl.style.display = 'inline-flex';
      const titleSpan = listeningEl.querySelector('span');
      if (titleSpan) titleSpan.textContent = chat.listening;
    } else {
      listeningEl.style.display = 'none';
    }
  }
}

// Helper: Render Messages Stream Flow
function renderChatMessages(chat) {
  const flow = document.getElementById('spatial-messages-flow');
  if (!flow) return;

  // Clear messages container
  flow.innerHTML = '';

  // Timeline pill
  const timelinePill = document.createElement('div');
  timelinePill.className = 'chat-timeline-pill';
  timelinePill.textContent = 'Сегодня';
  flow.appendChild(timelinePill);

  // Render all messages in sequence
  chat.messages.forEach(msg => {
    const row = document.createElement('div');
    row.className = `msg-row ${msg.sender}`;

    if (msg.type === 'track') {
      row.innerHTML = `
        <div class="msg-bubble" style="padding: 5px;">
          <div class="sound-module-card" id="sound-module-${msg.id}">
            <div class="sound-module-vinyl">
              <div class="vinyl-center"></div>
            </div>
            <div class="sound-module-info">
              <div class="sound-module-title">${escapeHtml(msg.track.title)}</div>
              <div class="sound-module-artist">${escapeHtml(msg.track.artist)} • ${escapeHtml(msg.track.duration)}</div>
              <div class="sound-waveform">
                <div class="wave-bar"></div>
                <div class="wave-bar"></div>
                <div class="wave-bar"></div>
                <div class="wave-bar"></div>
                <div class="wave-bar"></div>
                <div class="wave-bar"></div>
              </div>
            </div>
            <button class="sound-play-orb" onclick="toggleSpatialTrack(this)" title="Слушать трек">
              <svg viewBox="0 0 24 24">
                <polygon points="5 3 19 12 5 21 5 3"></polygon>
              </svg>
            </button>
          </div>
          <div class="msg-meta" style="padding: 2px 10px 4px 0;">
            <span>${msg.time}</span>
          </div>
        </div>
      `;
    } else {
      const checkMarkSvg = msg.delivered ? `
        <svg class="msg-status-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6">
          <path d="M18 6L7 17l-5-5"></path>
          <path d="M22 10l-7.5 7.5L13 16"></path>
        </svg>
      ` : '';

      row.innerHTML = `
        <div class="msg-bubble">
          ${escapeHtml(msg.text)}
          <div class="msg-meta">
            <span>${msg.time}</span>
            ${checkMarkSvg}
          </div>
        </div>
      `;
    }

    flow.appendChild(row);
  });

  // Typing indicator if recipient is currently online
  if (chat.status === 'online') {
    const typing = document.createElement('div');
    typing.className = 'typing-capsule';
    typing.id = 'spatial-typing-bubble';
    typing.title = `${chat.name} печатает...`;
    typing.innerHTML = `
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
    `;
    flow.appendChild(typing);
  }

  // Smooth scroll to bottom
  flow.scrollTop = flow.scrollHeight;
}

// 3. Send Message Handler
function handleSendSpatialMessage(event) {
  event.preventDefault();
  const input = document.getElementById('composer-input');
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;

  const chat = CHATS_STORE[currentActiveChatId];
  if (!chat) return;

  const now = new Date();
  const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

  const newMsg = {
    id: `msg-${chat.id}-${Date.now()}`,
    sender: 'outgoing',
    type: 'text',
    text: text,
    time: timeStr,
    delivered: true
  };

  // Push to local store
  chat.messages.push(newMsg);

  // Append to current stream
  const flow = document.getElementById('spatial-messages-flow');
  const typingBubble = document.getElementById('spatial-typing-bubble');

  const row = document.createElement('div');
  row.className = 'msg-row outgoing';
  row.innerHTML = `
    <div class="msg-bubble">
      ${escapeHtml(text)}
      <div class="msg-meta">
        <span>${timeStr}</span>
        <svg class="msg-status-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6">
          <path d="M18 6L7 17l-5-5"></path>
          <path d="M22 10l-7.5 7.5L13 16"></path>
        </svg>
      </div>
    </div>
  `;

  if (typingBubble) {
    flow.insertBefore(row, typingBubble);
  } else {
    flow.appendChild(row);
  }

  input.value = '';
  flow.scrollTop = flow.scrollHeight;

  // Update preview & time in left deck
  const activeDeckItem = document.querySelector(`.deck-item[data-chat-id="${chat.id}"]`);
  if (activeDeckItem) {
    const previewEl = activeDeckItem.querySelector('.deck-item-preview');
    const timeEl = activeDeckItem.querySelector('.deck-item-time');
    if (previewEl) previewEl.textContent = text;
    if (timeEl) timeEl.textContent = timeStr;
  }
}

// 4. Search Filter
function handleSearchDialogs(query) {
  const term = (query || '').toLowerCase().trim();
  const items = document.querySelectorAll('.deck-item');

  items.forEach(item => {
    const name = item.querySelector('.deck-item-name')?.textContent.toLowerCase() || '';
    const preview = item.querySelector('.deck-item-preview')?.textContent.toLowerCase() || '';
    if (!term || name.includes(term) || preview.includes(term)) {
      item.style.display = 'flex';
    } else {
      item.style.display = 'none';
    }
  });
}

// 5. Quick Filter Chips
function filterDialogs(btn, filterType) {
  document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');

  const items = document.querySelectorAll('.deck-item');
  items.forEach(item => {
    const chatId = parseInt(item.getAttribute('data-chat-id'), 10);
    const chat = CHATS_STORE[chatId];
    if (!chat) return;

    if (filterType === 'all') {
      item.style.display = 'flex';
    } else if (filterType === 'tracks') {
      const hasTrack = chat.messages.some(m => m.type === 'track') || !!chat.listening;
      item.style.display = hasTrack ? 'flex' : 'none';
    } else if (filterType === 'unread') {
      const hasBadge = !!item.querySelector('.deck-item-badge');
      item.style.display = hasBadge ? 'flex' : 'none';
    }
  });
}

// Helper: Recalculate Total Unread Badge in Top Island
function updateUnreadCounterBadge() {
  const badges = document.querySelectorAll('.deck-item-badge');
  let total = 0;
  badges.forEach(b => {
    total += parseInt(b.textContent, 10) || 1;
  });

  const segmentCounter = document.querySelector('.segment-counter');
  if (segmentCounter) {
    if (total > 0) {
      segmentCounter.style.display = 'inline-block';
      segmentCounter.textContent = total;
    } else {
      segmentCounter.style.display = 'none';
    }
  }
}

// 6. Sound Module Playback Demo
function toggleSpatialTrack(button) {
  const card = button.closest('.sound-module-card') || document.getElementById('demo-sound-module');
  if (!card) return;
  const playIcon = button.querySelector('svg');
  isCurrentTrackPlaying = !isCurrentTrackPlaying;

  if (isCurrentTrackPlaying) {
    card.classList.add('playing');
    playIcon.innerHTML = `
      <rect x="6" y="4" width="4" height="16" fill="currentColor"></rect>
      <rect x="14" y="4" width="4" height="16" fill="currentColor"></rect>
    `;
  } else {
    card.classList.remove('playing');
    playIcon.innerHTML = `
      <polygon points="5 3 19 12 5 21 5 3" fill="currentColor"></polygon>
    `;
  }
}

// 7. Settings Toggles (Physics & Lens)
function toggleSpatialBlur(checkbox) {
  const root = document.documentElement;
  if (checkbox.checked) {
    root.style.setProperty('--glass-blur-deep', 'blur(32px) saturate(200%)');
  } else {
    root.style.setProperty('--glass-blur-deep', 'blur(0px) saturate(100%)');
  }
}

function toggleSpatialLens(checkbox) {
  const lens = document.querySelector('.ambient-ice-lens');
  if (lens) {
    lens.style.display = checkbox.checked ? 'block' : 'none';
  }
}

function escapeHtml(string) {
  const entityMap = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  };
  return String(string).replace(/[&<>"']/g, s => entityMap[s]);
}

// Initial Boot: Set Alice (Chat 1) as active on page load
document.addEventListener('DOMContentLoaded', () => {
  selectChat(1);
});
