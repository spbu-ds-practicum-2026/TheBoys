// Страница входа и регистрации: POST /api/login и POST /api/register.

import { api } from './api.js';

const form = document.getElementById('auth-form');
const errorBox = document.getElementById('auth-error');

const MESSAGES = {
  LOGIN_TAKEN: 'Логин уже занят. Выберите другой.',
  INVALID_CREDENTIALS: 'Неверный логин или пароль.',
};

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const mode = event.submitter?.dataset.mode ?? 'login';
  const login = form.elements.login.value.trim();
  const password = form.elements.password.value;

  if (!login || !password) {
    errorBox.textContent = 'Введите логин и пароль.';
    return;
  }

  errorBox.textContent = '';
  const buttons = form.querySelectorAll('button');
  buttons.forEach((button) => { button.disabled = true; });
  try {
    const response = mode === 'register' ? await api.register(login, password) : await api.login(login, password);
    if (response.ok) {
      location.href = '/music';
      return;
    }
    errorBox.textContent = MESSAGES[response.data?.code] ?? response.data?.message ?? 'Не удалось выполнить запрос.';
  } catch {
    errorBox.textContent = 'Нет связи с сервером.';
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
});
