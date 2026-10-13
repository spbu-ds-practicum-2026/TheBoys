/**
 * Boysic Messenger — Spatial Island UI & Real Interactive Logic
 */

// In-Memory Chat State & Mock Database
const CHATS_STORE = {
  1: {
    id: 1,
    name: 'Алиса Смирнова',
    status: 'online',
    statusText: 'в сети (узел app-2)',
    avatarText: 'АС',
    avatarBg: 'var(--gradient-sunset)',
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
    avatarBg: '#1c1c24',
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
        text: 'Слушай, а трек синхронизируется между окнами?',
        time: '19:30'
      },
      {
        id: 'msg-2-3',
        sender: 'outgoing',
        type: 'text',
        text: 'Да! Плеер вынесен в независимый глобальный компонент, поэтому музыка играет непрерывно при любых переходах.',
        time: '19:32',
        delivered: true
      }
    ]
  },
  3: {
    id: 3,
    name: 'Павел Григорьев',
    status: 'offline',
    statusText: 'был(а) в сети 45 мин назад',
    avatarText: 'ПГ',
    avatarBg: '#141418',
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
        text: 'Схему БД зафиксировал, отправляю в репо',
        time: '18:12'
      },
      {
        id: 'msg-3-3',
        sender: 'outgoing',
        type: 'text',
        text: 'Отлично! Тогда монотонный seq для каждого диалога генерируем строго в транзакции.',
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
    avatarBg: '#201a18',
    listening: 'Neon Sunset',
    messages: [
      {
        id: 'msg-4-1',
        sender: 'incoming',
        type: 'text',
        text: 'Docker Compose стенд поднят и работает! Nginx балансирует трафик между app-1 и app-2.',
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
        text: 'Запустил тест Т-1 на доставку сообщения на чужой узел — прошло за 0.3 секунды.',
        time: '17:55'
      }
    ]
  }
};

let currentActiveChatId = 1;
let isCurrentTrackPlaying = false;

// 1. Navigation Tab Switching (Диалоги vs Параметры)
function switchNavTab(tabName) {
  const btnChats = document.getElementById('btn-tab-chats');
  const btnSettings = document.getElementById('btn-tab-settings');
  const viewChats = document.getElementById('view-chats');
  const viewSettings = document.getElementById('view-settings');

  if (!btnChats || !btnSettings || !viewChats || !viewSettings) return;

  if (tabName === 'chats') {
    btnChats.classList.add('active');
    btnSettings.classList.remove('active');
    viewChats.style.display = 'flex';
    viewSettings.style.display = 'none';
  } else if (tabName === 'settings') {
    btnSettings.classList.add('active');
    btnChats.classList.remove('active');
    viewChats.style.display = 'none';
    viewSettings.style.display = 'flex';
  }
}

// 2. Chat Switching & Dynamic Rendering
function selectSpatialDialog(element, userName, status, initials) {
  const chatId = parseInt(element.getAttribute('data-chat-id'), 10);
  if (!chatId || !CHATS_STORE[chatId]) return;

  currentActiveChatId = chatId;
  const chatData = CHATS_STORE[chatId];

  // Update active style in left deck
  document.querySelectorAll('.deck-item').forEach(item => item.classList.remove('active'));
  element.classList.add('active');

  // Clear unread badge on click
  const badge = element.querySelector('.deck-item-badge');
  if (badge) {
    badge.remove();
    updateUnreadCounterBadge();
  }

  // Render recipient header
  renderChatHeader(chatData);

  // Render conversation messages
  renderChatMessages(chatData);

  // Update input placeholder
  const input = document.getElementById('composer-input');
  if (input) {
    input.placeholder = `Написать сообщение ${chatData.name.split(' ')[0]}...`;
    input.focus();
  }
}

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

  // Clear flow
  flow.innerHTML = '';

  // Timeline pill
  const timelinePill = document.createElement('div');
  timelinePill.className = 'chat-timeline-pill';
  timelinePill.textContent = 'Сегодня';
  flow.appendChild(timelinePill);

  // Append each message from store
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

  // Typing indicator if online
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

  // Scroll to bottom
  flow.scrollTop = flow.scrollHeight;
}

// 3. Send Message
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

  // Add to store
  chat.messages.push(newMsg);

  // Append to DOM
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

  // Update preview & time in left deck list
  const activeDeckItem = document.querySelector(`.deck-item[data-chat-id="${chat.id}"]`);
  if (activeDeckItem) {
    const previewEl = activeDeckItem.querySelector('.deck-item-preview');
    const timeEl = activeDeckItem.querySelector('.deck-item-time');
    if (previewEl) previewEl.textContent = text;
    if (timeEl) timeEl.textContent = timeStr;
  }
}

// 4. Quick Filter Chips
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

// Helper: Update total unread badge in top navbar
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

// 5. Sound Module Playback Demo
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

// 6. Settings Toggles (Physics & Lens)
function toggleSpatialBlur(checkbox) {
  const root = document.documentElement;
  if (checkbox.checked) {
    root.style.setProperty('--glass-blur', 'blur(28px) saturate(170%)');
    root.style.setProperty('--glass-blur-deep', 'blur(36px) saturate(190%)');
  } else {
    root.style.setProperty('--glass-blur', 'blur(0px) saturate(100%)');
    root.style.setProperty('--glass-blur-deep', 'blur(0px) saturate(100%)');
  }
}

function toggleSpatialLens(checkbox) {
  const lens = document.querySelector('.ambient-peach-lens');
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

// Initial Boot
document.addEventListener('DOMContentLoaded', () => {
  const flow = document.getElementById('spatial-messages-flow');
  if (flow) {
    flow.scrollTop = flow.scrollHeight;
  }
});
