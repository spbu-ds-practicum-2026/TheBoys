/**
 * TheBoys Messenger — UI Interactions & Liquid Glass Preview
 */

// Tab Switching
function switchTab(tabName) {
  const chatsTabBtn = document.getElementById('tab-chats-btn');
  const settingsTabBtn = document.getElementById('tab-settings-btn');
  const viewChats = document.getElementById('view-chats');
  const viewSettings = document.getElementById('view-settings');

  if (tabName === 'chats') {
    chatsTabBtn.classList.add('active');
    settingsTabBtn.classList.remove('active');
    viewChats.style.display = 'flex';
    viewSettings.style.display = 'none';
  } else if (tabName === 'settings') {
    settingsTabBtn.classList.add('active');
    chatsTabBtn.classList.remove('active');
    viewChats.style.display = 'none';
    viewSettings.style.display = 'flex';
  }
}

// Dialog Selection
function selectDialog(element, userName, status) {
  // Update active state in list
  document.querySelectorAll('.dialog-item').forEach(item => item.classList.remove('active'));
  element.classList.add('active');

  // Update header
  const nameEl = document.getElementById('active-chat-name');
  const statusEl = document.getElementById('active-chat-status');
  const avatarEl = document.getElementById('active-chat-avatar');

  if (nameEl) nameEl.textContent = userName;
  
  if (statusEl) {
    if (status === 'online') {
      statusEl.className = 'chat-header-status online';
      statusEl.innerHTML = '<span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:currentColor;"></span> в сети';
    } else {
      statusEl.className = 'chat-header-status';
      statusEl.textContent = 'был(а) недавно';
    }
  }

  // Update avatar initials & gradient
  if (avatarEl) {
    const initials = userName.split(' ').map(n => n[0]).join('');
    avatarEl.childNodes[0].nodeValue = initials;
  }

  // Clear unread badge on click
  const unreadBadge = element.querySelector('.dialog-unread');
  if (unreadBadge) {
    unreadBadge.remove();
  }
}

// Send Message Demo
function handleSendMessage(event) {
  event.preventDefault();
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;

  const messagesStream = document.getElementById('messages-stream');
  const typingIndicator = document.getElementById('typing-indicator');

  const now = new Date();
  const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`;

  // Create Outgoing Bubble
  const messageRow = document.createElement('div');
  messageRow.className = 'message-row outgoing';
  messageRow.innerHTML = `
    <div class="message-bubble">
      ${escapeHtml(text)}
      <div class="message-footer">
        <span class="message-time">${timeStr}</span>
        <svg class="message-status-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <path d="M18 6L7 17l-5-5"></path>
          <path d="M22 10l-7.5 7.5L13 16"></path>
        </svg>
      </div>
    </div>
  `;

  // Insert before typing indicator
  messagesStream.insertBefore(messageRow, typingIndicator);
  input.value = '';

  // Scroll to bottom
  messagesStream.scrollTop = messagesStream.scrollHeight;

  // Update preview in active dialog
  const activeDialog = document.querySelector('.dialog-item.active .dialog-preview');
  if (activeDialog) {
    activeDialog.textContent = text;
  }
}

// Audio Track Playback Demo
let isPlaying = false;
function toggleTrackPlayback(button) {
  const card = document.getElementById('demo-track-card');
  const playIcon = button.querySelector('svg');
  isPlaying = !isPlaying;

  if (isPlaying) {
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

// Realtime Glass Settings Toggles
function toggleBlurEffect(checkbox) {
  const root = document.documentElement;
  if (checkbox.checked) {
    root.style.setProperty('--glass-blur-strength', 'blur(28px) saturate(190%)');
  } else {
    root.style.setProperty('--glass-blur-strength', 'blur(0px) saturate(100%)');
  }
}

function toggleOrbs(checkbox) {
  const orbs = document.querySelector('.liquid-background');
  if (orbs) {
    orbs.style.display = checkbox.checked ? 'block' : 'none';
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

// Auto scroll messages to bottom on load
document.addEventListener('DOMContentLoaded', () => {
  const messagesStream = document.getElementById('messages-stream');
  if (messagesStream) {
    messagesStream.scrollTop = messagesStream.scrollHeight;
  }
});

