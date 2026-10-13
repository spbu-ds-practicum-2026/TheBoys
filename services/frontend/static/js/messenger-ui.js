/**
 * TheBoys Messenger — Spatial Island UI & Interactions
 */

// 1. Navigation Tab Switching (Dynamic Island Nav)
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

// 2. Spatial Dialog Selection
function selectSpatialDialog(element, userName, status, initials) {
  // Update active state in list
  document.querySelectorAll('.deck-item').forEach(item => item.classList.remove('active'));
  element.classList.add('active');

  // Update recipient header in canvas
  const nameEl = document.getElementById('active-recipient-name');
  const statusEl = document.getElementById('active-recipient-status');
  const avatarEl = document.getElementById('active-recipient-avatar');

  if (nameEl) nameEl.textContent = userName;
  if (avatarEl) avatarEl.textContent = initials || userName.slice(0, 2).toUpperCase();

  if (statusEl) {
    if (status === 'online') {
      statusEl.className = 'chat-recipient-status online';
      statusEl.innerHTML = '<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:currentColor;"></span> в сети';
    } else {
      statusEl.className = 'chat-recipient-status';
      statusEl.textContent = 'был(а) недавно';
    }
  }

  // Clear unread badge
  const badge = element.querySelector('.deck-item-badge');
  if (badge) badge.remove();
}

// 3. Quick Filter Chips
function filterDialogs(btn, filterType) {
  document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');

  const items = document.querySelectorAll('.deck-item');
  items.forEach(item => {
    if (filterType === 'all') {
      item.style.display = 'flex';
    } else if (filterType === 'tracks') {
      const hasTrack = item.querySelector('.deck-item-preview')?.textContent.includes('🎵');
      item.style.display = hasTrack ? 'flex' : 'none';
    } else if (filterType === 'unread') {
      const hasBadge = !!item.querySelector('.deck-item-badge');
      item.style.display = hasBadge ? 'flex' : 'none';
    }
  });
}

// 4. Send Message from Floating Composer
function handleSendSpatialMessage(event) {
  event.preventDefault();
  const input = document.getElementById('composer-input');
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;

  const flow = document.getElementById('spatial-messages-flow');
  const typingBubble = document.getElementById('spatial-typing-bubble');

  const now = new Date();
  const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

  // Outgoing Bubble (Sunset Gradient with double check)
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

  // Update preview in active deck item
  const activePreview = document.querySelector('.deck-item.active .deck-item-preview');
  if (activePreview) {
    activePreview.textContent = text;
  }
}

// 5. Sound Module Playback Demo
let isTrackPlaying = false;
function toggleSpatialTrack(button) {
  const card = document.getElementById('demo-sound-module');
  if (!card) return;
  const playIcon = button.querySelector('svg');
  isTrackPlaying = !isTrackPlaying;

  if (isTrackPlaying) {
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

// Scroll messages to bottom on initial load
document.addEventListener('DOMContentLoaded', () => {
  const flow = document.getElementById('spatial-messages-flow');
  if (flow) {
    flow.scrollTop = flow.scrollHeight;
  }
});
