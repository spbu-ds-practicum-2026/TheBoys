// Поиск собеседника по логину: GET /api/users?login=… возвращает собеседника и диалог (ТР, технический сценарий 4, п. 1).
import test from 'node:test';
import assert from 'node:assert/strict';
import { api } from '../../static/js/api.js';
import { Session } from '../../static/js/session.js';
import { Store } from '../../static/js/store.js';

const BOB = { id: 2, login: 'bob' };
const CONVERSATION = { conversation_id: 7, peer: BOB, last_seq: 3, unread_count: 1 };

test('список диалогов читается по полю conversation_id', () => {
  const store = new Store(1);
  store.applyConversations([CONVERSATION]);
  const conv = store.get(7);
  assert.ok(conv);
  assert.equal(conv.knownSeq, 3);
  assert.equal(conv.unread, 1);
  assert.equal(conv.peer.login, 'bob');
});

test('openByLogin: логин найден — диалог добавлен в хранилище и возвращён его номер', async () => {
  const calls = [];
  api.findUser = async (login) => {
    calls.push(login);
    return { status: 200, ok: true, data: { user: BOB, conversation: CONVERSATION } };
  };
  const session = new Session(1);
  assert.deepEqual(await session.openByLogin('bob'), { ok: true, id: 7 });
  assert.deepEqual(calls, ['bob']);
  assert.equal(session.store.get(7).knownSeq, 3);
});

test('openByLogin: ошибка сервера возвращает её код, диалог не появляется', async () => {
  for (const [status, code] of [[404, 'USER_NOT_FOUND'], [422, 'INVALID_INPUT']]) {
    api.findUser = async () => ({ status, ok: false, data: { code, message: '…' } });
    const session = new Session(1);
    assert.deepEqual(await session.openByLogin('x'), { ok: false, code });
    assert.equal(session.store.list().length, 0);
  }
});

test('в списке нет пустых диалогов, кроме открытого и диалога с неотправленным сообщением', () => {
  const store = new Store(1);
  store.applyConversations([
    CONVERSATION,
    { conversation_id: 8, peer: { id: 3, login: 'carol' }, last_seq: 0, unread_count: 0 },
    { conversation_id: 9, peer: { id: 4, login: 'dave' }, last_seq: 0, unread_count: 0 },
  ]);
  assert.deepEqual(store.visibleList(null).map((c) => c.id), [7]);
  assert.deepEqual(store.visibleList(8).map((c) => c.id).sort(), [7, 8]);
  store.queueSend(9, 'text', { text: 'привет' }, { text: 'привет' }, 'c-1');
  assert.ok(store.visibleList(null).some((c) => c.id === 9));
  assert.equal(store.list().length, 3); // скрытые диалоги остаются в хранилище
});
