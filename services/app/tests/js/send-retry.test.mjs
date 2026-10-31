// Повтор отправки после ошибки узла (ТР, пользовательский сценарий 7, п. 4; технический сценарий 6, п. 3).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Session } from '../../static/js/session.js';

const CONV = 10;

function makeSession() {
  const session = new Session(1);
  const sent = [];
  session.connection = { state: 'open', send: (event) => { sent.push(event); return true; } };
  session.store.applyConversations([{ conversation_id: CONV, peer: { id: 2, login: 'bob' }, last_seq: 0, unread_count: 0 }]);
  const sends = () => sent.filter((event) => event.type === 'send_message');
  const status = () => session.store.get(CONV).pending[0]?.status;
  return { session, sends, status };
}

const error = (code, clientMsgId) => ({ type: 'error', code, message: '…', client_msg_id: clientMsgId });

test('временная ошибка узла: сообщение остаётся «отправляется» и уходит снова с тем же client_msg_id', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const { session, sends, status } = makeSession();
  session.sendText(CONV, 'привет');
  const id = sends()[0].client_msg_id;

  session.handleEvent(error('INTERNAL_ERROR', id));
  assert.equal(status(), 'sending');
  t.mock.timers.tick(1000);
  assert.equal(sends().length, 2);
  assert.equal(sends()[1].client_msg_id, id);

  session.handleEvent(error('INTERNAL_ERROR', id));
  t.mock.timers.tick(1999);
  assert.equal(sends().length, 2); // пауза растёт
  t.mock.timers.tick(1);
  assert.equal(sends().length, 3);

  session.handleEvent(error('INTERNAL_ERROR', id));
  session.handleEvent({ type: 'ack', client_msg_id: id, conversation_id: CONV, seq: 1, created_at: '2026-10-30T12:00:00Z' });
  t.mock.timers.tick(60000);
  assert.equal(sends().length, 3); // после ack повторов нет
});

test('постоянная ошибка: «не отправлено» и без повторов, в том числе после переподключения', (t) => {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  for (const code of ['CONVERSATION_NOT_FOUND', 'NOT_A_MEMBER', 'TRACK_NOT_FOUND', 'INVALID_PAYLOAD']) {
    const { session, sends, status } = makeSession();
    session.sendText(CONV, 'привет');
    session.handleEvent(error(code, sends()[0].client_msg_id));
    assert.equal(status(), 'failed', code);
    t.mock.timers.tick(60000);
    session.handleOpen();
    assert.equal(sends().length, 1, code);
  }
});
