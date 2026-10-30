import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { Connection } from '../../static/js/ws.js';
import { newClientMsgId } from '../../static/js/session.js';

class FakeSocket {
  static OPEN = 1;
  static all = [];
  constructor() { this.readyState = 0; FakeSocket.all.push(this); }
  send() {}
  close() {}
  open() { this.readyState = 1; this.onopen?.(); }
  receive(event) { this.onmessage?.({ data: JSON.stringify(event) }); }
  drop(code = 1011) { this.readyState = 3; this.onclose?.({ code }); }
}

test('узел принимает подключение и сразу закрывает — пауза между попытками растёт', () => {
  mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
  globalThis.WebSocket = FakeSocket;
  globalThis.location = { protocol: 'http:', host: 'localhost:8000' };
  const connection = new Connection({ onEvent() {}, onOpen() {}, onState() {} });
  connection.start();
  for (let i = 0; i < 3; i += 1) {
    FakeSocket.all.at(-1).open();
    FakeSocket.all.at(-1).drop();
    mock.timers.tick(9000);
  }
  assert.equal(connection.attempts, 3);

  FakeSocket.all.at(-1).open();
  FakeSocket.all.at(-1).receive({ type: 'dialog_sync', dialogs: [] });
  assert.equal(connection.attempts, 0);
  mock.timers.reset();
});

test('client_msg_id создаётся и без crypto.randomUUID (сайт открыт по http://IP)', () => {
  const insecure = { getRandomValues: (array) => crypto.getRandomValues(array) };
  const id = newClientMsgId(insecure);
  assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.notEqual(newClientMsgId(insecure), id);
});
