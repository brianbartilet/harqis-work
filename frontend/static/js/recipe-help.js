(() => {
  const dialog = document.getElementById('recipe-help');
  const trigger = document.getElementById('recipe-help-open');
  if (!dialog || !trigger) return;
  trigger.onclick = () => { dialog.showModal(); document.getElementById('recipe-help-title').focus(); };
  dialog.querySelectorAll('[data-recipe-help-close]').forEach(button => button.onclick = () => dialog.close());
  dialog.addEventListener('close', () => trigger.focus());
  dialog.addEventListener('click', event => {
    const box = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) dialog.close();
  });
})();
