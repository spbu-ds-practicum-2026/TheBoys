import test from 'node:test';
import assert from 'node:assert/strict';
import { Session } from '../../static/js/session.js';

const CONV = 10;

// Сессия с подменённым соединением: все отправленные события попадают в sent.
function makeSession(lastSeq) {
  const session = new Session(1);
  const sent = [];
  session.connection = { state: 'open', send: (event) => { sent.push(event); return true; } };
  session.store.applyConversations([{ id: CONV, peer: { id: 2, login: 'bob' }, last_seq: lastSeq, unread_count: 0 }]);
  const syncs = () => sent.filter((event) => event.type === 'sync');
  return { session, syncs };
}

function msg(seq) {
  return {
    type: 'message', conversation_id: CONV, seq, sender_id: 2, client_msg_id: `id-${seq}`,
    kind: 'text', payload: { text: `m${seq}` }, created_at: '2026-10-29T12:00:00Z',
  };
}

function history(from, to, hasMore) {
  const messages = [];
  for (let seq = from; seq <= to; seq += 1) messages.push(msg(seq));
  return { type: 'history', conversation_id: CONV, messages, has_more: hasMore };
}

test('диалог открывается запросом последних сообщений: before_seq = known_seq + 1', () => {
  const { session, syncs } = makeSession(150);
  session.openConversation(CONV);
  assert.deepEqual(syncs().map((s) => [s.before_seq, s.since_seq]), [[151, undefined]]);
});

test('пока ответа нет, тот же запрос не дублируется', () => {
  const { session, syncs } = makeSession(150);
  session.openConversation(CONV);
  session.openConversation(CONV);
  assert.equal(syncs().length, 1);
});

test('подгрузка вверх страница за страницей: после каждого ответа следующий запрос уходит', () => {
  const { session, syncs } = makeSession(150);
  const conv = session.store.get(CONV);

  session.openConversation(CONV);
  session.handleEvent(history(101, 150, true));
  session.loadOlder(conv);
  session.handleEvent(history(51, 100, true));
  session.loadOlder(conv);
  session.handleEvent(history(1, 50, false));
  session.loadOlder(conv); // начало истории: запрашивать больше нечего

  assert.deepEqual(syncs().map((s) => s.before_seq), [151, 101, 51]);
  assert.equal(conv.hasOlder, false);
});

test('догрузка после пропуска не блокируется предыдущим ответом', () => {
  const { session, syncs } = makeSession(50);
  session.openConversation(CONV);
  session.handleEvent(history(1, 50, false));

  session.handleEvent(msg(53)); // пришло через пропуск: known_seq обогнал конец окна
  session.handleEvent(history(51, 53, false));
  session.handleEvent(msg(56));
  session.handleEvent(history(54, 56, false));

  assert.deepEqual(syncs().filter((s) => s.since_seq !== undefined).map((s) => s.since_seq), [50, 53]);
});

test('ошибка на sync освобождает запрос, и его можно повторить', () => {
  const { session, syncs } = makeSession(150);
  const warn = console.warn;
  console.warn = () => {};
  try {
    session.openConversation(CONV);
    session.handleEvent({ type: 'error', code: 'INTERNAL_ERROR', message: 'stub' });
    session.openConversation(CONV);
  } finally {
    console.warn = warn;
  }
  assert.equal(syncs().length, 2);
});
