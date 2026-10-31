// Общее модальное окно на <dialog>: Esc и клик по фону закрывают его.

const dialog = () => document.getElementById('modal');

export function openModal(title, ...nodes) {
  const el = dialog();
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').replaceChildren(...nodes);
  if (!el.open) el.showModal();
}

export function closeModal() {
  const el = dialog();
  if (el.open) el.close();
}

export function initModal() {
  dialog().addEventListener('click', (event) => {
    if (event.target === dialog()) closeModal();
  });
}
