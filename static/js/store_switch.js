(() => {
  const modal = document.querySelector('[data-store-switch-modal]');
  if (!modal) {
    return;
  }

  const openers = document.querySelectorAll('[data-store-switch-open]');
  const closers = modal.querySelectorAll('[data-store-switch-close]');

  const openModal = () => {
    modal.classList.add('is-active');
    modal.setAttribute('aria-hidden', 'false');
  };

  const closeModal = () => {
    modal.classList.remove('is-active');
    modal.setAttribute('aria-hidden', 'true');
  };

  openers.forEach((button) => button.addEventListener('click', openModal));
  closers.forEach((button) => button.addEventListener('click', closeModal));

  modal.addEventListener('click', (event) => {
    if (event.target === modal) {
      closeModal();
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      closeModal();
    }
  });
})();
