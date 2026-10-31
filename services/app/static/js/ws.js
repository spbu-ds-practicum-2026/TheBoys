// WebSocket-подключение к /ws: автоматическое переподключение и регулярный ping (сверка диалогов).
// Ответ на ping — dialog_sync; если он не приходит, соединение считается мёртвым и открывается заново.

const PING_INTERVAL_MS = 15000;
const PONG_TIMEOUT_MS = 8000;
const BACKOFF_MS = [500, 1000, 2000, 4000, 8000];
const CLOSE_UNAUTHORIZED = 4401;
const CLOSE_FORBIDDEN_ORIGIN = 4403;

export class Connection {
  // handlers: { onEvent(event), onOpen(), onState(state) }
  // state: connecting | open | reconnecting | rejected (сервер отверг подключение окончательно)
  constructor(handlers) {
    this.handlers = handlers;
    this.socket = null;
    this.state = 'connecting';
    this.attempts = 0;
    this.pingTimer = null;
    this.pongTimer = null;
    this.retryTimer = null;
  }

  start() {
    this.open();
  }

  open() {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${scheme}://${location.host}/ws`);
    this.socket = socket;

    socket.onopen = () => {
      if (this.socket !== socket) return;
      this.setState('open');
      this.pingTimer = setInterval(() => this.ping(), PING_INTERVAL_MS);
      this.handlers.onOpen();
    };
    socket.onmessage = (message) => {
      if (this.socket !== socket) return;
      let event;
      try { event = JSON.parse(message.data); } catch { return; }
      if (event.type === 'dialog_sync') {
        // Пауза между попытками сбрасывается только после ответа узла: если узел принимает
        // подключение и сразу закрывает его, повторы не должны идти каждые полсекунды.
        this.attempts = 0;
        this.clearPongTimer();
      }
      this.handlers.onEvent(event);
    };
    socket.onclose = (closeEvent) => {
      if (this.socket !== socket) return;
      if (closeEvent.code === CLOSE_UNAUTHORIZED) {
        location.href = '/login';
        return;
      }
      if (closeEvent.code === CLOSE_FORBIDDEN_ORIGIN) {
        this.reject();
        return;
      }
      this.lost();
    };
  }

  // Недопустимый Origin: повторять подключение бессмысленно, остаётся сообщить об этом.
  reject() {
    const socket = this.socket;
    this.socket = null;
    clearInterval(this.pingTimer);
    clearTimeout(this.retryTimer);
    this.clearPongTimer();
    if (socket) socket.onopen = socket.onmessage = socket.onclose = null;
    this.setState('rejected');
  }

  // Соединение потеряно: останавливаем таймеры и пробуем снова с растущей паузой.
  lost() {
    const socket = this.socket;
    this.socket = null;
    clearInterval(this.pingTimer);
    this.clearPongTimer();
    if (socket) {
      socket.onopen = socket.onmessage = socket.onclose = null;
      try { socket.close(); } catch { /* уже закрыт */ }
    }
    this.setState('reconnecting');
    const delay = BACKOFF_MS[Math.min(this.attempts, BACKOFF_MS.length - 1)];
    this.attempts += 1;
    this.retryTimer = setTimeout(() => this.open(), delay + Math.random() * 250);
  }

  ping() {
    if (!this.send({ type: 'ping' })) return;
    this.clearPongTimer();
    this.pongTimer = setTimeout(() => this.lost(), PONG_TIMEOUT_MS);
  }

  clearPongTimer() {
    clearTimeout(this.pongTimer);
    this.pongTimer = null;
  }

  send(payload) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return false;
    this.socket.send(JSON.stringify(payload));
    return true;
  }

  setState(state) {
    if (this.state === state) return;
    this.state = state;
    this.handlers.onState(state);
  }
}
