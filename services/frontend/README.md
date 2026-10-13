# Фронтенд мессенджера (services/frontend)

Модуль веб-интерфейса мессенджера в стиле **Apple iOS Liquid Glass (Glassmorphism)**.

## Содержимое
- `static/css/glass.css` — дизайн-система жидкого стекла (эффекты размытия, границы, тени, блики, анимированный фон).
- `static/css/messenger.css` — верстка мессенджера (диалоги, лента сообщений, бабблы, карточки треков).
- `static/css/settings.css` — верстка вкладки «Настройки» в стиле iOS Settings.
- `static/js/messenger-ui.js` — интерактивность интерфейса (переключение табов, диалогов, отправка, воспроизведение трека).
- `templates/` — Jinja2-шаблоны мессенджера и настроек.
- `tests/` — тесты интерфейса и статических ассетов.

## Запуск в режиме разработки

1. Активируйте виртуальное окружение:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
2. Запустите dev-сервер:
   ```bash
   python -m uvicorn services.frontend.main:app --reload --port 8000
   ```
3. Откройте в браузере: [http://localhost:8000](http://localhost:8000)

## Запуск тестов

```bash
python -m pytest services/frontend/tests/
```
