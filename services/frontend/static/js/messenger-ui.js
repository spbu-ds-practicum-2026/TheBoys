/**
 * Boysic Messenger — Modern Discord & Telegram Dark Hybrid (Refined Gray Edition)
 * Features:
 *  - Monochromatic Dark & Sleek Gray Avatars (No orange clutter)
 *  - Bilingual i18n System (English Default, Instant Live RU/EN Switching)
 *  - Typewriter Streaming & Monospace Precision
 *  - Functional Paperclip File Attachments & Music Upload Pipeline
 */

// ============================================================================
// 1. Bilingual Translations Dictionary (EN Default / RU)
// ============================================================================
const I18N_DICTIONARY = {
  en: {
    // Navigation
    nav_chats: 'Chats',
    nav_player: 'Player',
    nav_import: 'Import Music',
    nav_settings: 'Settings',
    back_to_chats: 'Back to Chats',
    user_status_online: 'Dmitry Byzov (online)',

    // Drawer / Dialogs
    search_placeholder: 'Search messages...',
    hide_drawer: 'Hide drawer (Ctrl+B)',
    show_drawer: 'Show drawer (Ctrl+B)',
    filter_all: 'All Chats',
    filter_direct: 'Direct',
    filter_channels: 'Channels',

    // Chat header & recipient
    user_alice: 'Alice Smirnova',
    user_oleg: 'Oleg Ivanov',
    user_pavel: 'Pavel Grigoryev',
    user_artem: 'Artem Eremenko',
    recipient_online_node2: 'online [node app-2]',
    recipient_online_node1: 'online [node app-1]',
    recipient_offline_pavel: 'last seen 45 min ago',
    search_chat_tooltip: 'Search conversation',
    dialog_options_tooltip: 'Chat options',

    // Timeline & typing
    timeline_today: 'Today',
    timeline_stream: '[ -- 2026-10-26 // LOG STREAM -- ]',
    typing_alice: 'alice is typing...',
    typing_oleg: 'oleg is typing...',
    typing_pavel: 'pavel is typing...',
    typing_artem: 'artem is typing...',

    // Messages
    msg_alice_1: 'Hello! Full-text search and file storage are up and running.',
    msg_alice_2: 'Verified inter-node delivery via POST /internal/deliver — all sequence events arrive in strict order without duplicates.',
    msg_alice_3: 'Great! Now attachments can be sent with any file format, and the music import section supports track uploads.',
    msg_alice_4: 'Typewriter active: monospace input with tactile feedback and live cursor.',
    alice_preview: 'Hello! Full-text search and storage are ready...',
    oleg_preview: 'Can we send attachments via paperclip now?',
    pavel_preview: 'Database schema committed',
    artem_preview: 'Docker Compose cluster is up',

    // Composer
    attach_tooltip: 'Attach file (Paperclip)',
    composer_placeholder: 'Write a message to {name}...',
    emoji_tooltip: 'Insert emoji',
    send_tooltip: 'Send message (Enter)',

    // Footer
    footer_drawer: 'drawer',
    footer_send: 'send',
    footer_engine: '[TTY // ENGINE: LIVE]',
    footer_seq: 'seq: total order',
    footer_ws: 'ws: connected',
    footer_node: 'node: app-1',

    // Player tab
    player_badge: 'Audio Module',
    player_title: 'Music Player',
    player_desc: 'Global audio player with seamless background playback during messaging and navigation',
    player_now_playing: 'NOW PLAYING',
    player_shuffle: 'Shuffle',
    player_prev: 'Previous',
    player_play_pause: 'Play / Pause',
    player_next: 'Next',
    player_repeat: 'Repeat',
    player_footer_note: 'Tracks replicated across 2 nodes (storage-1, storage-2). Streaming via HTTP /blobs/{id}',

    // Import tab
    import_badge: '[STORAGE // REPLICATION ENGINE]',
    import_title: 'Import Music',
    import_desc: 'Upload MP3/WAV to distributed cluster with auto ID3-tag extraction and multi-node replication',
    dropzone_title: 'Drag & drop audio files here or click to browse',
    dropzone_subtitle: 'Supports MP3, WAV, FLAC, OGG (up to 50 MB)',
    chip_size: 'up to 50 MB',
    chip_id3: 'ID3 Parser',
    chip_replication: 'Replication: 2 copies',
    step1_title: 'Upload to node',
    step1_sub: 'Waiting for file selection...',
    step2_title: 'ID3 Metadata',
    step2_sub: 'Parsing tags and bitrate',
    step3_title: 'Replication',
    step3_sub: 'Synchronizing storage-1/storage-2',
    catalog_title: '[UPLOADED TRACKS CATALOG]',
    catalog_counter: '{count} tracks in cluster',
    send_to_chat_btn: '💬 To chat',

    // Settings tab
    settings_title: 'System Settings',
    settings_desc: 'Manage profile, glass physics, language and distributed cluster state'
  },
  ru: {
    // Navigation
    nav_chats: 'Чаты',
    nav_player: 'Плеер',
    nav_import: 'Импорт своей музыки',
    nav_settings: 'Параметры',
    back_to_chats: 'Назад к чатам',
    user_status_online: 'Дмитрий Бызов (в сети)',

    // Drawer / Dialogs
    search_placeholder: 'Поиск сообщений...',
    hide_drawer: 'Скрыть панель (Ctrl+B)',
    show_drawer: 'Показать панель (Ctrl+B)',
    filter_all: 'Все диалоги',
    filter_direct: 'Личные',
    filter_channels: 'Каналы',

    // Chat header & recipient
    user_alice: 'Алиса Смирнова',
    user_oleg: 'Олег Иванов',
    user_pavel: 'Павел Григорьев',
    user_artem: 'Артём Еременко',
    recipient_online_node2: 'в сети [узел app-2]',
    recipient_online_node1: 'в сети [узел app-1]',
    recipient_offline_pavel: 'был(а) в сети 45 мин назад',
    search_chat_tooltip: 'Поиск по переписке',
    dialog_options_tooltip: 'Опции диалога',

    // Timeline & typing
    timeline_today: 'Сегодня',
    timeline_stream: '[ -- 2026-10-26 // ПОТОК СООБЩЕНИЙ -- ]',
    typing_alice: 'alisa печатает...',
    typing_oleg: 'oleg печатает...',
    typing_pavel: 'pavel печатает...',
    typing_artem: 'artem печатает...',

    // Messages
    msg_alice_1: 'Привет! Полнотекстовый поиск и хранилище файлов готовы к работе.',
    msg_alice_2: 'Проверила доставку через межузловой протокол POST /internal/deliver — все события приходят строго по порядку sequence без дублей.',
    msg_alice_3: 'Отлично! Теперь через скрепку можно прикреплять любые файлы, а в разделе импорта загружать треки с предпросмотром.',
    msg_alice_4: 'Печатная машинка активна: monospace-набор с тактильным откликом и живым курсором.',
    alice_preview: 'Привет! Проверила доставку сообщений...',
    oleg_preview: 'Слушай, а вложения теперь отправляются?',
    pavel_preview: 'Схему БД зафиксировал',
    artem_preview: 'Docker Compose стенд поднят',

    // Composer
    attach_tooltip: 'Прикрепить файл (Скрепка)',
    composer_placeholder: 'Написать сообщение {name}...',
    emoji_tooltip: 'Вставить эмодзи',
    send_tooltip: 'Отправить сообщение (Enter)',

    // Footer
    footer_drawer: 'панель',
    footer_send: 'отправить',
    footer_engine: '[TTY // ДВИЖОК: АКТИВЕН]',
    footer_seq: 'seq: строгий порядок',
    footer_ws: 'ws: подключено',
    footer_node: 'узел: app-1',

    // Player tab
    player_badge: 'Аудио-модуль',
    player_title: 'Музыкальный плеер',
    player_desc: 'Глобальный аудиоплеер с непрерывным воспроизведением треков во время навигации и переписки',
    player_now_playing: 'СЕЙЧАС ИГРАЕТ',
    player_shuffle: 'Перемешать',
    player_prev: 'Предыдущий',
    player_play_pause: 'Воспроизведение / Пауза',
    player_next: 'Следующий',
    player_repeat: 'Повтор',
    player_footer_note: 'Треки распределены в 2 копиях на узлах storage-1 и storage-2. Стриминг через HTTP /blobs/{id}',

    // Import tab
    import_badge: '[STORAGE // ДВИЖОК РЕПЛИКАЦИИ]',
    import_title: 'Импорт своей музыки',
    import_desc: 'Загрузка MP3/WAV в распределённый кластер с автоматическим извлечением ID3-тегов и репликацией на storage-узлы',
    dropzone_title: 'Перетащите аудиофайлы сюда или нажмите для выбора',
    dropzone_subtitle: 'Поддерживаются MP3, WAV, FLAC, OGG (до 50 МБ)',
    chip_size: 'до 50 МБ',
    chip_id3: 'Парсер ID3',
    chip_replication: 'Репликация: 2 копии',
    step1_title: 'Загрузка в узел',
    step1_sub: 'Ожидание выбора файла...',
    step2_title: 'ID3 Метаданные',
    step2_sub: 'Парсинг тегов и битрейта',
    step3_title: 'Репликация',
    step3_sub: 'Синхронизация storage-1/storage-2',
    catalog_title: '[КАТАЛОГ ЗАГРУЖЕННЫХ ТРЕКОВ]',
    catalog_counter: '{count} трека в кластере',
    send_to_chat_btn: '💬 В чат',

    // Settings tab
    settings_title: 'Параметры системы',
    settings_desc: 'Управление профилем, космической физикой стекла и состоянием распределённого кластера'
  }
};

// Current active language: English is strictly the default
let currentLang = localStorage.getItem('boysic_lang') || 'en';

// ============================================================================
// 2. Chat Data Store with Bilingual Data & Sleek Gray Avatars
// ============================================================================
const CHATS_STORE = {
  1: {
    id: 1,
    name_en: 'Alice Smirnova',
    name_ru: 'Алиса Смирнова',
    initials_en: 'AS',
    initials_ru: 'АС',
    status: 'online',
    status_en: 'online [node app-2]',
    status_ru: 'в сети [узел app-2]',
    avatarBg: 'var(--avatar-gray-gradient)',
    messages_en: [
      {
        id: 'msg-1-1',
        sender: 'incoming',
        type: 'text',
        text: 'Hello! Full-text search and file storage are up and running.',
        time: '19:40'
      },
      {
        id: 'msg-1-2',
        sender: 'incoming',
        type: 'text',
        text: 'Verified inter-node delivery via POST /internal/deliver — all sequence events arrive in strict order without duplicates.',
        time: '19:41'
      },
      {
        id: 'msg-1-3',
        sender: 'outgoing',
        type: 'text',
        text: 'Great! Now attachments can be sent with any file format, and the music import section supports track uploads.',
        time: '19:42',
        delivered: true
      },
      {
        id: 'msg-1-4',
        sender: 'outgoing',
        type: 'text',
        text: 'Typewriter active: monospace input with tactile feedback and live cursor.',
        time: '19:43',
        delivered: true
      }
    ],
    messages_ru: [
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
    name_en: 'Oleg Ivanov',
    name_ru: 'Олег Иванов',
    initials_en: 'OI',
    initials_ru: 'ОИ',
    status: 'online',
    status_en: 'online [node app-1]',
    status_ru: 'в сети [узел app-1]',
    avatarBg: 'var(--avatar-gray-gradient)',
    messages_en: [
      {
        id: 'msg-2-1',
        sender: 'incoming',
        type: 'text',
        text: 'Hey Dmitry! Finishing up the layout for music catalog screens.',
        time: '19:28'
      },
      {
        id: 'msg-2-2',
        sender: 'incoming',
        type: 'text',
        text: 'Can we send attachments via paperclip now?',
        time: '19:30'
      },
      {
        id: 'msg-2-3',
        sender: 'outgoing',
        type: 'text',
        text: 'Yes! Added full file selection with chip preview in composer and direct message stream upload.',
        time: '19:32',
        delivered: true
      },
      {
        id: 'msg-2-4',
        sender: 'incoming',
        type: 'text',
        text: 'Awesome, testing photo and MP3 file uploads 👍',
        time: '19:34'
      }
    ],
    messages_ru: [
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
    name_en: 'Pavel Grigoryev',
    name_ru: 'Павел Григорьев',
    initials_en: 'PG',
    initials_ru: 'ПГ',
    status: 'offline',
    status_en: 'last seen 45 min ago',
    status_ru: 'был(а) в сети 45 мин назад',
    avatarBg: 'var(--avatar-gray-gradient)',
    messages_en: [
      {
        id: 'msg-3-1',
        sender: 'incoming',
        type: 'text',
        text: 'Hello! Database schema locked: conversations, messages, sessions, replicas.',
        time: '18:10'
      },
      {
        id: 'msg-3-2',
        sender: 'incoming',
        type: 'text',
        text: 'Using direct_key = min_id:max_id for 1-on-1 chats with monotonic seq.',
        time: '18:12'
      },
      {
        id: 'msg-3-3',
        sender: 'outgoing',
        type: 'text',
        text: 'Excellent! Generating seq strictly within chat transaction to avoid race conditions.',
        time: '18:15',
        delivered: true
      }
    ],
    messages_ru: [
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
    name_en: 'Artem Eremenko',
    name_ru: 'Артём Еременко',
    initials_en: 'AE',
    initials_ru: 'АЕ',
    status: 'online',
    status_en: 'online [node app-1]',
    status_ru: 'в сети [узел app-1]',
    avatarBg: 'var(--avatar-gray-gradient)',
    messages_en: [
      {
        id: 'msg-4-1',
        sender: 'incoming',
        type: 'text',
        text: 'Docker Compose stack is online! Nginx load balances traffic between app-1 and app-2.',
        time: '17:50'
      },
      {
        id: 'msg-4-2',
        sender: 'incoming',
        type: 'text',
        text: 'Containers replicate messages and files in real-time.',
        time: '17:52'
      }
    ],
    messages_ru: [
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

// Get chat localized fields
function getChatName(chat, lang = currentLang) {
  return lang === 'ru' ? chat.name_ru : chat.name_en;
}

function getChatInitials(chat, lang = currentLang) {
  return lang === 'ru' ? chat.initials_ru : chat.initials_en;
}

function getChatStatusText(chat, lang = currentLang) {
  return lang === 'ru' ? chat.status_ru : chat.status_en;
}

function getChatMessages(chat, lang = currentLang) {
  return lang === 'ru' ? chat.messages_ru : chat.messages_en;
}

// ============================================================================
// 3. Language Switching Engine (EN / RU)
// ============================================================================
function setLanguage(lang) {
  if (lang !== 'en' && lang !== 'ru') lang = 'en';
  currentLang = lang;
  localStorage.setItem('boysic_lang', currentLang);

  document.documentElement.lang = currentLang;

  // Update switcher badges in rail
  const badgeEn = document.getElementById('lang-badge-en');
  const badgeRu = document.getElementById('lang-badge-ru');
  if (badgeEn && badgeRu) {
    if (currentLang === 'en') {
      badgeEn.classList.add('active');
      badgeRu.classList.remove('active');
    } else {
      badgeEn.classList.remove('active');
      badgeRu.classList.add('active');
    }
  }

  const dict = I18N_DICTIONARY[currentLang];

  // Update elements with [data-i18n]
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (dict[key]) {
      el.textContent = dict[key];
    }
  });

  // Update elements with [data-i18n-placeholder]
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    if (dict[key]) {
      const activeChat = CHATS_STORE[currentActiveChatId];
      const firstName = activeChat ? getChatName(activeChat, currentLang).split(' ')[0] : 'user';
      el.placeholder = dict[key].replace('{name}', firstName);
    }
  });

  // Update elements with [data-i18n-title]
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.getAttribute('data-i18n-title');
    if (dict[key]) {
      el.title = dict[key];
    }
  });

  // Update dialogs drawer list items
  updateDialogsListLanguage();

  // Re-render active chat
  const chat = CHATS_STORE[currentActiveChatId];
  if (chat) {
    renderChatHeader(chat);
    renderChatMessages(chat);
    updateComposerPlaceholder(chat);
  }
}
window.setLanguage = setLanguage;

function toggleLanguage() {
  const nextLang = currentLang === 'en' ? 'ru' : 'en';
  setLanguage(nextLang);
}
window.toggleLanguage = toggleLanguage;

function updateDialogsListLanguage() {
  Object.keys(CHATS_STORE).forEach(id => {
    const chat = CHATS_STORE[id];
    const item = document.querySelector(`.deck-item[data-chat-id="${id}"]`);
    if (!item) return;

    const nameEl = item.querySelector('.deck-item-name');
    const avatarEl = item.querySelector('.deck-item-avatar');
    const previewEl = item.querySelector('.deck-item-preview');

    if (nameEl) nameEl.textContent = getChatName(chat, currentLang);
    if (avatarEl) {
      avatarEl.textContent = getChatInitials(chat, currentLang);
      const dot = document.createElement('span');
      dot.className = `deck-presence-dot ${chat.status}`;
      avatarEl.appendChild(dot);
    }

    if (previewEl) {
      const msgs = getChatMessages(chat, currentLang);
      if (msgs && msgs.length > 0) {
        const lastMsg = msgs[msgs.length - 1];
        previewEl.textContent = lastMsg.text;
      }
    }
  });
}

// ============================================================================
// 4. Navigation Tab Switching (Chats, Player, Import, Settings)
// ============================================================================
function switchNavTab(tabName) {
  const tabs = ['player', 'chats', 'import', 'settings'];
  const validTab = tabs.includes(tabName) ? tabName : 'chats';
  
  tabs.forEach(name => {
    const btn = document.getElementById(`btn-tab-${name}`);
    const secBtn = document.getElementById(`sec-btn-${name}`);
    const view = document.getElementById(`view-${name}`);

    if (name === validTab) {
      if (btn) btn.classList.add('active');
      if (secBtn) secBtn.classList.add('active');
      if (view) view.style.display = 'flex';
    } else {
      if (btn) btn.classList.remove('active');
      if (secBtn) secBtn.classList.remove('active');
      if (view) view.style.display = 'none';
    }
  });

  try {
    const newPath = validTab === 'chats' ? '/' : `/${validTab}`;
    if (window.location.pathname !== newPath) {
      history.pushState({ tab: validTab }, '', newPath);
    }
  } catch (e) {
    // Ignore history restrictions in isolated environments
  }

  if (validTab === 'chats') {
    const flow = document.getElementById('spatial-messages-flow');
    if (flow) flow.scrollTop = flow.scrollHeight;
  }
}
window.switchNavTab = switchNavTab;

// Handle browser Back / Forward navigation
window.addEventListener('popstate', () => {
  const path = window.location.pathname.replace(/^\//, '');
  const tab = ['player', 'chats', 'import', 'settings'].includes(path) ? path : 'chats';
  switchNavTab(tab);
});

// ============================================================================
// 5. Select & Render Chat
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

  // Re-render chat header & messages
  renderChatHeader(chatData);
  renderChatMessages(chatData);
  updateComposerPlaceholder(chatData);

  // Auto-collapse drawer on mobile viewports
  if (window.innerWidth <= 860 && typeof isDrawerOpen !== 'undefined' && isDrawerOpen) {
    toggleDialogsDrawer(false);
  }
}
window.selectChat = selectChat;

function updateComposerPlaceholder(chat) {
  const input = document.getElementById('composer-input');
  if (!input) return;
  const firstName = getChatName(chat, currentLang).split(' ')[0];
  const dict = I18N_DICTIONARY[currentLang];
  input.placeholder = dict.composer_placeholder.replace('{name}', firstName);
}

// Render Chat Header with Sleek Gray Avatar
function renderChatHeader(chat) {
  const nameEl = document.getElementById('active-recipient-name');
  const statusTextEl = document.getElementById('active-recipient-status-text');
  const avatarEl = document.getElementById('active-recipient-avatar');
  const statusContainer = document.getElementById('active-recipient-status');

  if (nameEl) nameEl.textContent = getChatName(chat, currentLang);
  if (avatarEl) {
    avatarEl.textContent = getChatInitials(chat, currentLang);
    avatarEl.className = 'chat-recipient-avatar avatar-gray';
  }

  if (statusContainer) {
    if (chat.status === 'online') {
      statusContainer.className = 'chat-recipient-status online';
    } else {
      statusContainer.className = 'chat-recipient-status';
    }
  }

  if (statusTextEl) {
    statusTextEl.textContent = getChatStatusText(chat, currentLang);
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
  timelinePill.textContent = I18N_DICTIONARY[currentLang].timeline_today;
  flow.appendChild(timelinePill);

  const messages = getChatMessages(chat, currentLang);

  // Render all messages in sequence
  messages.forEach(msg => {
    const row = document.createElement('div');
    row.className = `msg-row ${msg.sender}`;

    const checkMarkSvg = msg.delivered ? `
      <svg class="msg-status-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6">
        <path d="M18 6L7 17l-5-5"></path>
        <path d="M22 10l-7.5 7.5L13 16"></path>
      </svg>
    ` : '';

    const authorTag = msg.sender === 'incoming' ? `<span class="msg-author-tag">@${getChatName(chat, 'en').split(' ')[0].toLowerCase()}</span>` : '';

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
        <div class="msg-body-text">${escapeHtml(msg.text || '')}</div>
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
    const dict = I18N_DICTIONARY[currentLang];
    const key = `typing_${getChatName(chat, 'en').split(' ')[0].toLowerCase()}`;
    const typingText = dict[key] || `${getChatName(chat, currentLang).split(' ')[0]} ...`;
    typing.innerHTML = `
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
      <span class="typing-label typewriter-font" id="chat-typing-label">${typingText}</span>
    `;
    flow.appendChild(typing);
  }

  flow.scrollTop = flow.scrollHeight;
}

// ============================================================================
// 6. Functional Paperclip & File Attachments
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
// 7. Send Message with Typewriter Streaming Effect
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

  // Add to active lang message list
  if (currentLang === 'ru') {
    chat.messages_ru.push(newMsg);
  } else {
    chat.messages_en.push(newMsg);
  }

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
      <div class="msg-body-text">${escapeHtml(text)}</div>
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

      const repliesEn = [
        'Received in replicated log [seq: OK].',
        'Message delivered and stored in storage-1.',
        'Files successfully committed to cluster.',
        'Got it! Synchronizing across all nodes.'
      ];
      const repliesRu = [
        'Принято в реплицированный лог [seq: OK].',
        'Сообщение доставлено и сохранено в storage-1.',
        'Файлы успешно зафиксированы в кластере.',
        'Получено! Синхронизирую с другими клиентами.'
      ];

      const replyPool = currentLang === 'ru' ? repliesRu : repliesEn;
      const replyText = replyPool[Math.floor(Math.random() * replyPool.length)];
      const replyTime = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

      const replyMsg = {
        id: `msg-${chat.id}-${Date.now() + 1}`,
        sender: 'incoming',
        type: 'text',
        text: replyText,
        time: replyTime
      };

      if (currentLang === 'ru') {
        chat.messages_ru.push(replyMsg);
      } else {
        chat.messages_en.push(replyMsg);
      }

      const replyRow = document.createElement('div');
      replyRow.className = 'msg-row incoming';
      replyRow.innerHTML = `
        <div class="msg-bubble typewriter-bubble">
          <span class="msg-author-tag">@${getChatName(chat, 'en').split(' ')[0].toLowerCase()}</span>
          <div class="msg-body-text typewriter-streaming"></div>
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
      const textContainer = replyRow.querySelector('.msg-body-text');
      typewriterStreamText(textContainer, replyText, 18);
    }, 1000);
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
// 8. Functional Music & File Import Pipeline
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
  if (step1Sub) step1Sub.textContent = currentLang === 'ru' 
    ? `Загружено: ${filename} (${sizeStr})` 
    : `Uploaded: ${filename} (${sizeStr})`;

  setTimeout(() => {
    if (step1) step1.className = 'pipeline-step completed';
    if (step2) step2.className = 'pipeline-step active';
    if (step2Sub) step2Sub.textContent = currentLang === 'ru'
      ? `ID3: Парсинг тегов (${filename.replace(/\.[^/.]+$/, '')})`
      : `ID3: Parsing tags (${filename.replace(/\.[^/.]+$/, '')})`;

    setTimeout(() => {
      if (step2) step2.className = 'pipeline-step completed';
      if (step3) step3.className = 'pipeline-step active completed';
      if (step3Sub) step3Sub.textContent = currentLang === 'ru'
        ? 'Успешно реплицировано на storage-1 и storage-2'
        : 'Replicated successfully on storage-1 and storage-2';

      // Add to catalog
      addUploadedTrackToCatalog(filename, currentLang === 'ru' ? 'Пользовательский трек' : 'User Track', sizeStr);
    }, 700);
  }, 600);

  event.target.value = '';
}
window.handleMusicFilesUpload = handleMusicFilesUpload;

function addUploadedTrackToCatalog(title, artist, sizeStr) {
  const list = document.getElementById('uploaded-tracks-list');
  const countLabel = document.getElementById('uploaded-count-label');
  if (!list) return;

  const item = document.createElement('div');
  item.className = 'uploaded-track-item';
  const btnText = I18N_DICTIONARY[currentLang].send_to_chat_btn;
  item.innerHTML = `
    <div class="track-item-icon">🎵</div>
    <div class="track-item-info">
      <div class="track-item-title typewriter-text">${escapeHtml(title)}</div>
      <div class="track-item-meta typewriter-font">${escapeHtml(artist)} • 3:30 • ${sizeStr} • storage-1:ok, storage-2:ok</div>
    </div>
    <div class="track-item-actions">
      <button class="tactile-btn" onclick="sendUploadedTrackToChat('${escapeHtml(title)}', '${escapeHtml(artist)}')">${btnText}</button>
    </div>
  `;
  list.insertBefore(item, list.firstChild);

  const total = list.children.length;
  if (countLabel) {
    countLabel.textContent = currentLang === 'ru' 
      ? `${total} трека в кластере` 
      : `${total} tracks in cluster`;
  }
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

  const textMsg = currentLang === 'ru' ? `Отправляю трек: ${filename}` : `Sending track: ${filename}`;

  const newMsg = {
    id: `msg-${chat.id}-${Date.now()}`,
    sender: 'outgoing',
    type: 'text',
    text: textMsg,
    attachments: [trackAttachment],
    time: timeStr,
    delivered: true
  };

  if (currentLang === 'ru') {
    chat.messages_ru.push(newMsg);
  } else {
    chat.messages_en.push(newMsg);
  }

  renderChatMessages(chat);
}
window.sendUploadedTrackToChat = sendUploadedTrackToChat;

// ============================================================================
// 9. Search & Quick Filters
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
// 10. Slide-Out Left Drawer Controller
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
    const dict = I18N_DICTIONARY[currentLang];
    headerBtn.title = isDrawerOpen ? dict.hide_drawer : dict.show_drawer;
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

function toggleDrawerDropdownMenu(event) {
  if (event) event.stopPropagation();
  const menu = document.getElementById('drawer-dropdown-menu');
  if (!menu) return;
  const isHidden = menu.style.display === 'none' || !menu.style.display;
  menu.style.display = isHidden ? 'flex' : 'none';
}
window.toggleDrawerDropdownMenu = toggleDrawerDropdownMenu;

function closeDrawerDropdownMenu() {
  const menu = document.getElementById('drawer-dropdown-menu');
  if (menu) menu.style.display = 'none';
}
window.closeDrawerDropdownMenu = closeDrawerDropdownMenu;

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
  const menu = document.getElementById('drawer-dropdown-menu');
  const btn = document.getElementById('drawer-menu-btn');
  if (menu && menu.style.display !== 'none' && !menu.contains(e.target) && !btn?.contains(e.target)) {
    menu.style.display = 'none';
  }
});

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

// ============================================================================
// 10. Cosmic Settings Physics & Interactive Spotlight Controls
// ============================================================================
let cursorGlowEnabled = localStorage.getItem('boysic_cursor_glow') !== 'false';
let mouseX = window.innerWidth / 2;
let mouseY = window.innerHeight / 2;
let currentX = mouseX;
let currentY = mouseY;

function initCursorSpotlight() {
  const spotlight = document.getElementById('solar-cursor-spotlight');
  if (!spotlight) return;

  spotlight.style.display = cursorGlowEnabled ? 'block' : 'none';

  window.addEventListener('mousemove', (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;
  });

  function animateSpotlight() {
    if (cursorGlowEnabled && spotlight) {
      currentX += (mouseX - currentX) * 0.14;
      currentY += (mouseY - currentY) * 0.14;
      spotlight.style.transform = `translate3d(${currentX}px, ${currentY}px, 0)`;
    }
    requestAnimationFrame(animateSpotlight);
  }
  requestAnimationFrame(animateSpotlight);
}

function toggleCursorGlow(checkbox) {
  cursorGlowEnabled = checkbox.checked;
  localStorage.setItem('boysic_cursor_glow', cursorGlowEnabled);
  const spotlight = document.getElementById('solar-cursor-spotlight');
  if (spotlight) {
    spotlight.style.display = cursorGlowEnabled ? 'block' : 'none';
  }
}
window.toggleCursorGlow = toggleCursorGlow;

function toggleBlackHole(checkbox) {
  const isEnabled = checkbox.checked;
  localStorage.setItem('boysic_black_hole', isEnabled);
  const canvas = document.getElementById('cosmic-canvas');
  if (canvas) {
    canvas.style.opacity = isEnabled ? '1' : '0.12';
  }
}
window.toggleBlackHole = toggleBlackHole;

function toggleHaptics(checkbox) {
  const isEnabled = checkbox.checked;
  localStorage.setItem('boysic_haptics', isEnabled);
  document.body.classList.toggle('disable-tactile-lift', !isEnabled);
}
window.toggleHaptics = toggleHaptics;

function toggleSpatialBlur(checkbox) {
  const isEnabled = checkbox.checked;
  localStorage.setItem('boysic_spatial_blur', isEnabled);
  const root = document.documentElement;
  if (isEnabled) {
    root.style.setProperty('--glass-blur-deep', 'blur(28px) saturate(190%)');
  } else {
    root.style.setProperty('--glass-blur-deep', 'blur(0px) saturate(100%)');
  }
}
window.toggleSpatialBlur = toggleSpatialBlur;

function toggleSpatialLens(checkbox) {
  const isEnabled = checkbox.checked;
  localStorage.setItem('boysic_spatial_lens', isEnabled);
  const lens = document.querySelector('.accretion-disk-glow');
  if (lens) {
    lens.style.display = isEnabled ? 'block' : 'none';
  }
}
window.toggleSpatialLens = toggleSpatialLens;

// ============================================================================
// 11. Initial Boot
// ============================================================================
document.addEventListener('DOMContentLoaded', () => {
  setLanguage(currentLang);
  applyDrawerState();

  const initialTab = document.body.getAttribute('data-active-tab') || 'chats';
  switchNavTab(initialTab);

  selectChat(1);
  setupDragAndDrop();
  initCursorSpotlight();

  // Synchronize Settings UI toggles with persisted localStorage
  const savedCursorToggle = document.getElementById('spatial-toggle-cursor');
  if (savedCursorToggle) {
    savedCursorToggle.checked = cursorGlowEnabled;
  }

  const savedBlackHole = localStorage.getItem('boysic_black_hole');
  const blackHoleToggle = document.getElementById('spatial-toggle-black-hole');
  if (blackHoleToggle) {
    const isEnabled = savedBlackHole !== 'false';
    blackHoleToggle.checked = isEnabled;
    toggleBlackHole(blackHoleToggle);
  }

  const savedHaptics = localStorage.getItem('boysic_haptics');
  const hapticsToggle = document.getElementById('spatial-toggle-haptics');
  if (hapticsToggle) {
    const isEnabled = savedHaptics !== 'false';
    hapticsToggle.checked = isEnabled;
    toggleHaptics(hapticsToggle);
  }

  const savedBlur = localStorage.getItem('boysic_spatial_blur');
  const blurToggle = document.getElementById('spatial-toggle-blur');
  if (blurToggle) {
    const isEnabled = savedBlur !== 'false';
    blurToggle.checked = isEnabled;
    toggleSpatialBlur(blurToggle);
  }

  const savedLens = localStorage.getItem('boysic_spatial_lens');
  const lensToggle = document.getElementById('spatial-toggle-lens');
  if (lensToggle) {
    const isEnabled = savedLens !== 'false';
    lensToggle.checked = isEnabled;
    toggleSpatialLens(lensToggle);
  }
});
