# Сервис узла приложения (`services/app`)

Узел веб-приложения на базе **FastAPI**. Отвечает за:
- HTTP API и WebSocket-соединения клиентов (`/ws`);
- Регистрацию сессий в таблице `sessions`;
- Гарантированную упорядоченную доставку сообщений с монотонным `seq`;
- Межузловую доставку сообщений через `POST /internal/deliver`.

---

## Запуск сервиса

### Переменные окружения
- `NODE_ID` — уникальный идентификатор узла (например, `app-1`, `app-2`).
- `INTERNAL_SECRET` — общий секрет для авторизации межсерверных вызовов (`X-Internal-Secret`).
- `DATABASE_URL` — строка подключения к PostgreSQL (`postgresql+asyncpg://user:pass@db:5432/theboys`).
- `JWT_SECRET` — ключ подписи cookie/токенов сессий пользователей.

### Локальный запуск (разработка)
```bash
# Из корня репозитория:
uvicorn services.app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Запуск тестов
```bash
pytest services/app/tests/
```

---

## 1. Спецификация WebSocket-событий (`/ws`)

### 1.1. Подключение и авторизация
- **URL:** `ws://<host>:<port>/ws`
- Клиент авторизуется через HTTP-only cookie входа (подписанную `JWT_SECRET`).
- При подключении узел:
  1. Генерирует `connection_id` (UUID).
  2. Записывает запись в таблицу `sessions`:
     ```sql
     INSERT INTO sessions (connection_id, user_id, node_id, last_seen)
     VALUES (:connection_id, :user_id, :node_id, now());
     ```
  3. При разрыве соединения удаляет сессию:
     ```sql
     DELETE FROM sessions WHERE connection_id = :connection_id;
     ```

---

### 1.2. События от клиента к серверу (Client -> Server)

Все события передаются в формате JSON. Обязательное поле: `"type"`.

#### 1.2.1. Отправка сообщения (`type: "send_message"`)
Клиент присваивает каждому сообщению уникальный `client_msg_id` (UUIDv4). По нему сервер распознаёт повторные отправки при сетевых сбоях.

- **Текстовое сообщение:**
```json
{
  "type": "send_message",
  "client_msg_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "conversation_id": 12,
  "kind": "text",
  "payload": {
    "text": "Привет! Зацени трек."
  }
}
```

- **Карточка трека:**
```json
{
  "type": "send_message",
  "client_msg_id": "a50c8413-2d18-4e89-a2e6-9922c2a0129f",
  "conversation_id": 12,
  "kind": "track",
  "payload": {
    "track_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "title": "Starboy",
    "artist": "The Weeknd",
    "duration_s": 230
  }
}
```

#### 1.2.2. Отметка о прочтении (`type: "read"`)
Клиент сообщает максимальный номер `seq`, который он отрисовал в окне.
```json
{
  "type": "read",
  "conversation_id": 12,
  "up_to_seq": 45
}
```
*Правило:* Сервер принимает позицию только если `up_to_seq > current_last_read_seq` и `up_to_seq <= conversation.last_seq`.

#### 1.2.3. Синхронизация пропущенных сообщений (`type: "sync"`)
Отправляется после переподключения или при обнаружении пропуска в номерах `seq` (`known_seq < incoming_seq - 1`).
```json
{
  "type": "sync",
  "conversation_id": 12,
  "since_seq": 40
}
```

#### 1.2.4. Пинг / Heartbeat клиента (`type: "ping"`)
Отправляется клиентом каждые 5–10 секунд для поддержания соединения и сверки актуального состояния диалогов.
```json
{
  "type": "ping"
}
```
При получении сервер выполняет `UPDATE sessions SET last_seen = now() WHERE connection_id = :conn_id`.

#### 1.2.5. Индикатор «Печатает…» (`type: "typing"`)
```json
{
  "type": "typing",
  "conversation_id": 12
}
```

---

### 1.3. События от сервера к клиенту (Server -> Client)

#### 1.3.1. Подтверждение отправки (`type: "ack"`)
Отправляется автору сообщения сразу после фиксации в транзакции PostgreSQL.
```json
{
  "type": "ack",
  "client_msg_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "conversation_id": 12,
  "seq": 46,
  "created_at": "2026-10-26T21:15:30.123456Z"
}
```

#### 1.3.2. Входящее сообщение (`type: "message"`)
Рассылается во все открытые вкладки (сессии) обоих участников диалога.
```json
{
  "type": "message",
  "conversation_id": 12,
  "seq": 46,
  "sender_id": 5,
  "client_msg_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "kind": "text",
  "payload": {
    "text": "Привет! Зацени трек."
  },
  "created_at": "2026-10-26T21:15:30.123456Z"
}
```

#### 1.3.3. Подтверждение прочтения (`type: "read_ack"`)
```json
{
  "type": "read_ack",
  "conversation_id": 12,
  "last_read_seq": 45,
  "unread_count": 0
}
```

#### 1.3.4. Ответ на пинг / Сверка состояния (`type: "dialog_sync"`)
Возвращает список всех диалогов пользователя с актуальными `last_seq` и счётчиками непрочитанных сообщений.
```json
{
  "type": "dialog_sync",
  "dialogs": [
    {
      "conversation_id": 12,
      "last_seq": 46,
      "unread_count": 1
    },
    {
      "conversation_id": 14,
      "last_seq": 102,
      "unread_count": 0
    }
  ]
}
```

#### 1.3.5. Догрузка истории диалога (`type: "history"`)
Ответ на запрос `"type": "sync"`. Содержит непрерывный массив сообщений.
```json
{
  "type": "history",
  "conversation_id": 12,
  "messages": [
    {
      "conversation_id": 12,
      "seq": 41,
      "sender_id": 8,
      "client_msg_id": "c1f7a0b3-982e-4b2a-8d19-482a558509cd",
      "kind": "text",
      "payload": { "text": "Тут кто-нибудь есть?" },
      "created_at": "2026-10-26T21:14:00Z"
    }
  ]
}
```

#### 1.3.6. Уведомление «Собеседник печатает…» (`type: "peer_typing"`)
```json
{
  "type": "peer_typing",
  "conversation_id": 12,
  "user_id": 8
}
```

#### 1.3.7. Ошибка (`type: "error"`)
```json
{
  "type": "error",
  "code": "CONVERSATION_NOT_FOUND",
  "message": "Диалог с ID 999 не существует",
  "client_msg_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
}
```

---

## 2. Межузловая доставка (`POST /internal/deliver`)

Когда узел приложения сохраняет сообщение в БД, он находит по таблице `sessions` все активные сессии участников:
1. Если сессия на текущем узле (`node_id == NODE_ID`) — отправляет в локальный WebSocket.
2. Если сессия на другом узле — отправляет HTTP-запрос `POST http://<node_address>/internal/deliver`.

### 2.1. Формат запроса
- **URL:** `http://<target_app_node>/internal/deliver`
- **Метод:** `POST`
- **Заголовок:** `X-Internal-Secret: <INTERNAL_SECRET>`
- **Content-Type:** `application/json`

**Тело запроса:**
```json
{
  "connection_ids": [
    "550e8400-e29b-41d4-a716-446655440000",
    "e4d92461-1250-424a-9ef8-e04e8a4d46b2"
  ],
  "user_id": 8,
  "event": {
    "type": "message",
    "conversation_id": 12,
    "seq": 46,
    "sender_id": 5,
    "client_msg_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
    "kind": "text",
    "payload": {
      "text": "Привет! Зацени трек."
    },
    "created_at": "2026-10-26T21:15:30.123456Z"
  }
}
```

### 2.2. Ответ целевого узла
- `200 OK`:
```json
{
  "delivered": ["550e8400-e29b-41d4-a716-446655440000"],
  "missed": ["e4d92461-1250-424a-9ef8-e04e8a4d46b2"]
}
```
- `403 Forbidden` — если `X-Internal-Secret` не совпадает с `INTERNAL_SECRET`.
- `422 Unprocessable Entity` — если тело запроса не соответствует схеме.

---

## 3. Решение проблем распределённых систем в архитектуре

1. **Ненадёжная доставка и идемпотентность:**
   - Клиент генерирует `client_msg_id` (UUID). При потере связи или таймауте клиент повторяет отправку с тем же `client_msg_id`.
   - Сервер выполняет вставку с уникальным индексом `UNIQUE (sender_id, client_msg_id)`. При повторе возвращается уже сохранённая запись без генерации дублей и без расхода `seq`.

2. **Строгий порядок событий (Strict Total Order):**
   - У каждого диалога есть счётчик `last_seq`. При отправке транзакция блокирует строку `conversations` (`SELECT FOR UPDATE`), увеличивает `last_seq + 1` и фиксирует сообщение с этим номером.
   - Номера `seq` строго монотонны, непрерывны и не содержат пропусков.

3. **Согласованность данных при сбоях узлов (Fault Tolerance):**
   - Если отправка через `/internal/deliver` не удалась (целевой узел упал), сообщение всё равно надёжно сохранено в PostgreSQL.
   - При переподключении к любому другому живому узлу клиент вызывает `sync` с параметром `since_seq` и гарантированно получает всю упущенную историю.
