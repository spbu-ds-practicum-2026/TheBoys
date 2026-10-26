/**
 * Boysic Messenger — Discord & Telegram Dark Hybrid (Typewriter Edition)
 * Features: Typewriter Streaming, Functional Paperclip Attachments, File Import Pipeline
 */

// Global State Store (Pure Messages & Documents, No Track Module Clutter)
const CHATS_STORE = {
  1: {
    id: 1,
    name: 'Алиса Смирнова',
    status: 'online',
    statusText: 'в сети [узел app-2]',
    avatarText: 'АС',
    avatarBg: 'var(--avatar-orange-gradient)',
    messages: [
      {
        id: 'msg-1-1',
        sender: 'incoming',
        type: 'text',
        text: 'Привет! Полнотекстовый поиск и хранилище файлов готовы к работе.',
        time: '19:40'
      },
      {
        id: 'msg-1-2',
        sender: 'incoming',
        type: 'text',
        text: 'Проверила доставку через межузловой протокол POST /internal/deliver — все события приходят строго по порядку sequence без дублей.',
        time: '19:41'
      },
      {
        id: 'msg-1-3',
        sender: 'outgoing',
        type: 'text',
        text: 'Отлично! Теперь через скрепку можно прикреплять любые файлы, а в разделе импорта загружать треки с предпросмотром.',
        time: '19:42',
        delivered: true
      },
      {
        id: 'msg-1-4',
        sender: 'outgoing',
        type: 'text',
        text: 'Печатная машинка активна: monospace-набор с тактильным откликом и живым курсором.',
        time: '19:43',
        delivered: true
      }
    ]
  },
  2: {
    id: 2,
    name: 'Олег Иванов',
    status: 'online',
    statusText: 'в сети [узел app-1]',
    avatarText: 'ОИ',
    avatarBg: 'var(--avatar-orange-gradient)',
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
        text: 'Слушай, а вложения теперь отправляются через скрепку?',
        time: '19:30'
      },
      {
        id: 'msg-2-3',
        sender: 'outgoing',
        type: 'text',
        text: 'Да! Добавил полноценный выбор файлов с превью в поле ввода и отправкой прямо в поток сообщений.',
        time: '19:32',
        delivered: true
      },
      {
        id: 'msg-2-4',
        sender: 'incoming',
        type: 'text',
        text: 'Супер, проверяю отправку картинок и MP3 треков 👍',
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
    avatarBg: 'var(--avatar-orange-gradient)',
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
    statusText: 'в сети [узел app-1]',
    avatarText: 'АЕ',
    avatarBg: 'var(--avatar-orange-gradient)',
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
        type: 'text',
        text: 'Контейнеры реплицируют сообщения и файлы в реальном времени.',
        time: '17:52'
      }
    ]
  }
};

let currentActiveChatId = 1;
let currentAttachments = [];

// ============================================================================
// 1. Navigation Tab Switching (Плеер, Чаты, Импорт, Параметры)
// ============================================================================
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

  if (tabName === 'chats') {
    const flow = document.getElementById('spatial-messages-flow');
    if (flow) flow.scrollTop = flow.scrollHeight;
  }
}

// ============================================================================
// 2. Select & Render Chat
// ============================================================================
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
    } else {
      item.classList.remove('active');
    }
  });

  // Re-render chat header
  renderChatHeader(chatData);

  // Re-render chat messages
  renderChatMessages(chatData);

  // Update composer input placeholder with Typewriter Feel
  const input = document.getElementById('composer-input');
  if (input) {
    const firstName = chatData.name.split(' ')[0];
    input.placeholder = `Написать сообщение ${firstName}...`;
    input.focus();
  }

  // On compact viewports, auto-collapse drawer when user picks a chat
  if (window.innerWidth <= 860 && typeof isDrawerOpen !== 'undefined' && isDrawerOpen) {
    toggleDialogsDrawer(false);
  }
}
window.selectChat = selectChat;

// Helper: Render Chat Header
function renderChatHeader(chat) {
  const nameEl = document.getElementById('active-recipient-name');
  const statusEl = document.getElementById('active-recipient-status');
  const avatarEl = document.getElementById('active-recipient-avatar');

  if (nameEl) nameEl.textContent = chat.name;
  if (avatarEl) {
    avatarEl.textContent = chat.avatarText;
    avatarEl.style.background = 'var(--avatar-orange-gradient)';
    avatarEl.style.color = '#000000';
    avatarEl.style.fontWeight = '800';
  }

  if (statusEl) {
    if (chat.status === 'online') {
      statusEl.className = 'chat-recipient-status online';
      statusEl.innerHTML = `
        <span class="recipient-presence-dot"></span>
        <span>в сети [узел app-2]</span>
      `;
    } else {
      statusEl.className = 'chat-recipient-status';
      statusEl.innerHTML = `
        <span class="recipient-presence-dot" style="background:#64748b; box-shadow:none;"></span>
        <span>${escapeHtml(chat.statusText)}</span>
      `;
    }
  }
}

// Helper: Format File Size
function formatFileSize(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// Helper: Render Chat Messages (Clean Typewriter Stream + Attachment Cards)
function renderChatMessages(chat) {
  const flow = document.getElementById('spatial-messages-flow');
  if (!flow) return;

  flow.innerHTML = '';

  // Typewriter Timeline Pill
  const timelinePill = document.createElement('div');
  timelinePill.className = 'chat-timeline-pill typewriter-pill';
  timelinePill.textContent = '[ -- 2026-10-26 // LOG STREAM -- ]';
  flow.appendChild(timelinePill);

  // Render all messages in sequence
  chat.messages.forEach(msg => {
    const row = document.createElement('div');
    row.className = `msg-row ${msg.sender}`;

    const checkMarkSvg = msg.delivered ? `
      <svg class="msg-status-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6">
        <path d="M18 6L7 17l-5-5"></path>
        <path d="M22 10l-7.5 7.5L13 16"></path>
      </svg>
    ` : '';

    const authorTag = msg.sender === 'incoming' ? `<span class="msg-author-tag">@${chat.name.split(' ')[0].toLowerCase()}</span>` : '';

    // Render attachments if any
    let attachmentsHtml = '';
    if (msg.attachments && msg.attachments.length > 0) {
      msg.attachments.forEach(att => {
        if (att.isImage && att.dataUrl) {
          attachmentsHtml += `<img src="${att.dataUrl}" alt="${escapeHtml(att.name)}" class="msg-image-attachment">`;
        } else {
          attachmentsHtml += `
            <div class="msg-file-attachment">
              <span class="file-icon">📄</span>
              <div class="file-meta">
                <span class="file-name">${escapeHtml(att.name)}</span>
                <span class="file-size">${escapeHtml(att.sizeStr || '')}</span>
              </div>
              <span class="file-dl-btn">⬇</span>
            </div>
          `;
        }
      });
    }

    row.innerHTML = `
      <div class="msg-bubble typewriter-bubble">
        ${authorTag}
        <div class="msg-text-content">${escapeHtml(msg.text || '')}</div>
        ${attachmentsHtml}
        <div class="msg-meta">
          <span>${msg.time}</span>
          ${checkMarkSvg}
        </div>
      </div>
    `;

    flow.appendChild(row);
  });

  // Typing indicator
  if (chat.status === 'online') {
    const typing = document.createElement('div');
    typing.className = 'typing-capsule';
    typing.id = 'chat-typing-capsule';
    typing.innerHTML = `
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
      <span class="typing-label typewriter-font">${chat.name.split(' ')[0].toLowerCase()} печатает...</span>
    `;
    flow.appendChild(typing);
  }

  flow.scrollTop = flow.scrollHeight;
}

// ============================================================================
// 3. Functional Paperclip & File Attachments
// ============================================================================
function triggerComposerAttach() {
  const fileInput = document.getElementById('composer-file-input');
  if (fileInput) {
    fileInput.click();
  }
}
window.triggerComposerAttach = triggerComposerAttach;

function handleComposerFileSelected(event) {
  const files = event.target.files;
  if (!files || files.length === 0) return;

  Array.from(files).forEach(file => {
    const isImage = file.type.startsWith('image/');
    const attObj = {
      name: file.name,
      sizeStr: formatFileSize(file.size),
      isImage: isImage,
      dataUrl: null
    };

    if (isImage) {
      const reader = new FileReader();
      reader.onload = (e) => {
        attObj.dataUrl = e.target.result;
        renderComposerAttachmentChips();
      };
      reader.readAsDataURL(file);
    }

    currentAttachments.push(attObj);
  });

  renderComposerAttachmentChips();
  event.target.value = '';
}
window.handleComposerFileSelected = handleComposerFileSelected;

function renderComposerAttachmentChips() {
  const bar = document.getElementById('composer-attachments-bar');
  const list = document.getElementById('attachment-chips-list');
  if (!bar || !list) return;

  if (currentAttachments.length === 0) {
    bar.style.display = 'none';
    list.innerHTML = '';
    return;
  }

  bar.style.display = 'flex';
  list.innerHTML = '';

  currentAttachments.forEach((att, index) => {
    const chip = document.createElement('div');
    chip.className = 'attachment-chip';
    const icon = att.isImage ? '🖼️' : '📎';
    chip.innerHTML = `
      <span>${icon} ${escapeHtml(att.name)} (${att.sizeStr})</span>
      <span class="attachment-chip-remove" onclick="removeComposerAttachment(${index})">✕</span>
    `;
    list.appendChild(chip);
  });
}

function removeComposerAttachment(index) {
  if (index >= 0 && index < currentAttachments.length) {
    currentAttachments.splice(index, 1);
    renderComposerAttachmentChips();
  }
}
window.removeComposerAttachment = removeComposerAttachment;

// ============================================================================
// 4. Send Message with Typewriter Streaming Effect
// ============================================================================
function handleSendSpatialMessage(event) {
  if (event && event.preventDefault) event.preventDefault();
  const input = document.getElementById('composer-input');
  if (!input) return;

  const text = input.value.trim();
  if (!text && currentAttachments.length === 0) return;

  const chat = CHATS_STORE[currentActiveChatId];
  if (!chat) return;

  const now = new Date();
  const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

  const messageAttachments = [...currentAttachments];
  currentAttachments = [];
  renderComposerAttachmentChips();

  const newMsg = {
    id: `msg-${chat.id}-${Date.now()}`,
    sender: 'outgoing',
    type: 'text',
    text: text,
    attachments: messageAttachments,
    time: timeStr,
    delivered: true
  };

  chat.messages.push(newMsg);

  const flow = document.getElementById('spatial-messages-flow');
  const typingCapsule = document.getElementById('chat-typing-capsule');

  // Render Outgoing Message
  let attachmentsHtml = '';
  if (messageAttachments.length > 0) {
    messageAttachments.forEach(att => {
      if (att.isImage && att.dataUrl) {
        attachmentsHtml += `<img src="${att.dataUrl}" alt="${escapeHtml(att.name)}" class="msg-image-attachment">`;
      } else {
        attachmentsHtml += `
          <div class="msg-file-attachment">
            <span class="file-icon">📄</span>
            <div class="file-meta">
              <span class="file-name">${escapeHtml(att.name)}</span>
              <span class="file-size">${escapeHtml(att.sizeStr || '')}</span>
            </div>
            <span class="file-dl-btn">⬇</span>
          </div>
        `;
      }
    });
  }

  const row = document.createElement('div');
  row.className = 'msg-row outgoing';
  row.innerHTML = `
    <div class="msg-bubble typewriter-bubble">
      <div class="msg-text-content">${escapeHtml(text)}</div>
      ${attachmentsHtml}
      <div class="msg-meta">
        <span>${timeStr}</span>
        <svg class="msg-status-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6">
          <path d="M18 6L7 17l-5-5"></path>
          <path d="M22 10l-7.5 7.5L13 16"></path>
        </svg>
      </div>
    </div>
  `;

  if (typingCapsule) {
    flow.insertBefore(row, typingCapsule);
  } else {
    flow.appendChild(row);
  }

  input.value = '';
  flow.scrollTop = flow.scrollHeight;

  // Update preview in dialogs list
  const activeDeckItem = document.querySelector(`.deck-item[data-chat-id="${chat.id}"]`);
  if (activeDeckItem) {
    const previewEl = activeDeckItem.querySelector('.deck-item-preview');
    const timeEl = activeDeckItem.querySelector('.deck-item-time');
    if (previewEl) previewEl.textContent = text || (messageAttachments[0] ? `📎 ${messageAttachments[0].name}` : '');
    if (timeEl) timeEl.textContent = timeStr;
  }

  // Typewriter simulated response if chat is online
  if (chat.status === 'online') {
    if (typingCapsule) typingCapsule.style.display = 'inline-flex';

    setTimeout(() => {
      if (typingCapsule) typingCapsule.style.display = 'none';

      const replyReplies = [
        'Принято в реплицированный лог [seq: OK].',
        'Сообщение доставлено и сохранено в storage-1.',
        'Файлы успешно зафиксированы в кластере.',
        'Получено! Синхронизирую с другими клиентами.'
      ];
      const replyText = replyReplies[Math.floor(Math.random() * replyReplies.length)];
      const replyTime = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

      const replyMsg = {
        id: `msg-${chat.id}-${Date.now() + 1}`,
        sender: 'incoming',
        type: 'text',
        text: replyText,
        time: replyTime
      };
      chat.messages.push(replyMsg);

      const replyRow = document.createElement('div');
      replyRow.className = 'msg-row incoming';
      replyRow.innerHTML = `
        <div class="msg-bubble typewriter-bubble">
          <span class="msg-author-tag">@${chat.name.split(' ')[0].toLowerCase()}</span>
          <div class="msg-text-content typewriter-streaming"></div>
          <div class="msg-meta">
            <span>${replyTime}</span>
          </div>
        </div>
      `;

      if (typingCapsule) {
        flow.insertBefore(replyRow, typingCapsule);
      } else {
        flow.appendChild(replyRow);
      }

      // Typewriter Character by Character Animation
      const textContainer = replyRow.querySelector('.msg-text-content');
      typewriterStreamText(textContainer, replyText, 18);
    }, 1100);
  }
}
window.sendSpatialMessage = handleSendSpatialMessage;
window.handleSendSpatialMessage = handleSendSpatialMessage;

function handleComposerKey(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    handleSendSpatialMessage(event);
  }
}
window.handleComposerKey = handleComposerKey;

// Typewriter Streaming Character by Character
function typewriterStreamText(element, fullText, speed = 18, callback = null) {
  if (!element) return;
  element.textContent = '';
  let i = 0;
  const timer = setInterval(() => {
    if (i < fullText.length) {
      element.textContent += fullText.charAt(i);
      i++;
      const flow = document.getElementById('spatial-messages-flow');
      if (flow) flow.scrollTop = flow.scrollHeight;
    } else {
      clearInterval(timer);
      if (callback) callback();
    }
  }, speed);
}

function insertEmojiDemo() {
  const input = document.getElementById('composer-input');
  if (!input) return;
  const emojis = ['✨', '🔥', '👍', '🚀', '⚡', '🎧'];
  const picked = emojis[Math.floor(Math.random() * emojis.length)];
  input.value += ` ${picked} `;
  input.focus();
}
window.insertEmojiDemo = insertEmojiDemo;

// ============================================================================
// 5. Functional Music & File Import Pipeline
// ============================================================================
function handleMusicFilesUpload(event) {
  const files = event.target.files;
  if (!files || files.length === 0) return;

  const file = files[0];
  const filename = file.name;
  const sizeStr = formatFileSize(file.size);

  const step1 = document.getElementById('pipe-step-1');
  const step2 = document.getElementById('pipe-step-2');
  const step3 = document.getElementById('pipe-step-3');

  const step1Sub = document.getElementById('pipe-step-1-sub');
  const step2Sub = document.getElementById('pipe-step-2-sub');
  const step3Sub = document.getElementById('pipe-step-3-sub');

  if (step1) step1.className = 'pipeline-step active';
  if (step1Sub) step1Sub.textContent = `Загружено: ${filename} (${sizeStr})`;

  setTimeout(() => {
    if (step1) step1.className = 'pipeline-step completed';
    if (step2) step2.className = 'pipeline-step active';
    if (step2Sub) step2Sub.textContent = `ID3: Парсинг тегов (${filename.replace(/\.[^/.]+$/, '')})`;

    setTimeout(() => {
      if (step2) step2.className = 'pipeline-step completed';
      if (step3) step3.className = 'pipeline-step active completed';
      if (step3Sub) step3Sub.textContent = 'Успешно реплицировано на storage-1 и storage-2';

      // Add to catalog
      addUploadedTrackToCatalog(filename, 'Пользовательский трек', sizeStr);
    }, 800);
  }, 700);

  event.target.value = '';
}
window.handleMusicFilesUpload = handleMusicFilesUpload;

function addUploadedTrackToCatalog(title, artist, sizeStr) {
  const list = document.getElementById('uploaded-tracks-list');
  const countLabel = document.getElementById('uploaded-count-label');
  if (!list) return;

  const item = document.createElement('div');
  item.className = 'uploaded-track-item';
  item.innerHTML = `
    <div class="track-item-icon">🎵</div>
    <div class="track-item-info">
      <div class="track-item-title typewriter-text">${escapeHtml(title)}</div>
      <div class="track-item-meta typewriter-font">${escapeHtml(artist)} • 3:30 • ${sizeStr} • storage-1:ok, storage-2:ok</div>
    </div>
    <div class="track-item-actions">
      <button class="tactile-btn" onclick="sendUploadedTrackToChat('${escapeHtml(title)}', '${escapeHtml(artist)}')" title="Отправить в чат">💬 В чат</button>
    </div>
  `;
  list.insertBefore(item, list.firstChild);

  const total = list.children.length;
  if (countLabel) countLabel.textContent = `${total} треков в кластере`;
}

function sendUploadedTrackToChat(filename, artist) {
  switchNavTab('chats');
  const chat = CHATS_STORE[currentActiveChatId];
  if (!chat) return;

  const now = new Date();
  const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

  const trackAttachment = {
    name: filename,
    sizeStr: '8.4 MB',
    isImage: false,
    dataUrl: null
  };

  const newMsg = {
    id: `msg-${chat.id}-${Date.now()}`,
    sender: 'outgoing',
    type: 'text',
    text: `Отправляю трек: ${filename}`,
    attachments: [trackAttachment],
    time: timeStr,
    delivered: true
  };

  chat.messages.push(newMsg);
  renderChatMessages(chat);
}
window.sendUploadedTrackToChat = sendUploadedTrackToChat;

// ============================================================================
// 6. Search & Quick Filters (Clean, No Unread/Tracks Filter)
// ============================================================================
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
window.handleSearchDialogs = handleSearchDialogs;

function filterDialogs(btn, filterType) {
  document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');

  const items = document.querySelectorAll('.deck-item');
  items.forEach(item => {
    if (filterType === 'all') {
      item.style.display = 'flex';
    } else if (filterType === 'direct') {
      item.style.display = 'flex';
    } else if (filterType === 'groups') {
      const chatId = parseInt(item.getAttribute('data-chat-id'), 10);
      item.style.display = (chatId === 4) ? 'flex' : 'none';
    }
  });
}
window.filterDialogs = filterDialogs;

// ============================================================================
// 7. Slide-Out Left Drawer Controller
// ============================================================================
let isDrawerOpen = localStorage.getItem('boysic_drawer_open') !== 'false';

function applyDrawerState() {
  const drawer = document.getElementById('dialogs-drawer');
  const headerBtn = document.getElementById('header-drawer-btn');

  if (drawer) {
    if (isDrawerOpen) {
      drawer.classList.remove('drawer-collapsed');
    } else {
      drawer.classList.add('drawer-collapsed');
    }
  }

  if (headerBtn) {
    headerBtn.classList.toggle('drawer-active', isDrawerOpen);
    headerBtn.title = isDrawerOpen ? 'Скрыть панель (Ctrl+B)' : 'Показать панель (Ctrl+B)';
  }
}

function toggleDialogsDrawer(forceState) {
  if (typeof forceState === 'boolean') {
    isDrawerOpen = forceState;
  } else {
    isDrawerOpen = !isDrawerOpen;
  }
  localStorage.setItem('boysic_drawer_open', isDrawerOpen);
  applyDrawerState();
}
window.toggleDialogsDrawer = toggleDialogsDrawer;

// Global Hotkeys: Ctrl+B / Cmd+B for Drawer Toggle
window.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && (e.key === 'b' || e.key === 'B' || e.key === 'и' || e.key === 'И')) {
    e.preventDefault();
    toggleDialogsDrawer();
  }
});

// Drag and drop setup for chat canvas & dropzone
function setupDragAndDrop() {
  const dropBox = document.getElementById('import-dropzone-box');
  if (dropBox) {
    ['dragenter', 'dragover'].forEach(name => {
      dropBox.addEventListener(name, (e) => {
        e.preventDefault();
        dropBox.classList.add('drag-over');
      });
    });
    ['dragleave', 'drop'].forEach(name => {
      dropBox.addEventListener(name, (e) => {
        e.preventDefault();
        dropBox.classList.remove('drag-over');
      });
    });
    dropBox.addEventListener('drop', (e) => {
      const dt = e.dataTransfer;
      if (dt && dt.files && dt.files.length > 0) {
        handleMusicFilesUpload({ target: { files: dt.files, value: '' } });
      }
    });
  }

  const chatCanvas = document.getElementById('chat-canvas-main');
  if (chatCanvas) {
    chatCanvas.addEventListener('dragover', (e) => {
      e.preventDefault();
    });
    chatCanvas.addEventListener('drop', (e) => {
      e.preventDefault();
      const dt = e.dataTransfer;
      if (dt && dt.files && dt.files.length > 0) {
        handleComposerFileSelected({ target: { files: dt.files, value: '' } });
      }
    });
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
  applyDrawerState();
  selectChat(1);
  setupDragAndDrop();
});
