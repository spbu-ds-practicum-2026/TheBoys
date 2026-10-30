// Сессия клиента: связывает хранилище, WebSocket и REST. Здесь живёт протокол из ТР:
// сверка по ping, догрузка после пропуска, повтор неподтверждённых и прочитанных позиций после обрыва.

import { api } from './api.js';
import { Connection } from './ws.js';
import { Store } from './store.js';

const PAGE_SIZE = 50;

export class Session {
  constructor(userId) {
    this.userId = userId;
    this.store = new Store(userId);
    this.connection = new Connection({
      onEvent: (event) => this.handleEvent(event),
      onOpen: () => this.handleOpen(),
      onState: (state) => this.stateListeners.forEach((listener) => listener(state)),
    });
    this.stateListeners = new Set();
    this.currentId = null;      // диалог, открытый сейчас в разделе «Чаты»
    this.inflight = new Set();  // запросы sync, на которые ещё нет ответа
    this.reloading = false;
  }

  onState(listener) {
    this.stateListeners.add(listener);
    return () => this.stateListeners.delete(listener);
  }

  get state() {
    return this.connection.state;
  }

  async start() {
    await this.reloadConversations();
    this.connection.start();
  }

  // Список диалогов: добавляет незнакомые и поднимает known_seq, окна не трогает.
  async reloadConversations() {
    if (this.reloading) return;
    this.reloading = true;
    try {
      const response = await api.conversations();
      if (response.status === 401) { location.href = '/login'; return; }
      if (response.ok) {
        this.store.applyConversations(response.data);
        this.catchUp();
      }
    } catch {
      // Нет связи: список обновится при следующей сверке или переподключении.
    } finally {
      this.reloading = false;
    }
  }

  // После обрыва: заново открыть окно, повторить неподтверждённые, прочитанные позиции и сверку.
  handleOpen() {
    this.inflight.clear();
    this.store.resetReadPositions();
    for (const item of this.store.unconfirmed()) this.transmit(item);
    this.connection.send({ type: 'ping' });
    this.reloadConversations();
    if (this.currentId !== null) this.openConversation(this.currentId);
  }

  handleEvent(event) {
    switch (event.type) {
      case 'ack':
        this.afterApply(this.store.applyAck(event), event.conversation_id);
        break;
      case 'message':
        this.afterApply(this.store.applyMessage(event, event.conversation_id === this.currentId), event.conversation_id);
        break;
      case 'history':
        this.finishRequests(event.conversation_id);
        this.afterApply(this.store.applyHistory(event.conversation_id, event.messages, event.has_more), event.conversation_id);
        break;
      case 'dialog_sync': {
        const { needReload, forward } = this.store.applyDialogSync(event.dialogs);
        if (needReload) this.reloadConversations();
        for (const id of forward) this.syncForward(this.store.get(id));
        break;
      }
      case 'read_ack':
        if (this.store.applyReadAck(event).needReload) this.reloadConversations();
        break;
      case 'error':
        this.handleError(event);
        break;
      default:
        break;
    }
  }

  afterApply(result, conversationId) {
    if (result.needReload) { this.reloadConversations(); return; }
    const conv = this.store.get(conversationId);
    if (result.forwardSync) this.syncForward(conv);
    this.markRead(conv);
  }

  handleError(event) {
    if (event.code === 'UNAUTHORIZED') { location.href = '/login'; return; }
    if (event.client_msg_id) {
      this.store.markFailed(event.client_msg_id);
      return;
    }
    // Ошибка на read или sync: ответа history не будет, поэтому запрос можно будет повторить.
    this.inflight.clear();
    console.warn('WS error', event.code, event.message);
  }

  // Подгрузка: сообщения после конца окна, если known_seq его обогнал.
  catchUp() {
    for (const conv of this.store.convs.values()) {
      if (this.store.needsForwardSync(conv)) this.syncForward(conv);
    }
  }

  // Ответ history не говорит, на какой из запросов диалога он пришёл, поэтому освобождаем все направления.
  // Лишний повторный запрос безвреден: порции истории сливаются по seq.
  finishRequests(conversationId) {
    for (const flight of [...this.inflight]) {
      if (flight.startsWith(`${conversationId}:`)) this.inflight.delete(flight);
    }
  }

  requestHistory(conv, key, params) {
    const flight = `${conv.id}:${key}`;
    if (this.inflight.has(flight)) return;
    if (this.connection.send({ type: 'sync', conversation_id: conv.id, limit: PAGE_SIZE, ...params })) {
      this.inflight.add(flight);
    }
  }

  syncForward(conv) {
    this.requestHistory(conv, 'forward', { since_seq: this.store.windowEnd(conv) });
  }

  loadOlder(conv) {
    if (!conv.loaded || !conv.hasOlder) return;
    this.requestHistory(conv, 'older', { before_seq: this.store.windowStart(conv) });
  }

  // Диалог открывается с последних сообщений: before_seq = known_seq + 1.
  openConversation(id) {
    this.currentId = id;
    const conv = this.store.get(id);
    if (!conv) return;
    if (!conv.loaded) this.requestHistory(conv, 'initial', { before_seq: conv.knownSeq + 1 });
    else if (this.store.needsForwardSync(conv)) this.syncForward(conv);
    this.markRead(conv);
    this.store.emit();
  }

  closeConversation() {
    this.currentId = null;
  }

  // Прочитанным клиент сообщает конец окна — непрерывный отрезок без пропусков.
  markRead(conv) {
    if (!conv || conv.id !== this.currentId) return;
    const position = this.store.readPosition(conv);
    if (position === null) return;
    if (this.connection.send({ type: 'read', conversation_id: conv.id, up_to_seq: position })) {
      this.store.markReadSent(conv, position);
    }
  }

  // Найти собеседника и открыть диалог — существующий или новый.
  async openWithUser(user) {
    const response = await api.openConversation(user.id);
    if (!response.ok) return null;
    this.store.applyConversations([response.data]);
    return response.data.id;
  }

  sendText(conversationId, text) {
    this.queue(conversationId, 'text', { text }, { text });
  }

  sendTrack(conversationId, track) {
    this.queue(conversationId, 'track', { track_id: track.id }, {
      track_id: track.id, title: track.title, artist: track.artist, duration_s: track.duration_s,
    });
  }

  queue(conversationId, kind, wirePayload, payload) {
    const item = this.store.queueSend(conversationId, kind, wirePayload, payload, newClientMsgId());
    if (item) this.transmit(item);
  }

  // Без связи сообщение остаётся «отправляется» и уходит при переподключении с тем же client_msg_id.
  transmit(item) {
    this.connection.send({
      type: 'send_message',
      client_msg_id: item.clientMsgId,
      conversation_id: item.conversationId,
      kind: item.kind,
      payload: item.wirePayload,
    });
  }
}

// client_msg_id. crypto.randomUUID браузер даёт только в защищённом контексте (HTTPS или localhost);
// по адресу вида http://192.168.x.x собираем UUID v4 из crypto.getRandomValues — он доступен везде.
export function newClientMsgId(source = globalThis.crypto) {
  if (typeof source.randomUUID === 'function') return source.randomUUID();
  const bytes = source.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // версия 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // вариант RFC 4122
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
