// Мини-плеер. Стоит вне области, которую заменяет HTMX, поэтому музыка не прерывается при смене раздела.
// Перемотку обеспечивает браузер: он сам запрашивает нужную часть файла заголовком Range.

import { formatDuration } from './dom.js';

// Обрыв потока (ТР, технический сценарий 7, п. 2): плеер заново запрашивает трек и продолжает
// с той же позиции — браузер запросит файл с заголовком Range. Попыток несколько, с растущей паузой.
const STREAM_RETRY_DELAYS_MS = [1000, 2000, 4000];

export class Player {
  constructor() {
    this.root = document.getElementById('player');
    this.audio = document.getElementById('player-audio');
    this.title = document.getElementById('player-title');
    this.artist = document.getElementById('player-artist');
    this.toggleButton = document.getElementById('player-toggle');
    this.seek = document.getElementById('player-seek');
    this.current = document.getElementById('player-current');
    this.total = document.getElementById('player-total');
    this.volume = document.getElementById('player-volume');
    this.track = null;
    this.seeking = false;
    this.listeners = new Set();
    this.lastTime = 0;        // последняя позиция, до которой трек играл без ошибок
    this.resumeAt = null;     // позиция, с которой продолжить после повторного запроса
    this.retries = 0;
    this.failedAt = 0;        // позиция, на которой поток оборвался
    this.retryTimer = null;

    this.toggleButton.addEventListener('click', () => this.toggle());
    this.seek.addEventListener('pointerdown', () => { this.seeking = true; });
    this.seek.addEventListener('change', () => { this.seeking = false; });
    this.seek.addEventListener('input', () => {
      this.audio.currentTime = Number(this.seek.value);
      this.current.textContent = formatDuration(this.seek.value);
    });
    this.volume.addEventListener('input', () => {
      this.audio.volume = Number(this.volume.value);
      try { localStorage.setItem('player-volume', this.volume.value); } catch { /* не критично */ }
    });
    this.audio.addEventListener('timeupdate', () => {
      if (this.audio.error) return;
      this.lastTime = this.audio.currentTime;
      // Трек снова играет дальше места обрыва — попытки восстановления закончились успехом.
      // Событие playing для этого не подходит: Chromium присылает его из буфера ещё до ошибки.
      if (this.retries > 0 && this.lastTime > this.failedAt + 2) {
        this.retries = 0;
        this.artist.textContent = this.track.artist;
      }
      this.renderTime();
    });
    this.audio.addEventListener('loadedmetadata', () => {
      if (this.resumeAt !== null) {
        this.audio.currentTime = this.resumeAt;
        this.resumeAt = null;
        this.audio.play().catch(() => {});
      }
      this.renderTime();
    });
    this.audio.addEventListener('play', () => this.changed());
    this.audio.addEventListener('pause', () => this.changed());
    this.audio.addEventListener('ended', () => this.changed());
    this.audio.addEventListener('error', () => this.onError());

    try {
      const saved = localStorage.getItem('player-volume');
      if (saved !== null) this.volume.value = saved;
    } catch { /* не критично */ }
    this.audio.volume = Number(this.volume.value);
  }

  onChange(listener) {
    this.listeners.add(listener);
  }

  get playing() {
    return Boolean(this.track) && !this.audio.paused && !this.audio.ended;
  }

  // Тот же трек — пауза или продолжение, другой — загрузка с начала.
  play(track) {
    if (this.track && this.track.id === track.id) {
      this.toggle();
      return;
    }
    clearTimeout(this.retryTimer);
    this.retries = 0;
    this.lastTime = 0;
    this.resumeAt = null;
    this.track = track;
    this.title.textContent = track.title;
    this.artist.textContent = track.artist;
    this.root.classList.remove('is-idle');
    this.toggleButton.disabled = false;
    this.seek.disabled = false;
    this.seek.max = track.duration_s || 0;
    this.seek.value = 0;
    this.total.textContent = formatDuration(track.duration_s);
    this.audio.src = `/api/tracks/${encodeURIComponent(track.id)}/stream`;
    this.audio.play().catch(() => { /* ошибку покажет обработчик error */ });
    this.changed();
  }

  onError() {
    if (!this.track) return;
    if (this.retries === 0) this.failedAt = this.lastTime;
    if (this.retries < STREAM_RETRY_DELAYS_MS.length) {
      const delay = STREAM_RETRY_DELAYS_MS[this.retries];
      this.retries += 1;
      this.artist.textContent = 'Восстановление воспроизведения…';
      clearTimeout(this.retryTimer);
      this.retryTimer = setTimeout(() => this.reload(), delay);
    } else {
      this.artist.textContent = 'Не удалось воспроизвести трек';
    }
    this.changed();
  }

  // Повторный запрос трека с последней позиции, до которой он играл.
  reload() {
    if (!this.track) return;
    this.resumeAt = this.lastTime;
    this.audio.src = `/api/tracks/${encodeURIComponent(this.track.id)}/stream`;
  }

  // После ошибки «▶» не просто снимает паузу у сломанного <audio>, а заново запрашивает трек с той же позиции.
  toggle() {
    if (!this.track) return;
    if (this.audio.error) {
      clearTimeout(this.retryTimer);
      this.retries = 0;
      this.artist.textContent = this.track.artist;
      this.reload();
      return;
    }
    if (this.audio.paused) this.audio.play().catch(() => {});
    else this.audio.pause();
  }

  renderTime() {
    const duration = Number.isFinite(this.audio.duration) ? this.audio.duration : this.track?.duration_s || 0;
    this.seek.max = Math.floor(duration);
    this.total.textContent = formatDuration(duration);
    this.current.textContent = formatDuration(this.audio.currentTime);
    if (!this.seeking) this.seek.value = Math.floor(this.audio.currentTime);
  }

  changed() {
    this.root.classList.toggle('is-playing', this.playing);
    for (const listener of this.listeners) listener();
  }
}
