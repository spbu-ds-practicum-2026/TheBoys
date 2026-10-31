import test from 'node:test';
import assert from 'node:assert/strict';
import { Store } from '../../static/js/store.js';

const ME = 1;
const PEER = 2;
const CONV = 10;

function makeStore() {
  const store = new Store(ME, () => 1000);
  store.applyConversations([{ conversation_id: CONV, peer: { id: PEER, login: 'bob' }, last_seq: 0, unread_count: 0 }]);
  return store;
}

function msg(seq, sender = PEER, extra = {}) {
  return {
    type: 'message', conversation_id: CONV, seq, sender_id: sender,
    client_msg_id: extra.client_msg_id ?? `id-${seq}`, kind: 'text',
    payload: { text: `m${seq}` }, created_at: '2026-10-29T12:00:00Z',
  };
}

function seqs(store) {
  return store.get(CONV).messages.map((m) => m.seq);
}

test('диалог открывается с последних сообщений, старые подгружаются вверх', () => {
  const store = makeStore();
  store.applyConversations([{ conversation_id: CONV, peer: { id: PEER, login: 'bob' }, last_seq: 6, unread_count: 2 }]);
  store.applyHistory(CONV, [msg(5), msg(6)], true);
  assert.deepEqual(seqs(store), [5, 6]);
  assert.equal(store.get(CONV).hasOlder, true);

  store.applyHistory(CONV, [msg(3), msg(4)], true);
  assert.deepEqual(seqs(store), [3, 4, 5, 6]);

  store.applyHistory(CONV, [msg(1), msg(2)], false);
  assert.deepEqual(seqs(store), [1, 2, 3, 4, 5, 6]);
  assert.equal(store.get(CONV).hasOlder, false);
});

test('окно растёт вниз следующим по номеру сообщением', () => {
  const store = makeStore();
  store.applyHistory(CONV, [msg(1), msg(2)], false);
  const result = store.applyMessage(msg(3), true);
  assert.deepEqual(seqs(store), [1, 2, 3]);
  assert.equal(result.forwardSync, false);
});

test('сообщение через пропуск не попадает в окно и требует догрузки', () => {
  const store = makeStore();
  store.applyHistory(CONV, [msg(1), msg(2)], false);
  const result = store.applyMessage(msg(5), true);
  assert.deepEqual(seqs(store), [1, 2]);
  assert.equal(store.get(CONV).knownSeq, 5);
  assert.equal(result.forwardSync, true);

  store.applyHistory(CONV, [msg(3), msg(4), msg(5)], false);
  assert.deepEqual(seqs(store), [1, 2, 3, 4, 5]);
  assert.equal(store.needsForwardSync(store.get(CONV)), false);
});

test('повторно полученное сообщение узнаётся по seq', () => {
  const store = makeStore();
  store.applyHistory(CONV, [msg(1), msg(2)], false);
  store.applyMessage(msg(2), true);
  store.applyMessage(msg(1), true);
  assert.deepEqual(seqs(store), [1, 2]);
});

test('сообщение незнакомого диалога просит перезагрузить список диалогов', () => {
  const store = makeStore();
  const result = store.applyMessage({ ...msg(1), conversation_id: 99 }, false);
  assert.equal(result.needReload, true);
  assert.equal(store.get(99), undefined);
});

test('сверка по незнакомому диалогу просит перезагрузку, по известному — поднимает known_seq и счётчик', () => {
  const store = makeStore();
  const { needReload } = store.applyDialogSync([
    { conversation_id: CONV, last_seq: 4, unread_count: 3 },
    { conversation_id: 77, last_seq: 1, unread_count: 1 },
  ]);
  assert.equal(needReload, true);
  assert.equal(store.get(CONV).knownSeq, 4);
  assert.equal(store.get(CONV).unread, 3);
});

test('сверка находит потерянное последнее сообщение: known_seq обгоняет конец окна', () => {
  const store = makeStore();
  store.applyHistory(CONV, [msg(1), msg(2)], false);
  const { forward } = store.applyDialogSync([{ conversation_id: CONV, last_seq: 3, unread_count: 1 }]);
  assert.deepEqual(forward, [CONV]);
});

test('known_seq только растёт', () => {
  const store = makeStore();
  store.applyConversations([{ conversation_id: CONV, peer: { id: PEER, login: 'bob' }, last_seq: 8, unread_count: 0 }]);
  store.applyDialogSync([{ conversation_id: CONV, last_seq: 5, unread_count: 0 }]);
  store.applyConversations([{ conversation_id: CONV, peer: { id: PEER, login: 'bob' }, last_seq: 3, unread_count: 0 }]);
  assert.equal(store.get(CONV).knownSeq, 8);
});

test('перезагрузка списка диалогов не трогает окно', () => {
  const store = makeStore();
  store.applyHistory(CONV, [msg(1), msg(2)], false);
  store.applyConversations([{ conversation_id: CONV, peer: { id: PEER, login: 'bob' }, last_seq: 4, unread_count: 2 }]);
  assert.deepEqual(seqs(store), [1, 2]);
  assert.equal(store.get(CONV).knownSeq, 4);
});

test('счётчик: сообщение собеседника в закрытом диалоге прибавляет единицу, своё и повтор — нет', () => {
  const store = makeStore();
  store.applyMessage(msg(1, PEER), false);
  assert.equal(store.get(CONV).unread, 1);
  store.applyMessage(msg(1, PEER), false);
  assert.equal(store.get(CONV).unread, 1);
  store.applyMessage(msg(2, ME), false);
  assert.equal(store.get(CONV).unread, 1);
  store.applyMessage(msg(3, PEER), true);
  assert.equal(store.get(CONV).unread, 1);
});

test('read_ack задаёт точный счётчик', () => {
  const store = makeStore();
  store.applyMessage(msg(1, PEER), false);
  store.applyReadAck({ conversation_id: CONV, last_read_seq: 1, unread_count: 0 });
  assert.equal(store.get(CONV).unread, 0);
});

test('прочитанная позиция — конец окна, повторно не отправляется, после переподключения отправляется снова', () => {
  const store = makeStore();
  store.applyHistory(CONV, [msg(1), msg(2)], false);
  const conv = store.get(CONV);
  assert.equal(store.readPosition(conv), 2);
  store.markReadSent(conv, 2);
  assert.equal(store.readPosition(conv), null);
  store.applyMessage(msg(3), true);
  assert.equal(store.readPosition(conv), 3);
  store.markReadSent(conv, 3);
  store.resetReadPositions();
  assert.equal(store.readPosition(conv), 3);
});

test('позиция прочтения не перепрыгивает через пропуск', () => {
  const store = makeStore();
  store.applyHistory(CONV, [msg(1), msg(2)], false);
  store.applyMessage(msg(5), true);
  assert.equal(store.readPosition(store.get(CONV)), 2);
});

test('своё сообщение: «отправляется» до подтверждения, затем встаёт в окно по seq', () => {
  const store = makeStore();
  store.applyHistory(CONV, [msg(1)], false);
  store.queueSend(CONV, 'text', { text: 'привет' }, { text: 'привет' }, 'c-1');
  assert.equal(store.timeline(store.get(CONV)).at(-1).state, 'sending');

  store.applyAck({ conversation_id: CONV, client_msg_id: 'c-1', seq: 2, created_at: '2026-10-29T12:01:00Z' });
  const timeline = store.timeline(store.get(CONV));
  assert.deepEqual(timeline.map((m) => [m.seq, m.state]), [[1, 'ok'], [2, 'ok']]);
  assert.equal(store.get(CONV).pending.length, 0);
});

test('подтверждение через пропуск: сообщение остаётся внизу, пока чужие не догружены, дубля нет', () => {
  const store = makeStore();
  store.applyHistory(CONV, [msg(1)], false);
  store.queueSend(CONV, 'text', { text: 'a' }, { text: 'a' }, 'c-1');
  const ack = store.applyAck({ conversation_id: CONV, client_msg_id: 'c-1', seq: 3, created_at: '2026-10-29T12:01:00Z' });
  assert.equal(ack.forwardSync, true);
  assert.deepEqual(store.timeline(store.get(CONV)).map((m) => [m.seq, m.state]), [[1, 'ok'], [3, 'sent']]);

  store.applyHistory(CONV, [msg(2), msg(3, ME, { client_msg_id: 'c-1' })], false);
  assert.deepEqual(store.timeline(store.get(CONV)).map((m) => [m.seq, m.state]), [[1, 'ok'], [2, 'ok'], [3, 'ok']]);
  assert.equal(store.get(CONV).pending.length, 0);
});

test('то же сообщение пришло и подтверждением, и доставкой в другую вкладку — дубля нет', () => {
  const store = makeStore();
  store.applyHistory(CONV, [msg(1)], false);
  store.queueSend(CONV, 'text', { text: 'a' }, { text: 'a' }, 'c-1');
  store.applyMessage(msg(2, ME, { client_msg_id: 'c-1' }), true);
  store.applyAck({ conversation_id: CONV, client_msg_id: 'c-1', seq: 2, created_at: '2026-10-29T12:01:00Z' });
  assert.deepEqual(seqs(store), [1, 2]);
  assert.equal(store.get(CONV).pending.length, 0);
});

test('после обрыва неподтверждённые уходят повторно с теми же client_msg_id', () => {
  const store = makeStore();
  store.applyHistory(CONV, [], false);
  store.queueSend(CONV, 'text', { text: 'a' }, { text: 'a' }, 'c-1');
  store.queueSend(CONV, 'text', { text: 'b' }, { text: 'b' }, 'c-2');
  store.applyAck({ conversation_id: CONV, client_msg_id: 'c-1', seq: 1, created_at: '2026-10-29T12:01:00Z' });
  assert.deepEqual(store.unconfirmed().map((p) => p.clientMsgId), ['c-2']);
});

test('отклонённое сервером сообщение помечается и не повторяется', () => {
  const store = makeStore();
  store.queueSend(CONV, 'text', { text: 'a' }, { text: 'a' }, 'c-1');
  store.markFailed('c-1');
  assert.deepEqual(store.unconfirmed(), []);
  assert.equal(store.timeline(store.get(CONV)).at(-1).state, 'failed');
});

test('порция истории, не стыкующаяся с окном, игнорируется', () => {
  const store = makeStore();
  store.applyHistory(CONV, [msg(10), msg(11)], true);
  store.applyHistory(CONV, [msg(2), msg(3)], true);
  assert.deepEqual(seqs(store), [10, 11]);
});

test('выборка вперёд с has_more просит следующую порцию', () => {
  const store = makeStore();
  store.applyHistory(CONV, [msg(1)], false);
  const result = store.applyHistory(CONV, [msg(2), msg(3)], true);
  assert.equal(result.forwardSync, true);
});
