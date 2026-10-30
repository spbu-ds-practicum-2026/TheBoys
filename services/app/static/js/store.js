// Состояние клиента: диалоги, окно истории, known_seq, непрочитанные и очередь неподтверждённых сообщений.
// Чистая логика без DOM и сети — правила из ТР («Синхронизация истории на клиенте», сценарии 5 и 6).
//
// Окно диалога — непрерывный отрезок сообщений по seq без пропусков. Растёт вверх порциями истории
// и вниз следующим по номеру сообщением: полученным или своим подтверждённым.

export class Store {
  constructor(selfId, clock = () => Date.now()) {
    this.selfId = selfId;
    this.clock = clock;
    this.convs = new Map();
    this.listeners = new Set();
  }

  onChange(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  emit() {
    for (const listener of this.listeners) listener();
  }

  get(id) {
    return this.convs.get(id);
  }

  list() {
    return [...this.convs.values()].sort((a, b) => b.activity - a.activity || a.id - b.id);
  }

  ensure(id, peer) {
    let conv = this.convs.get(id);
    if (!conv) {
      conv = {
        id, peer, knownSeq: 0, unread: 0, activity: 0, reportedRead: 0,
        loaded: false, hasOlder: true, messages: [], pending: [],
      };
      this.convs.set(id, conv);
    }
    return conv;
  }

  windowStart(conv) {
    return conv.messages.length ? conv.messages[0].seq : 0;
  }

  windowEnd(conv) {
    return conv.messages.length ? conv.messages[conv.messages.length - 1].seq : 0;
  }

  // known_seq обогнал конец окна — клиент догружает сообщения после конца окна.
  needsForwardSync(conv) {
    return conv.loaded && conv.knownSeq > this.windowEnd(conv);
  }

  // Список диалогов: добавляет незнакомые и поднимает known_seq известных, окна не трогает.
  applyConversations(list) {
    for (const item of list) {
      const conv = this.ensure(item.id, item.peer);
      conv.peer = item.peer;
      conv.knownSeq = Math.max(conv.knownSeq, item.last_seq);
      conv.unread = item.unread_count;
    }
    this.emit();
  }

  // Сверка (ответ на ping). Незнакомый диалог → нужно перезагрузить список диалогов.
  applyDialogSync(dialogs) {
    let needReload = false;
    const forward = [];
    for (const item of dialogs) {
      const conv = this.convs.get(item.conversation_id);
      if (!conv) { needReload = true; continue; }
      conv.knownSeq = Math.max(conv.knownSeq, item.last_seq);
      conv.unread = item.unread_count;
      if (this.needsForwardSync(conv)) forward.push(conv.id);
    }
    this.emit();
    return { needReload, forward };
  }

  // Доставленное сообщение. isOpen — диалог сейчас открыт у пользователя.
  applyMessage(raw, isOpen = false) {
    const conv = this.convs.get(raw.conversation_id);
    if (!conv) return { needReload: true, forwardSync: false };

    const message = normalize(raw);
    const previousKnown = conv.knownSeq;
    conv.knownSeq = Math.max(conv.knownSeq, message.seq);
    conv.activity = this.clock();

    let inWindow = conv.messages.some((m) => m.seq === message.seq);
    if (conv.loaded && !inWindow && message.seq === this.windowEnd(conv) + 1) {
      conv.messages.push(message);
      inWindow = true;
    }

    const pending = conv.pending.find((p) => p.clientMsgId === message.clientMsgId);
    if (pending) {
      if (inWindow) conv.pending.splice(conv.pending.indexOf(pending), 1);
      else { pending.status = 'sent'; pending.seq = message.seq; }
    }

    // Не открытый диалог: новое сообщение собеседника прибавляет единицу к счётчику.
    // Точное значение клиент получит с сервера (список диалогов, ответ на ping, read_ack).
    const own = message.senderId === this.selfId;
    if (!own && !isOpen && message.seq > previousKnown) conv.unread += 1;

    this.emit();
    return { needReload: false, forwardSync: this.needsForwardSync(conv) };
  }

  // Подтверждение своего сообщения: приносит seq, содержимое берём из очереди.
  applyAck(ack) {
    const conv = this.convs.get(ack.conversation_id);
    if (!conv) return { needReload: true, forwardSync: false };

    conv.knownSeq = Math.max(conv.knownSeq, ack.seq);
    const pending = conv.pending.find((p) => p.clientMsgId === ack.client_msg_id);
    if (pending) {
      const inWindow = conv.messages.some((m) => m.seq === ack.seq);
      if (conv.loaded && (inWindow || ack.seq === this.windowEnd(conv) + 1)) {
        if (!inWindow) {
          conv.messages.push({
            seq: ack.seq, senderId: this.selfId, clientMsgId: pending.clientMsgId,
            kind: pending.kind, payload: pending.payload, createdAt: ack.created_at,
          });
        }
        conv.pending.splice(conv.pending.indexOf(pending), 1);
      } else {
        // Между окном и этим сообщением есть чужие: оно остаётся внизу, пока их не догрузят.
        pending.status = 'sent';
        pending.seq = ack.seq;
        pending.createdAt = ack.created_at;
      }
    }
    this.emit();
    return { needReload: false, forwardSync: this.needsForwardSync(conv) };
  }

  // Порция истории (ответ на sync). Принимается, только если стыкуется с окном или окно пусто.
  // more — сервер сообщил, что после порции есть ещё сообщения (has_more при выборке вперёд).
  applyHistory(conversationId, rawMessages, hasMore) {
    const conv = this.convs.get(conversationId);
    if (!conv) return { needReload: true, forwardSync: false };

    const incoming = rawMessages.map(normalize).sort((a, b) => a.seq - b.seq);
    let forwardChunk = false;

    if (!conv.loaded) {
      conv.messages = incoming;
      conv.loaded = true;
      conv.hasOlder = incoming.length > 0 && hasMore;
    } else if (incoming.length) {
      const start = this.windowStart(conv);
      const end = this.windowEnd(conv);
      const first = incoming[0].seq;
      const last = incoming[incoming.length - 1].seq;
      if (last >= start - 1 && first <= end + 1) {
        const bySeq = new Map(conv.messages.map((m) => [m.seq, m]));
        for (const m of incoming) bySeq.set(m.seq, m);
        conv.messages = [...bySeq.values()].sort((a, b) => a.seq - b.seq);
        if (first < start) conv.hasOlder = hasMore;
        else forwardChunk = true;
      }
    }
    if (this.windowStart(conv) === 1) conv.hasOlder = false;

    if (incoming.length) {
      conv.knownSeq = Math.max(conv.knownSeq, incoming[incoming.length - 1].seq);
    }
    // Свои сообщения, которые пришли в истории, больше не «ожидают».
    const seqs = new Set(conv.messages.map((m) => m.seq));
    conv.pending = conv.pending.filter((p) => !(p.seq && seqs.has(p.seq)));

    this.emit();
    return {
      needReload: false,
      forwardSync: this.needsForwardSync(conv) || (forwardChunk && hasMore),
    };
  }

  applyReadAck(ack) {
    const conv = this.convs.get(ack.conversation_id);
    if (!conv) return { needReload: true };
    conv.unread = ack.unread_count;
    this.emit();
    return { needReload: false };
  }

  // Конец окна, если он больше уже отправленной прочитанной позиции.
  readPosition(conv) {
    const end = this.windowEnd(conv);
    return conv.loaded && end > conv.reportedRead ? end : null;
  }

  markReadSent(conv, seq) {
    conv.reportedRead = Math.max(conv.reportedRead, seq);
  }

  // После переподключения прочитанные позиции повторяются.
  resetReadPositions() {
    for (const conv of this.convs.values()) conv.reportedRead = 0;
  }

  queueSend(conversationId, kind, wirePayload, payload, clientMsgId) {
    const conv = this.convs.get(conversationId);
    if (!conv) return null;
    const item = {
      conversationId, clientMsgId, kind, wirePayload, payload,
      status: 'sending', seq: null, createdAt: new Date(this.clock()).toISOString(),
    };
    conv.pending.push(item);
    conv.activity = this.clock();
    this.emit();
    return item;
  }

  // Неподтверждённые сообщения: повторяются с теми же client_msg_id.
  unconfirmed() {
    const items = [];
    for (const conv of this.convs.values()) {
      for (const p of conv.pending) if (p.status === 'sending') items.push(p);
    }
    return items;
  }

  markFailed(clientMsgId) {
    for (const conv of this.convs.values()) {
      const item = conv.pending.find((p) => p.clientMsgId === clientMsgId);
      if (item) { item.status = 'failed'; this.emit(); return; }
    }
  }

  // Что показывать в окне диалога: сообщения окна по seq, затем ожидающие.
  timeline(conv) {
    const sent = conv.messages.map((m) => ({ ...m, state: 'ok', own: m.senderId === this.selfId }));
    const waiting = conv.pending.map((p) => ({
      seq: p.seq, senderId: this.selfId, clientMsgId: p.clientMsgId, kind: p.kind,
      payload: p.payload, createdAt: p.createdAt, state: p.status, own: true,
    }));
    return [...sent, ...waiting];
  }
}

function normalize(raw) {
  return {
    seq: raw.seq,
    senderId: raw.sender_id,
    clientMsgId: raw.client_msg_id,
    kind: raw.kind,
    payload: raw.payload,
    createdAt: raw.created_at,
  };
}
