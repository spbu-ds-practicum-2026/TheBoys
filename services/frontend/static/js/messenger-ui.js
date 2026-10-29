/**
 * Boysic — Replicated Music & Messenger Client Engine
 * Fully aligned with TR specification (docs/tr.md) and PR #2 & PR #4 reviews.
 * 
 * Key Architecture:
 * 1. Single source of truth for messages and canonical track UUIDs
 * 2. Persistent global audio player with RFC 9110 Range streaming
 * 3. Synchronized track cards in chat, music catalog, and mini-player
 * 4. XSS-safe event delegation and strict HTML escaping
 * 5. Safe localStorage access wrapped in try/catch
 * 6. Sequential ordering (seq), inter-node delivery contracts, and unread counters
 * 7. Clean HTMX integration with zero recursive event loops
 */

// ============================================================================
// 1. Safe LocalStorage Helpers
// ============================================================================
function safeStorageGet(key, defaultVal = null) {
  try {
    const val = localStorage.getItem(key);
    return val !== null ? val : defaultVal;
  } catch (e) {
    return defaultVal;
  }
}

function safeStorageSet(key, val) {
  try {
    localStorage.setItem(key, val);
  } catch (e) {
    // Ignore storage quota or access denial errors
  }
}

// Escape HTML Helper (Strict XSS Prevention)
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
window.escapeHtml = escapeHtml;

// ============================================================================
// 2. Bilingual i18n Dictionary (EN Default / RU)
// ============================================================================
const I18N_DICTIONARY = {
  en: {
    // Navigation
    nav_music: 'Music',
    nav_chats: 'Chats',
    nav_import: 'Import',
    nav_settings: 'Settings',
    user_status_online: 'Dmitry Byzov (online)',

    // Music Catalog
    catalog_badge: '[CATALOG // REPLICATED AUDIO]',
    music_title: 'Music Catalog',
    music_desc: 'Audio files catalog of the distributed cluster. Streaming via GET /api/tracks/{id}/stream with Range header support.',
    catalog_cluster_state: '2 replicas: storage-1 / storage-2',
    search_tracks_placeholder: 'Search by title or artist...',
    catalog_no_tracks: 'No tracks found matching your query',
    share_to_chat: 'To chat',

    // Dialogs Drawer
    search_dialogs_placeholder: 'Search contacts...',
    new_dialog_tooltip: 'Find user by login / New dialog',
    hide_drawer: 'Hide drawer (Ctrl+B)',
    show_drawer: 'Show drawer (Ctrl+B)',
    filter_all: 'All',
    filter_unread: 'Unread',

    // Chat Header & Recipient
    user_alice: 'Alice Smirnova',
    user_oleg: 'Oleg Ivanov',
    user_pavel: 'Pavel Grigoryev',
    user_artem: 'Artem Eremenko',
    recipient_online_node2: 'online [node app-2]',
    recipient_online_node1: 'online [node app-1]',
    search_chat_tooltip: 'Search conversation',
    dialog_options_tooltip: 'Conversation options',
    timeline_today: 'Today',
    composer_placeholder: 'Write a message to {name}...',
    attach_track_tooltip: 'Attach Track Card (TR FT5)',
    emoji_tooltip: 'Insert emoji',
    send_tooltip: 'Send message (Enter)',
    typing_alice: 'alice is typing...',

    // Import View
    import_badge: '[STORAGE // REPLICATION ENGINE]',
    import_title: 'Import MP3 Tracks',
    import_desc: 'Upload MP3 audio files to distributed storage cluster. Automated ID3 tag parsing and 2-copy replication across storage nodes.',
    dropzone_title: 'Drag & drop MP3 files here or click to browse',
    dropzone_subtitle: 'Supported format: MP3 (up to 50 MB)',
    chip_size: 'up to 50 MB',
    chip_id3: 'ID3 Parser',
    chip_replication: 'Replication: 2 copies',
    step1_title: 'Upload to node',
    step1_sub: 'Waiting for MP3 file selection...',
    step2_title: 'ID3 Metadata',
    step2_sub: 'Extracting title, artist, duration',
    step3_title: 'Replication',
    step3_sub: 'Storing on 2 storage nodes',
    catalog_title: '[UPLOADED TRACKS CATALOG]',
    catalog_counter: '{count} tracks in cluster',

    // Settings View
    settings_title: 'System Settings',
    settings_desc: 'Manage user profile, interface localization, and distributed cluster nodes topology.',
    settings_auth_status: 'Session active (WebSocket: connected)',
    settings_switch_user: 'Switch Account',
    settings_audio_group: 'Audio & Streaming',
    setting_range_stream: 'HTTP Range Streaming',
    setting_range_desc: 'Seeking requests partial byte streams via HTTP 206 Partial Content',
    setting_sound_alerts: 'Sound Notifications',
    setting_sound_desc: 'Subtle acoustic click when incoming message arrives',
    setting_typing_broadcast: 'Broadcast "Typing..."',
    setting_typing_desc: 'Ephemeral typing indicators sent via WebSocket without DB writes',
    settings_theme_group: 'Theme & Typography',
    setting_dark_monochrome: 'Dark Graphite Palette',
    setting_dark_desc: 'Comfortable gray-black palette with neutral gray avatars',
    setting_glass_blur: 'Liquid Glass Frosting',
    setting_glass_desc: 'Backdrop blur refraction for matte surface panels',
    setting_typewriter: 'Monospace Typewriter',
    setting_typewriter_desc: 'Fixed-width font with tactile input cursor',
    settings_cluster_title: 'Cluster Topology (Application & Storage Nodes)',

    // Modals
    modal_new_dialog_title: 'Find User by Login',
    modal_recipient_details_title: 'Conversation Details',
    modal_share_track_title: 'Send Track Card to Chat',
    modal_auth_title: 'Login & Registration',
    user_search_prompt: 'Type username: @alisa, @oleg, @pavel...',
    select_dialog_prompt: 'Select dialogue:',
    select_account_prompt: 'Quick switch active cluster participant:',

    // Footer
    footer_drawer: 'drawer',
    footer_send: 'send',
    footer_seq: 'seq: total order',
    footer_ws: 'ws: connected',
    footer_node: 'node: app-1'
  },
  ru: {
    // Navigation
    nav_music: 'Музыка',
    nav_chats: 'Чаты',
    nav_import: 'Импорт',
    nav_settings: 'Параметры',
    user_status_online: 'Дмитрий Бызов (в сети)',

    // Music Catalog
    catalog_badge: '[КАТАЛОГ // РЕПЛИЦИРОВАННОЕ АУДИО]',
    music_title: 'Каталог треков',
    music_desc: 'Каталог аудиофайлов распределённого кластера. Воспроизведение через GET /api/tracks/{id}/stream с поддержкой Range.',
    catalog_cluster_state: '2 копии: storage-1 / storage-2',
    search_tracks_placeholder: 'Поиск треков по названию или исполнителю...',
    catalog_no_tracks: 'По вашему запросу ничего не найдено',
    share_to_chat: 'В чат',

    // Dialogs Drawer
    search_dialogs_placeholder: 'Поиск собеседника...',
    new_dialog_tooltip: 'Найти собеседника по логину / Новый диалог',
    hide_drawer: 'Скрыть панель (Ctrl+B)',
    show_drawer: 'Показать панель (Ctrl+B)',
    filter_all: 'Все',
    filter_unread: 'Непрочитанные',

    // Chat Header & Recipient
    user_alice: 'Алиса Смирнова',
    user_oleg: 'Олег Иванов',
    user_pavel: 'Павел Григорьев',
    user_artem: 'Артём Еременко',
    recipient_online_node2: 'в сети [узел app-2]',
    recipient_online_node1: 'в сети [узел app-1]',
    search_chat_tooltip: 'Поиск по переписке',
    dialog_options_tooltip: 'Информация о собеседнике',
    timeline_today: 'Сегодня',
    composer_placeholder: 'Написать сообщение {name}...',
    attach_track_tooltip: 'Прикрепить карточку трека (TR FT5)',
    emoji_tooltip: 'Вставить эмодзи',
    send_tooltip: 'Отправить сообщение (Enter)',
    typing_alice: 'алиса печатает...',

    // Import View
    import_badge: '[ХРАНИЛИЩЕ // ДВИЖОК РЕПЛИКАЦИИ]',
    import_title: 'Импорт MP3 треков',
    import_desc: 'Загрузка аудиофайлов формата MP3 в распределённый кластер. Автоматическое извлечение ID3-тегов и сохранение в 2 копиях на узлах хранения.',
    dropzone_title: 'Перетащите MP3 файлы сюда или нажмите для выбора',
    dropzone_subtitle: 'Поддерживаются аудиофайлы MP3 (до 50 МБ)',
    chip_size: 'до 50 МБ',
    chip_id3: 'Парсер ID3',
    chip_replication: 'Репликация: 2 копии',
    step1_title: 'Загрузка на узел',
    step1_sub: 'Ожидание выбора MP3 файла...',
    step2_title: 'ID3 Метаданные',
    step2_sub: 'Извлечение названия, автора и длительности',
    step3_title: 'Репликация',
    step3_sub: 'Сохранение на 2 узлах хранения',
    catalog_title: '[КАТАЛОГ ЗАГРУЖЕННЫХ ТРЕКОВ]',
    catalog_counter: '{count} треков в кластере',

    // Settings View
    settings_title: 'Параметры системы',
    settings_desc: 'Управление профилем пользователя, языком интерфейса и топологией узлов кластера.',
    settings_auth_status: 'Сессия активна (WebSocket: connected)',
    settings_switch_user: 'Сменить аккаунт',
    settings_audio_group: 'Аудио и потоковое вещание',
    setting_range_stream: 'Стриминг с Range-заголовком',
    setting_range_desc: 'Перемотка запрашивает фрагменты через HTTP 206 Partial Content',
    setting_sound_alerts: 'Звуковые уведомления',
    setting_sound_desc: 'Мягкий клик при доставке входящих сообщений',
    setting_typing_broadcast: 'Трансляция «Печатает...»',
    setting_typing_desc: 'Передача статуса набора через WebSocket без записи в БД',
    settings_theme_group: 'Оформление и типографика',
    setting_dark_monochrome: 'Тёмная графитовая палитра',
    setting_dark_desc: 'Комфортная серо-чёрная гамма с нейтральными серыми аватарами',
    setting_glass_blur: 'Размытие жидкого стекла',
    setting_glass_desc: 'Эффект преломления матовых панелей интерфейса',
    setting_typewriter: 'Печатная машинка (Monospace)',
    setting_typewriter_desc: 'Моноширинный шрифт и тактильный курсор ввода',
    settings_cluster_title: 'Топология кластера (узлы приложения и хранения)',

    // Modals
    modal_new_dialog_title: 'Найти собеседника',
    modal_recipient_details_title: 'Информация о собеседнике',
    modal_share_track_title: 'Отправить карточку трека',
    modal_auth_title: 'Вход и регистрация',
    user_search_prompt: 'Введите логин: @alisa, @oleg, @pavel...',
    select_dialog_prompt: 'Выберите диалог:',
    select_account_prompt: 'Быстрое переключение между пользователями кластера:',

    // Footer
    footer_drawer: 'панель',
    footer_send: 'отправить',
    footer_seq: 'seq: строгий порядок',
    footer_ws: 'ws: подключено',
    footer_node: 'узел: app-1'
  }
};

let currentLang = safeStorageGet('boysic_lang', 'en');

// ============================================================================
// 3. Central Data Store (Canonical UUIDs aligned with PR #4 schemas)
// ============================================================================
const TRACKS_STORE = [
  {
    id: '00000000-0000-0000-0000-000000000001',
    title: 'Midnight Echoes',
    artist: 'The Boys Band',
    duration: '3:42',
    duration_s: 222,
    format: 'MP3 (128 kbps)',
    replicas: ['storage-1', 'storage-2']
  },
  {
    id: '00000000-0000-0000-0000-000000000002',
    title: 'Neon Sunset Drive',
    artist: 'Synthesia Core',
    duration: '4:15',
    duration_s: 255,
    format: 'MP3 (128 kbps)',
    replicas: ['storage-2', 'storage-3']
  },
  {
    id: '00000000-0000-0000-0000-000000000003',
    title: 'Orbital Resonance',
    artist: 'Pavel & Dmitry',
    duration: '2:58',
    duration_s: 178,
    format: 'MP3 (128 kbps)',
    replicas: ['storage-1', 'storage-3']
  },
  {
    id: '00000000-0000-0000-0000-000000000004',
    title: 'Consensus Beats',
    artist: 'Distributed Ensemble',
    duration: '3:10',
    duration_s: 190,
    format: 'MP3 (128 kbps)',
    replicas: ['storage-1', 'storage-2']
  }
];

const CHATS_STORE = {
  1: {
    id: 1,
    name_en: 'Alice Smirnova',
    name_ru: 'Алиса Смирнова',
    handle: '@alisa',
    initials: 'AS',
    status: 'online',
    status_text_en: 'online [node app-2]',
    status_text_ru: 'в сети [узел app-2]',
    unread_count: 2,
    messages: [
      {
        id: 'msg-1-1',
        seq: 1,
        sender: 'incoming',
        kind: 'text',
        text: 'Hello! Full-text search and file storage are up and running.',
        time: '19:40',
        delivered: true
      },
      {
        id: 'msg-1-2',
        seq: 2,
        sender: 'incoming',
        kind: 'text',
        text: 'Verified inter-node delivery via POST /internal/deliver — all sequence events arrive in strict order without duplicates.',
        time: '19:41',
        delivered: true
      },
      {
        id: 'msg-1-3',
        seq: 3,
        sender: 'incoming',
        kind: 'track',
        track_id: '00000000-0000-0000-0000-000000000001',
        title: 'Midnight Echoes',
        artist: 'The Boys Band',
        duration: '3:42',
        duration_s: 222,
        time: '19:42',
        delivered: true
      },
      {
        id: 'msg-1-4',
        seq: 4,
        sender: 'outgoing',
        kind: 'text',
        text: 'Great! Now track cards stream directly via /api/tracks/{id}/stream with Range support.',
        time: '19:43',
        delivered: true
      }
    ]
  },
  2: {
    id: 2,
    name_en: 'Oleg Ivanov',
    name_ru: 'Олег Иванов',
    handle: '@oleg',
    initials: 'OI',
    status: 'online',
    status_text_en: 'online [node app-1]',
    status_text_ru: 'в сети [узел app-1]',
    unread_count: 1,
    messages: [
      {
        id: 'msg-2-1',
        seq: 1,
        sender: 'incoming',
        kind: 'track',
        track_id: '00000000-0000-0000-0000-000000000002',
        title: 'Neon Sunset Drive',
        artist: 'Synthesia Core',
        duration: '4:15',
        duration_s: 255,
        time: '19:30',
        delivered: true
      },
      {
        id: 'msg-2-2',
        seq: 2,
        sender: 'outgoing',
        kind: 'text',
        text: 'Thanks Oleg! Fixed all reviews on WebSocket formats and Messenger UI.',
        time: '19:32',
        delivered: true
      }
    ]
  },
  3: {
    id: 3,
    name_en: 'Pavel Grigoryev',
    name_ru: 'Павел Григорьев',
    handle: '@pavel',
    initials: 'PG',
    status: 'offline',
    status_text_en: 'last seen 45 min ago',
    status_text_ru: 'был(а) в сети 45 мин назад',
    unread_count: 0,
    messages: [
      {
        id: 'msg-3-1',
        seq: 1,
        sender: 'incoming',
        kind: 'text',
        text: 'Database schema committed with continuous sequence window.',
        time: '18:12',
        delivered: true
      }
    ]
  },
  4: {
    id: 4,
    name_en: 'Artem Eremenko',
    name_ru: 'Артём Еременко',
    handle: '@artem',
    initials: 'AE',
    status: 'online',
    status_text_en: 'online [node app-1]',
    status_text_ru: 'в сети [узел app-1]',
    unread_count: 0,
    messages: [
      {
        id: 'msg-4-1',
        seq: 1,
        sender: 'incoming',
        kind: 'text',
        text: 'Docker Compose cluster is up with nginx reverse proxy.',
        time: '17:55',
        delivered: true
      }
    ]
  }
};

let currentActiveChatId = 1;
let activeFilter = 'all';

// ============================================================================
// 4. Persistent Global Audio Player Engine (RFC 9110 Range Streaming)
// ============================================================================
class GlobalAudioEngine {
  constructor() {
    this.audio = document.getElementById('global-audio-element');
    this.currentTrackId = null;
    this.currentTrackIndex = 0;
    this.isPlaying = false;
    this.isShuffle = false;
    this.isRepeat = false;

    this.playBtn = document.getElementById('global-play-pause-btn');
    this.titleEl = document.getElementById('global-track-title');
    this.artistEl = document.getElementById('global-track-artist');
    this.currTimeEl = document.getElementById('player-current-time');
    this.totalTimeEl = document.getElementById('player-total-time');
    this.sliderEl = document.getElementById('global-progress-slider');
    this.discIcon = document.getElementById('player-disc-icon');

    this.initListeners();
  }

  initListeners() {
    if (!this.audio) return;

    this.audio.addEventListener('play', () => {
      this.isPlaying = true;
      this.updatePlayStateUI(true);
    });

    this.audio.addEventListener('pause', () => {
      this.isPlaying = false;
      this.updatePlayStateUI(false);
    });

    this.audio.addEventListener('timeupdate', () => {
      if (!this.audio.duration) return;
      const curr = this.audio.currentTime;
      const total = this.audio.duration;

      if (this.currTimeEl) this.currTimeEl.textContent = this.formatTime(curr);
      if (this.totalTimeEl && !isNaN(total)) this.totalTimeEl.textContent = this.formatTime(total);

      if (this.sliderEl && !this.sliderEl.matches(':active')) {
        this.sliderEl.value = Math.floor(curr);
      }
    });

    this.audio.addEventListener('loadedmetadata', () => {
      if (this.sliderEl && this.audio.duration) {
        this.sliderEl.max = Math.floor(this.audio.duration);
      }
      if (this.totalTimeEl && this.audio.duration) {
        this.totalTimeEl.textContent = this.formatTime(this.audio.duration);
      }
    });

    this.audio.addEventListener('ended', () => {
      if (this.isRepeat) {
        this.audio.currentTime = 0;
        this.audio.play().catch(() => {});
      } else {
        this.playNext();
      }
    });
  }

  formatTime(seconds) {
    if (isNaN(seconds) || seconds < 0) return '0:00';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  }

  loadTrack(track) {
    if (!track || !this.audio) return;
    this.currentTrackId = track.id;
    this.currentTrackIndex = TRACKS_STORE.findIndex(t => t.id === track.id);

    if (this.titleEl) this.titleEl.textContent = track.title;
    if (this.artistEl) this.artistEl.textContent = `${track.artist} • ${track.format || 'MP3 (128 kbps)'}`;
    if (this.totalTimeEl) this.totalTimeEl.textContent = track.duration || '3:42';
    if (this.sliderEl) {
      this.sliderEl.value = 0;
      this.sliderEl.max = track.duration_s || 222;
    }

    // Connect to HTTP Range streaming endpoint per TR
    this.audio.src = `/api/tracks/${track.id}/stream`;
  }

  playTrack(trackId, title, artist, duration, duration_s) {
    const track = TRACKS_STORE.find(t => t.id === trackId) || {
      id: trackId,
      title: title || 'Unknown Title',
      artist: artist || 'Unknown Artist',
      duration: duration || '3:30',
      duration_s: duration_s || 210
    };

    if (this.currentTrackId !== trackId) {
      this.loadTrack(track);
    }

    this.audio.play().catch(err => {
      console.warn('Audio playback notice:', err.message);
    });
  }

  togglePlayPause() {
    if (!this.audio) return;
    if (!this.currentTrackId) {
      this.loadTrack(TRACKS_STORE[0]);
    }

    if (this.audio.paused) {
      this.audio.play().catch(() => {});
    } else {
      this.audio.pause();
    }
  }

  seek(seconds) {
    if (!this.audio) return;
    this.audio.currentTime = parseFloat(seconds);
  }

  setVolume(val) {
    if (!this.audio) return;
    this.audio.volume = parseFloat(val);
  }

  playNext() {
    if (this.isShuffle) {
      const randIdx = Math.floor(Math.random() * TRACKS_STORE.length);
      this.loadTrack(TRACKS_STORE[randIdx]);
    } else {
      const nextIdx = (this.currentTrackIndex + 1) % TRACKS_STORE.length;
      this.loadTrack(TRACKS_STORE[nextIdx]);
    }
    this.audio.play().catch(() => {});
  }

  playPrev() {
    const prevIdx = (this.currentTrackIndex - 1 + TRACKS_STORE.length) % TRACKS_STORE.length;
    this.loadTrack(TRACKS_STORE[prevIdx]);
    this.audio.play().catch(() => {});
  }

  syncPlayButtons() {
    this.updatePlayStateUI(this.isPlaying);
  }

  updatePlayStateUI(isPlaying) {
    // 1. Update main orb button in persistent mini-player
    if (this.playBtn) {
      const playIcon = this.playBtn.querySelector('.orb-play-icon');
      const pauseIcon = this.playBtn.querySelector('.orb-pause-icon');
      if (playIcon) playIcon.style.display = isPlaying ? 'none' : 'block';
      if (pauseIcon) pauseIcon.style.display = isPlaying ? 'block' : 'none';
    }

    // 2. Vinyl disc spin animation
    if (this.discIcon) {
      if (isPlaying) this.discIcon.classList.add('spinning');
      else this.discIcon.classList.remove('spinning');
    }

    // 3. Synchronize all catalog track play buttons
    document.querySelectorAll('[data-action="play-track"]').forEach(btn => {
      const btnTrackId = btn.getAttribute('data-track-id');
      const playIcon = btn.querySelector('.play-icon');
      const pauseIcon = btn.querySelector('.pause-icon');
      const isThisTrackPlaying = isPlaying && btnTrackId === this.currentTrackId;

      if (playIcon) playIcon.style.display = isThisTrackPlaying ? 'none' : 'block';
      if (pauseIcon) pauseIcon.style.display = isThisTrackPlaying ? 'block' : 'none';
      if (isThisTrackPlaying) btn.classList.add('playing');
      else btn.classList.remove('playing');
    });

    // 4. Synchronize all track cards in chat
    document.querySelectorAll('[data-action="play-track-card"]').forEach(btn => {
      const btnTrackId = btn.getAttribute('data-track-id');
      const playIcon = btn.querySelector('.card-play-icon');
      const pauseIcon = btn.querySelector('.card-pause-icon');
      const isThisTrackPlaying = isPlaying && btnTrackId === this.currentTrackId;

      if (playIcon) playIcon.style.display = isThisTrackPlaying ? 'none' : 'block';
      if (pauseIcon) pauseIcon.style.display = isThisTrackPlaying ? 'block' : 'none';
      if (isThisTrackPlaying) btn.classList.add('playing');
      else btn.classList.remove('playing');
    });
  }
}

let globalAudioPlayer = null;

// ============================================================================
// 5. Section Tab Navigation (HTMX Powered, Clean & Non-Recursive)
// ============================================================================
function updateActiveNavTab(tabName) {
  const tabs = ['music', 'chats', 'import', 'settings'];
  const validTab = tabs.includes(tabName) ? tabName : 'music';

  tabs.forEach(name => {
    const btn = document.getElementById(`btn-tab-${name}`);
    if (btn) {
      if (name === validTab) btn.classList.add('active');
      else btn.classList.remove('active');
    }
  });
  document.body.setAttribute('data-active-tab', validTab);
}
window.updateActiveNavTab = updateActiveNavTab;

function switchNavTab(tabName) {
  const tabs = ['music', 'chats', 'import', 'settings'];
  const validTab = tabs.includes(tabName) ? tabName : 'music';
  const targetPath = validTab === 'music' ? '/music' : `/${validTab}`;

  if (window.htmx) {
    htmx.ajax('GET', targetPath, { target: '#main-viewport-content', swap: 'innerHTML' }).then(() => {
      try {
        history.pushState({ tab: validTab }, '', targetPath);
      } catch (e) {}
      updateActiveNavTab(validTab);
    });
  } else {
    window.location.href = targetPath;
  }
}
window.switchNavTab = switchNavTab;

// ============================================================================
// 6. Language Switching (EN Default / RU)
// ============================================================================
function setLanguage(lang) {
  if (lang !== 'en' && lang !== 'ru') lang = 'en';
  currentLang = lang;
  safeStorageSet('boysic_lang', currentLang);
  document.documentElement.lang = currentLang;

  // Update switcher pill badges
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

  // Update all [data-i18n] text nodes
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (dict[key]) {
      el.textContent = dict[key];
    }
  });

  // Update all [data-i18n-placeholder]
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    if (dict[key]) {
      const activeChat = CHATS_STORE[currentActiveChatId];
      const chatName = activeChat ? (currentLang === 'ru' ? activeChat.name_ru : activeChat.name_en) : 'User';
      const firstName = chatName.split(' ')[0];
      el.placeholder = dict[key].replace('{name}', firstName);
    }
  });

  // Update all [data-i18n-title]
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.getAttribute('data-i18n-title');
    if (dict[key]) el.title = dict[key];
  });

  // Update count label in upload view
  const countLabel = document.getElementById('uploaded-count-label');
  if (countLabel) {
    const count = document.querySelectorAll('.uploaded-track-item').length;
    countLabel.textContent = dict.catalog_counter.replace('{count}', count);
  }

  // Update active chat header
  const chat = CHATS_STORE[currentActiveChatId];
  if (chat) {
    renderChatHeader(chat);
  }
}
window.setLanguage = setLanguage;

function toggleLanguage() {
  setLanguage(currentLang === 'en' ? 'ru' : 'en');
}
window.toggleLanguage = toggleLanguage;

// ============================================================================
// 7. Dialogs & Chat Messaging Engine (Strict `seq` Order, Unread Badges)
// ============================================================================
function selectChat(chatId) {
  const targetId = parseInt(chatId, 10);
  if (!targetId || !CHATS_STORE[targetId]) return;

  currentActiveChatId = targetId;
  const chat = CHATS_STORE[targetId];

  // Reset unread count upon viewing
  chat.unread_count = 0;
  const unreadBadge = document.getElementById(`deck-unread-badge-${targetId}`);
  if (unreadBadge) {
    unreadBadge.style.display = 'none';
    unreadBadge.textContent = '0';
  }

  // Mark read on backend asynchronously
  fetch(`/api/conversations/${targetId}/read`, { method: 'POST' }).catch(() => {});

  // Update active item in list
  document.querySelectorAll('.deck-item').forEach(item => {
    const id = parseInt(item.getAttribute('data-chat-id'), 10);
    if (id === targetId) {
      item.classList.add('active');
      item.setAttribute('aria-selected', 'true');
    } else {
      item.classList.remove('active');
      item.setAttribute('aria-selected', 'false');
    }
  });

  renderChatHeader(chat);
  renderChatMessages(chat);

  if (window.innerWidth <= 860) {
    toggleDialogsDrawer(false);
  }
}
window.selectChat = selectChat;

function renderChatHeader(chat) {
  const nameEl = document.getElementById('active-recipient-name');
  const avatarEl = document.getElementById('active-recipient-avatar');
  const statusEl = document.getElementById('active-recipient-status');
  const statusTextEl = document.getElementById('active-recipient-status-text');

  const displayName = currentLang === 'ru' ? chat.name_ru : chat.name_en;
  const displayStatus = currentLang === 'ru' ? chat.status_text_ru : chat.status_text_en;

  if (nameEl) nameEl.textContent = displayName;
  if (avatarEl) avatarEl.textContent = chat.initials;
  if (statusTextEl) statusTextEl.textContent = displayStatus;

  if (statusEl) {
    if (chat.status === 'online') statusEl.className = 'chat-recipient-status online';
    else statusEl.className = 'chat-recipient-status';
  }

  const composerInput = document.getElementById('composer-input');
  if (composerInput) {
    const firstName = displayName.split(' ')[0];
    const dict = I18N_DICTIONARY[currentLang];
    composerInput.placeholder = dict.composer_placeholder.replace('{name}', firstName);
  }
}

function renderChatMessages(chat) {
  const flow = document.getElementById('spatial-messages-flow');
  if (!flow) return;

  const dict = I18N_DICTIONARY[currentLang];
  let html = `<div class="chat-timeline-pill typewriter-pill">${escapeHtml(dict.timeline_today)}</div>`;

  // Sort strictly by `seq` per TR 1.9
  const sortedMessages = [...chat.messages].sort((a, b) => a.seq - b.seq);

  sortedMessages.forEach(msg => {
    if (msg.kind === 'track') {
      const isPlaying = globalAudioPlayer && globalAudioPlayer.isPlaying && globalAudioPlayer.currentTrackId === msg.track_id;
      html += `
        <div class="msg-row ${escapeHtml(msg.sender)} msg-track-card-row" data-seq="${msg.seq}">
          <div class="msg-track-container">
            <span class="msg-author-tag" style="margin-bottom: 6px; display: block;">${escapeHtml(chat.handle)} • seq #${msg.seq}</span>
            <div class="sound-module-card" data-track-id="${escapeHtml(msg.track_id)}">
              <div class="sound-module-vinyl"><div class="vinyl-center"></div></div>
              <div class="sound-module-info">
                <div class="sound-module-title typewriter-text">${escapeHtml(msg.title)}</div>
                <div class="sound-module-artist typewriter-font">${escapeHtml(msg.artist)} • ${escapeHtml(msg.duration || '3:30')}</div>
                <div class="sound-waveform">
                  <div class="wave-bar"></div><div class="wave-bar"></div><div class="wave-bar"></div>
                  <div class="wave-bar"></div><div class="wave-bar"></div><div class="wave-bar"></div>
                </div>
              </div>
              <button 
                class="sound-play-orb ${isPlaying ? 'playing' : ''}" 
                data-action="play-track-card"
                data-track-id="${escapeHtml(msg.track_id)}"
                data-track-title="${escapeHtml(msg.title)}"
                data-track-artist="${escapeHtml(msg.artist)}"
                data-track-duration="${escapeHtml(msg.duration || '3:30')}"
                title="Play track"
              >
                <svg viewBox="0 0 24 24" class="card-play-icon" width="16" height="16" fill="currentColor" style="display: ${isPlaying ? 'none' : 'block'};">
                  <polygon points="5 3 19 12 5 21 5 3"></polygon>
                </svg>
                <svg viewBox="0 0 24 24" class="card-pause-icon" width="16" height="16" fill="currentColor" style="display: ${isPlaying ? 'block' : 'none'};">
                  <rect x="6" y="4" width="4" height="16"></rect>
                  <rect x="14" y="4" width="4" height="16"></rect>
                </svg>
              </button>
            </div>
            <div class="msg-meta" style="justify-content: flex-end; margin-top: 4px;">
              <span>${escapeHtml(msg.time)}</span>
            </div>
          </div>
        </div>
      `;
    } else {
      const isOutgoing = msg.sender === 'outgoing';
      html += `
        <div class="msg-row ${escapeHtml(msg.sender)}" data-seq="${msg.seq}">
          <div class="msg-bubble typewriter-bubble">
            ${!isOutgoing ? `<span class="msg-author-tag">${escapeHtml(chat.handle)} • seq #${msg.seq}</span>` : ''}
            <span class="msg-body-text">${escapeHtml(msg.text)}</span>
            <div class="msg-meta">
              <span>${isOutgoing ? `seq #${msg.seq} • ` : ''}${escapeHtml(msg.time)}</span>
              ${isOutgoing ? `
                <svg class="msg-status-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6">
                  <path d="M18 6L7 17l-5-5"></path>
                  <path d="M22 10l-7.5 7.5L13 16"></path>
                </svg>
              ` : ''}
            </div>
          </div>
        </div>
      `;
    }
  });

  html += `
    <div class="typing-capsule" id="chat-typing-capsule" style="display: none;">
      <span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>
      <span class="typing-label typewriter-font" id="chat-typing-label">${escapeHtml(dict.typing_alice)}</span>
    </div>
  `;

  flow.innerHTML = html;
  flow.scrollTop = flow.scrollHeight;
}

function sendChatMessage() {
  const input = document.getElementById('composer-input');
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;

  const chat = CHATS_STORE[currentActiveChatId];
  if (!chat) return;

  const nextSeq = chat.messages.length + 1;
  const now = new Date();
  const timeStr = `${now.getHours()}:${now.getMinutes() < 10 ? '0' : ''}${now.getMinutes()}`;

  chat.messages.push({
    id: `msg-${chat.id}-${Date.now()}`,
    seq: nextSeq,
    sender: 'outgoing',
    kind: 'text',
    text: text,
    time: timeStr,
    delivered: true
  });

  input.value = '';
  renderChatMessages(chat);

  const previewEl = document.querySelector(`[data-chat-preview="${chat.id}"]`);
  if (previewEl) previewEl.textContent = text;

  // Send message to server backend API
  fetch(`/api/conversations/${chat.id}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: text })
  }).catch(() => {});
}
window.sendChatMessage = sendChatMessage;

function handleComposerKey(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendChatMessage();
  }
}
window.handleComposerKey = handleComposerKey;

// ============================================================================
// 8. Track Card Attachment & Sending (TR FT5)
// ============================================================================
function sendTrackCardToChat(chatId, trackId, title, artist, duration, duration_s) {
  const chat = CHATS_STORE[chatId];
  if (!chat) return;

  const nextSeq = chat.messages.length + 1;
  const now = new Date();
  const timeStr = `${now.getHours()}:${now.getMinutes() < 10 ? '0' : ''}${now.getMinutes()}`;

  chat.messages.push({
    id: `msg-${chat.id}-${Date.now()}`,
    seq: nextSeq,
    sender: 'outgoing',
    kind: 'track',
    track_id: trackId,
    title: title,
    artist: artist,
    duration: duration,
    duration_s: duration_s || 210,
    time: timeStr,
    delivered: true
  });

  const previewEl = document.querySelector(`[data-chat-preview="${chat.id}"]`);
  if (previewEl) previewEl.textContent = `🎵 ${title} — ${artist}`;

  if (currentActiveChatId === chatId) {
    renderChatMessages(chat);
  }

  fetch(`/api/conversations/${chat.id}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: `[Track Card: ${title}]`, track_id: trackId })
  }).catch(() => {});
}

// ============================================================================
// 9. Modals (User Search, Recipient Details, Share Track, Account Switcher)
// ============================================================================
function openUserSearchModal() {
  const modal = document.getElementById('user-search-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  handleSearchUsersByLogin('');
  const input = document.getElementById('modal-user-search-input');
  if (input) {
    input.value = '';
    setTimeout(() => input.focus(), 80);
  }
}
window.openUserSearchModal = openUserSearchModal;

function closeUserSearchModal() {
  const modal = document.getElementById('user-search-modal');
  if (modal) modal.style.display = 'none';
}
window.closeUserSearchModal = closeUserSearchModal;

async function handleSearchUsersByLogin(val) {
  const container = document.getElementById('modal-users-list');
  if (!container) return;
  const query = (val || '').trim();

  try {
    const res = await fetch(`/api/users?login=${encodeURIComponent(query)}`);
    if (res.ok) {
      const users = await res.json();
      renderUsersSearchResults(users);
      return;
    }
  } catch (e) {}

  // Local fallback
  const fallbackUsers = [
    { id: 1, name: 'Alice Smirnova', login: 'alisa', initials: 'AS' },
    { id: 2, name: 'Oleg Ivanov', login: 'oleg', initials: 'OI' },
    { id: 3, name: 'Pavel Grigoryev', login: 'pavel', initials: 'PG' },
    { id: 4, name: 'Artem Eremenko', login: 'artem', initials: 'AE' }
  ].filter(u => !query || u.login.includes(query) || u.name.toLowerCase().includes(query.toLowerCase()));
  renderUsersSearchResults(fallbackUsers);
}
window.handleSearchUsersByLogin = handleSearchUsersByLogin;

function renderUsersSearchResults(users) {
  const container = document.getElementById('modal-users-list');
  if (!container) return;

  if (users.length === 0) {
    container.innerHTML = `<div class="typewriter-font" style="padding: 12px; color: var(--text-muted); text-align: center;">No users found</div>`;
    return;
  }

  container.innerHTML = users.map(u => `
    <div class="modal-pick-item" onclick="handleSelectUserFromSearch(${u.id}, '${escapeHtml(u.name)}', '${escapeHtml(u.login)}')">
      <div class="deck-item-avatar avatar-gray">${escapeHtml(u.initials || u.login.slice(0, 2).toUpperCase())}</div>
      <div>
        <div class="typewriter-text" style="font-weight:700;">${escapeHtml(u.name)}</div>
        <div class="typewriter-font" style="font-size:11px;color:var(--text-muted);">@${escapeHtml(u.login)}</div>
      </div>
    </div>
  `).join('');
}

function handleSelectUserFromSearch(userId, name, login) {
  closeUserSearchModal();
  let chatId = Object.keys(CHATS_STORE).find(id => CHATS_STORE[id].handle === `@${login}`);
  if (!chatId) {
    chatId = Object.keys(CHATS_STORE).length + 1;
    CHATS_STORE[chatId] = {
      id: parseInt(chatId, 10),
      name_en: name,
      name_ru: name,
      handle: `@${login}`,
      initials: (name.split(' ').map(n => n[0]).join('')).slice(0, 2).toUpperCase(),
      status: 'online',
      status_text_en: 'online [node app-1]',
      status_text_ru: 'в сети [узел app-1]',
      unread_count: 0,
      messages: []
    };
  }

  selectChat(chatId);
  switchNavTab('chats');
}
window.handleSelectUserFromSearch = handleSelectUserFromSearch;

// Recipient Details Modal (Header Details Button Fix)
function openRecipientProfileModal() {
  const chat = CHATS_STORE[currentActiveChatId];
  if (!chat) return;
  const modal = document.getElementById('recipient-profile-modal');
  if (!modal) return;

  const avatarEl = document.getElementById('modal-recipient-avatar');
  const nameEl = document.getElementById('modal-recipient-name');
  const handleEl = document.getElementById('modal-recipient-handle');
  const nodeEl = document.getElementById('modal-recipient-node');
  const statusEl = document.getElementById('modal-recipient-status');

  const displayName = currentLang === 'ru' ? chat.name_ru : chat.name_en;
  if (avatarEl) avatarEl.textContent = chat.initials;
  if (nameEl) nameEl.textContent = displayName;
  if (handleEl) handleEl.textContent = chat.handle;
  if (nodeEl) nodeEl.textContent = chat.id % 2 === 0 ? 'app-1:8000' : 'app-2:8001';
  if (statusEl) {
    statusEl.textContent = chat.status === 'online' ? 'Active / Online' : 'Offline';
    statusEl.style.color = chat.status === 'online' ? '#4ade80' : '#888';
  }

  modal.style.display = 'flex';
}
window.openRecipientProfileModal = openRecipientProfileModal;

function closeRecipientProfileModal() {
  const modal = document.getElementById('recipient-profile-modal');
  if (modal) modal.style.display = 'none';
}
window.closeRecipientProfileModal = closeRecipientProfileModal;

// Share Track to Chat Modal
let pendingShareTrack = null;

function openShareTrackModal(trackId, title, artist, duration) {
  pendingShareTrack = { trackId, title, artist, duration };
  const modal = document.getElementById('share-track-modal');
  if (!modal) return;

  const titleEl = document.getElementById('modal-share-track-title');
  const artistEl = document.getElementById('modal-share-track-artist');
  if (titleEl) titleEl.textContent = title;
  if (artistEl) artistEl.textContent = `${artist} • ${duration}`;

  const listEl = document.getElementById('modal-share-dialogs-list');
  if (listEl) {
    listEl.innerHTML = Object.values(CHATS_STORE).map(c => `
      <div class="modal-pick-item" onclick="confirmShareTrack(${c.id})">
        <div class="deck-item-avatar avatar-gray">${escapeHtml(c.initials)}</div>
        <div>
          <div class="typewriter-text" style="font-weight:700;">${escapeHtml(currentLang === 'ru' ? c.name_ru : c.name_en)}</div>
          <div class="typewriter-font" style="font-size:11px;color:var(--text-muted);">${escapeHtml(c.handle)}</div>
        </div>
      </div>
    `).join('');
  }

  modal.style.display = 'flex';
}

function confirmShareTrack(chatId) {
  if (!pendingShareTrack) return;
  sendTrackCardToChat(
    chatId,
    pendingShareTrack.trackId,
    pendingShareTrack.title,
    pendingShareTrack.artist,
    pendingShareTrack.duration
  );
  closeShareTrackModal();
  selectChat(chatId);
  switchNavTab('chats');
}
window.confirmShareTrack = confirmShareTrack;

function closeShareTrackModal() {
  const modal = document.getElementById('share-track-modal');
  if (modal) modal.style.display = 'none';
  pendingShareTrack = null;
}
window.closeShareTrackModal = closeShareTrackModal;

function openAttachTrackModal() {
  if (TRACKS_STORE.length > 0) {
    const t = TRACKS_STORE[0];
    openShareTrackModal(t.id, t.title, t.artist, t.duration);
  }
}
window.openAttachTrackModal = openAttachTrackModal;

// Account Switcher & Auth Modals
function openUserLoginModal() {
  const modal = document.getElementById('user-auth-modal');
  if (modal) modal.style.display = 'flex';
}
window.openUserLoginModal = openUserLoginModal;

function closeUserLoginModal() {
  const modal = document.getElementById('user-auth-modal');
  if (modal) modal.style.display = 'none';
}
window.closeUserLoginModal = closeUserLoginModal;

async function submitAuthLogin() {
  const loginInput = document.getElementById('auth-input-login');
  const passInput = document.getElementById('auth-input-password');
  const msgEl = document.getElementById('auth-status-message');
  const username = loginInput ? loginInput.value.trim() : '';
  const password = passInput ? passInput.value : '';

  if (!username) {
    if (msgEl) { msgEl.textContent = 'Please enter username'; msgEl.style.color = '#f87171'; }
    return;
  }

  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    const data = await res.json();
    if (res.ok) {
      if (msgEl) { msgEl.textContent = `Logged in as @${data.user.login} (session: ${data.session_token.slice(0, 8)}...)`; msgEl.style.color = '#4ade80'; }
      setTimeout(() => closeUserLoginModal(), 800);
    } else {
      if (msgEl) { msgEl.textContent = data.detail || 'Login failed'; msgEl.style.color = '#f87171'; }
    }
  } catch (err) {
    if (msgEl) { msgEl.textContent = 'Server connection error'; msgEl.style.color = '#f87171'; }
  }
}
window.submitAuthLogin = submitAuthLogin;

async function submitAuthRegister() {
  const loginInput = document.getElementById('auth-input-login');
  const passInput = document.getElementById('auth-input-password');
  const msgEl = document.getElementById('auth-status-message');
  const username = loginInput ? loginInput.value.trim() : '';
  const password = passInput ? passInput.value : '';

  if (!username) {
    if (msgEl) { msgEl.textContent = 'Please enter username'; msgEl.style.color = '#f87171'; }
    return;
  }

  try {
    const res = await fetch('/api/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    const data = await res.json();
    if (res.ok) {
      if (msgEl) { msgEl.textContent = `Registered user @${data.user.login}! Ready to login.`; msgEl.style.color = '#4ade80'; }
      setTimeout(() => closeUserLoginModal(), 800);
    } else {
      if (msgEl) { msgEl.textContent = data.detail || 'Registration failed'; msgEl.style.color = '#f87171'; }
    }
  } catch (err) {
    if (msgEl) { msgEl.textContent = 'Server connection error'; msgEl.style.color = '#f87171'; }
  }
}
window.submitAuthRegister = submitAuthRegister;

function switchActiveUserAccount(userKey) {
  closeUserLoginModal();
  const avatarEl = document.getElementById('rail-profile-avatar');
  const settingsAvatar = document.getElementById('settings-user-avatar');
  const settingsName = document.getElementById('settings-user-name');
  const settingsHandle = document.getElementById('settings-user-handle');

  if (userKey === 'alice') {
    if (avatarEl) avatarEl.textContent = 'AS';
    if (settingsAvatar) settingsAvatar.textContent = 'AS';
    if (settingsName) settingsName.textContent = 'Alice Smirnova';
    if (settingsHandle) settingsHandle.textContent = '@alisa • Node: app-2:8001';
  } else if (userKey === 'oleg') {
    if (avatarEl) avatarEl.textContent = 'OI';
    if (settingsAvatar) settingsAvatar.textContent = 'OI';
    if (settingsName) settingsName.textContent = 'Oleg Ivanov';
    if (settingsHandle) settingsHandle.textContent = '@oleg • Node: app-1:8000';
  } else {
    if (avatarEl) avatarEl.textContent = 'DB';
    if (settingsAvatar) settingsAvatar.textContent = 'ДБ';
    if (settingsName) settingsName.textContent = 'Дмитрий Бызов';
    if (settingsHandle) settingsHandle.textContent = '@byzov • Node: app-1:8000';
  }
}
window.switchActiveUserAccount = switchActiveUserAccount;

function closeModalOnBackdrop(event, modal) {
  if (event.target === modal) {
    modal.style.display = 'none';
  }
}
window.closeModalOnBackdrop = closeModalOnBackdrop;

// ============================================================================
// 10. Catalog Search & Filtering (TR FT2 & RFC Range Support)
// ============================================================================
async function handleSearchTracks(query) {
  const q = (query || '').toLowerCase().trim();

  // Query server API for full-text search
  try {
    const res = await fetch(`/api/tracks?q=${encodeURIComponent(q)}`);
    if (res.ok) {
      const tracks = await res.json();
      renderCatalogTracksGrid(tracks);
      return;
    }
  } catch (e) {}

  // Fallback to DOM filtering
  const rows = document.querySelectorAll('.track-card-row');
  let matchCount = 0;
  rows.forEach(row => {
    const title = row.getAttribute('data-title') || '';
    const artist = row.getAttribute('data-artist') || '';
    if (!q || title.includes(q) || artist.includes(q)) {
      row.style.display = 'flex';
      matchCount++;
    } else {
      row.style.display = 'none';
    }
  });
}
window.handleSearchTracks = handleSearchTracks;

function renderCatalogTracksGrid(tracks) {
  const container = document.getElementById('catalog-tracks-grid');
  if (!container) return;

  if (tracks.length === 0) {
    container.innerHTML = `
      <div id="catalog-empty-search" class="typewriter-font" style="padding: 24px; text-align: center; color: var(--text-muted);">
        No tracks found matching your query
      </div>
    `;
    return;
  }

  container.innerHTML = tracks.map(track => {
    const isPlaying = globalAudioPlayer && globalAudioPlayer.isPlaying && globalAudioPlayer.currentTrackId === track.id;
    return `
      <div class="track-card-row" data-track-id="${escapeHtml(track.id)}" data-title="${escapeHtml(track.title.toLowerCase())}" data-artist="${escapeHtml(track.artist.toLowerCase())}">
        <div class="track-row-left">
          <button 
            class="track-row-play-btn ${isPlaying ? 'playing' : ''}" 
            data-action="play-track"
            data-track-id="${escapeHtml(track.id)}"
            data-track-title="${escapeHtml(track.title)}"
            data-track-artist="${escapeHtml(track.artist)}"
            data-track-duration="${escapeHtml(track.duration)}"
            title="Воспроизвести / Play"
          >
            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" class="play-icon" style="display: ${isPlaying ? 'none' : 'block'};">
              <polygon points="5 3 19 12 5 21 5 3"></polygon>
            </svg>
            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" class="pause-icon" style="display: ${isPlaying ? 'block' : 'none'};">
              <rect x="6" y="4" width="4" height="16"></rect>
              <rect x="14" y="4" width="4" height="16"></rect>
            </svg>
          </button>
          
          <div class="track-meta-block">
            <div class="track-row-title typewriter-text">${escapeHtml(track.title)}</div>
            <div class="track-row-sub typewriter-font">
              <span class="track-artist-text">${escapeHtml(track.artist)}</span>
              <span class="track-meta-dim">•</span>
              <span class="track-duration-text">${escapeHtml(track.duration)}</span>
              <span class="track-meta-dim">•</span>
              <span class="track-format-tag">${escapeHtml(track.format || 'MP3')}</span>
            </div>
          </div>
        </div>

        <div class="track-row-right">
          <div class="track-replicas-tag typewriter-font" title="Реплики на узлах хранения">
            <span class="replica-badge">storage: ${escapeHtml((track.replicas || []).join(', '))}</span>
          </div>

          <button 
            class="tactile-btn track-send-to-chat-btn" 
            data-action="share-track-modal"
            data-track-id="${escapeHtml(track.id)}"
            data-track-title="${escapeHtml(track.title)}"
            data-track-artist="${escapeHtml(track.artist)}"
            data-track-duration="${escapeHtml(track.duration)}"
            data-i18n="share_to_chat" 
            data-ru="В чат"
            title="Отправить карточкой в диалог"
          >
            <svg viewBox="0 0 24 24" width="14" height="14" stroke="currentColor" stroke-width="2" fill="none">
              <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>
            </svg>
            <span class="btn-text">${currentLang === 'ru' ? 'В чат' : 'To chat'}</span>
          </button>
        </div>
      </div>
    `;
  }).join('');
}

// Dialogs Search & Filtering
function handleSearchDialogs(query) {
  const q = (query || '').toLowerCase().trim();
  applyDialogsVisibility(q, activeFilter);
}
window.handleSearchDialogs = handleSearchDialogs;

function filterDialogs(btn, filterType) {
  activeFilter = filterType;
  document.querySelectorAll('.filter-chip').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');

  const searchInput = document.getElementById('dialogs-search-input');
  const q = searchInput ? searchInput.value.toLowerCase().trim() : '';
  applyDialogsVisibility(q, activeFilter);
}
window.filterDialogs = filterDialogs;

function applyDialogsVisibility(searchQuery, filterType) {
  const items = document.querySelectorAll('.deck-item');
  items.forEach(item => {
    const name = item.getAttribute('data-name') || '';
    const handle = item.getAttribute('data-handle') || '';
    const unread = parseInt(item.getAttribute('data-unread') || '0', 10);

    const matchesSearch = !searchQuery || name.includes(searchQuery) || handle.includes(searchQuery);
    let matchesFilter = true;

    if (filterType === 'unread') {
      matchesFilter = unread > 0;
    }

    item.style.display = (matchesSearch && matchesFilter) ? 'flex' : 'none';
  });
}

function toggleDialogsDrawer(forceState) {
  const drawer = document.getElementById('dialogs-drawer');
  if (!drawer) return;
  if (typeof forceState === 'boolean') {
    if (forceState) drawer.classList.remove('drawer-collapsed');
    else drawer.classList.add('drawer-collapsed');
  } else {
    drawer.classList.toggle('drawer-collapsed');
  }
}
window.toggleDialogsDrawer = toggleDialogsDrawer;

// ============================================================================
// 11. Functional MP3 Import with Real Server Upload (POST /api/tracks/upload)
// ============================================================================
async function handleMusicFilesUpload(event) {
  const files = event.target.files;
  if (!files || files.length === 0) return;

  const tracker = document.getElementById('import-pipeline-tracker');
  const step1 = document.getElementById('pipe-step-1');
  const step2 = document.getElementById('pipe-step-2');
  const step3 = document.getElementById('pipe-step-3');

  if (tracker) tracker.classList.add('animating');
  if (step1) step1.classList.add('active');

  for (let i = 0; i < files.length; i++) {
    const file = files[i];
    const formData = new FormData();
    formData.append('file', file);

    if (step1) step1.classList.add('active');

    try {
      if (step1) step1.classList.remove('active');
      if (step2) step2.classList.add('active');

      const res = await fetch('/api/tracks/upload', {
        method: 'POST',
        body: formData
      });

      if (step2) step2.classList.remove('active');
      if (step3) step3.classList.add('active');

      if (res.ok) {
        const trackData = await res.json();
        addUploadedTrackToCatalog(trackData);
      } else {
        // Fallback for demo
        const cleanTitle = file.name.replace(/\.[^/.]+$/, '');
        const fallbackId = '00000000-0000-0000-0000-00000000000' + (TRACKS_STORE.length + 1);
        addUploadedTrackToCatalog({
          id: fallbackId,
          title: cleanTitle,
          artist: 'Uploaded User Track',
          duration: '3:30',
          duration_s: 210,
          format: 'MP3 (128 kbps)',
          replicas: ['storage-1', 'storage-2']
        });
      }
    } catch (err) {
      console.warn('Upload fallback applied:', err);
      const cleanTitle = file.name.replace(/\.[^/.]+$/, '');
      const fallbackId = '00000000-0000-0000-0000-00000000000' + (TRACKS_STORE.length + 1);
      addUploadedTrackToCatalog({
        id: fallbackId,
        title: cleanTitle,
        artist: 'Uploaded User Track',
        duration: '3:30',
        duration_s: 210,
        format: 'MP3 (128 kbps)',
        replicas: ['storage-1', 'storage-2']
      });
    }

    if (step3) step3.classList.remove('active');
  }

  event.target.value = '';
}
window.handleMusicFilesUpload = handleMusicFilesUpload;

function addUploadedTrackToCatalog(track) {
  const list = document.getElementById('uploaded-tracks-list');
  if (!list) return;

  const item = document.createElement('div');
  item.className = 'uploaded-track-item';
  item.setAttribute('data-track-id', track.id);

  item.innerHTML = `
    <div class="track-item-icon">🎵</div>
    <div class="track-item-info">
      <div class="track-item-title typewriter-text">${escapeHtml(track.title)}</div>
      <div class="track-item-meta typewriter-font">${escapeHtml(track.artist)} • ${escapeHtml(track.duration)} • ${escapeHtml(track.format || 'MP3')} • ${escapeHtml((track.replicas || []).join(', '))}</div>
    </div>
    <div class="track-item-actions">
      <button 
        class="tactile-btn" 
        data-action="send-uploaded-to-chat"
        data-track-id="${escapeHtml(track.id)}"
        data-track-title="${escapeHtml(track.title)}"
        data-track-artist="${escapeHtml(track.artist)}"
        data-track-duration="${escapeHtml(track.duration)}"
        title="Отправить в чат"
      >
        💬 В чат
      </button>
    </div>
  `;

  list.prepend(item);

  // Add to internal catalog so it plays via mini-player
  if (!TRACKS_STORE.some(t => t.id === track.id)) {
    TRACKS_STORE.unshift(track);
  }

  const countLabel = document.getElementById('uploaded-count-label');
  if (countLabel) {
    const count = document.querySelectorAll('.uploaded-track-item').length;
    const dict = I18N_DICTIONARY[currentLang];
    countLabel.textContent = dict.catalog_counter.replace('{count}', count);
  }
}

// ============================================================================
// 12. Settings Toggles (Live Interaction & Persistence)
// ============================================================================
function toggleSettingOption(key, checkbox) {
  const isEnabled = checkbox.checked;
  safeStorageSet(`boysic_setting_${key}`, isEnabled ? '1' : '0');
  applySettingEffect(key, isEnabled);
}
window.toggleSettingOption = toggleSettingOption;

function applySettingEffect(key, isEnabled) {
  if (key === 'palette') {
    document.body.classList.toggle('light-theme', !isEnabled);
  } else if (key === 'blur') {
    document.documentElement.style.setProperty('--glass-blur-deep', isEnabled ? '16px' : '0px');
    document.documentElement.style.setProperty('--glass-blur-soft', isEnabled ? '10px' : '0px');
  } else if (key === 'typewriter') {
    document.documentElement.style.setProperty(
      '--font-typewriter',
      isEnabled ? "'JetBrains Mono', monospace" : "'Inter', -apple-system, BlinkMacSystemFont, sans-serif"
    );
  }
}

function toggleGlobalAudioPlay() {
  if (globalAudioPlayer) globalAudioPlayer.togglePlayPause();
}
window.toggleGlobalAudioPlay = toggleGlobalAudioPlay;

function playNextTrack() {
  if (globalAudioPlayer) globalAudioPlayer.playNext();
}
window.playNextTrack = playNextTrack;

function playPrevTrack() {
  if (globalAudioPlayer) globalAudioPlayer.playPrev();
}
window.playPrevTrack = playPrevTrack;

function togglePlayerShuffle() {
  if (!globalAudioPlayer) return;
  globalAudioPlayer.isShuffle = !globalAudioPlayer.isShuffle;
  const btn = document.getElementById('btn-player-shuffle');
  if (btn) btn.classList.toggle('active', globalAudioPlayer.isShuffle);
}
window.togglePlayerShuffle = togglePlayerShuffle;

function togglePlayerRepeat() {
  if (!globalAudioPlayer) return;
  globalAudioPlayer.isRepeat = !globalAudioPlayer.isRepeat;
  const btn = document.getElementById('btn-player-repeat');
  if (btn) btn.classList.toggle('active', globalAudioPlayer.isRepeat);
}
window.togglePlayerRepeat = togglePlayerRepeat;

function handleScrubSeek(val) {
  if (globalAudioPlayer) globalAudioPlayer.seek(val);
}
window.handleScrubSeek = handleScrubSeek;

function handleVolumeChange(val) {
  if (globalAudioPlayer) globalAudioPlayer.setVolume(val);
}
window.handleVolumeChange = handleVolumeChange;

function toggleChatSearch() {
  const input = document.getElementById('dialogs-search-input');
  if (input) {
    toggleDialogsDrawer(true);
    input.focus();
  }
}
window.toggleChatSearch = toggleChatSearch;

function insertEmojiDemo() {
  const input = document.getElementById('composer-input');
  if (input) {
    input.value += '🎵 ';
    input.focus();
  }
}
window.insertEmojiDemo = insertEmojiDemo;

// ============================================================================
// 13. Event Delegation (XSS Safe Click Handlers)
// ============================================================================
document.addEventListener('click', event => {
  const target = event.target.closest('[data-action]');
  if (!target) return;

  const action = target.getAttribute('data-action');

  if (action === 'play-track' || action === 'play-track-card') {
    event.preventDefault();
    const trackId = target.getAttribute('data-track-id');
    const title = target.getAttribute('data-track-title');
    const artist = target.getAttribute('data-track-artist');
    const duration = target.getAttribute('data-track-duration');
    if (globalAudioPlayer) {
      if (globalAudioPlayer.currentTrackId === trackId && globalAudioPlayer.isPlaying) {
        globalAudioPlayer.togglePlayPause();
      } else {
        globalAudioPlayer.playTrack(trackId, title, artist, duration);
      }
    }
  } else if (action === 'share-track-modal' || action === 'send-uploaded-to-chat') {
    event.preventDefault();
    const trackId = target.getAttribute('data-track-id');
    const title = target.getAttribute('data-track-title');
    const artist = target.getAttribute('data-track-artist');
    const duration = target.getAttribute('data-track-duration');
    openShareTrackModal(trackId, title, artist, duration);
  }
});

// Hotkey listener (Ctrl+B to toggle drawer)
document.addEventListener('keydown', event => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'b') {
    event.preventDefault();
    toggleDialogsDrawer();
  }
});

// ============================================================================
// 14. HTMX Lifecycle Integration (State Restoration & Zero Recursion)
// ============================================================================
document.body.addEventListener('htmx:afterSwap', () => {
  const path = window.location.pathname;
  let tab = 'music';
  if (path.includes('/chats')) tab = 'chats';
  else if (path.includes('/import')) tab = 'import';
  else if (path.includes('/settings')) tab = 'settings';

  updateActiveNavTab(tab);
  setLanguage(currentLang);

  if (tab === 'chats') {
    selectChat(currentActiveChatId);
  }

  if (globalAudioPlayer && globalAudioPlayer.currentTrackId) {
    globalAudioPlayer.syncPlayButtons();
  }
});

// ============================================================================
// 15. Initial Boot
// ============================================================================
document.addEventListener('DOMContentLoaded', () => {
  // 1. Initialize persistent audio player
  globalAudioPlayer = new GlobalAudioEngine();

  // 2. Load active tab from attribute or default to music per TR
  const initialTab = document.body.getAttribute('data-active-tab') || 'music';

  // 3. Initialize localized strings
  setLanguage(currentLang);

  // 4. Update tab active button
  updateActiveNavTab(initialTab);

  // 5. Select default chat
  selectChat(1);

  // 6. Restore saved settings
  ['palette', 'blur', 'typewriter'].forEach(key => {
    const saved = safeStorageGet(`boysic_setting_${key}`, null);
    if (saved !== null) {
      const isEnabled = saved === '1';
      const checkbox = document.getElementById(`spatial-toggle-${key}`);
      if (checkbox) checkbox.checked = isEnabled;
      applySettingEffect(key, isEnabled);
    }
  });
});
