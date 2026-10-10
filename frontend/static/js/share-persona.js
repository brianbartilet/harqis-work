(() => {
  const mode = document.getElementById('suggestion-mode');
  const custom = document.getElementById('suggestion-custom-field');
  const toggleQuestions = () => { if (mode && custom) custom.hidden = mode.value !== 'custom'; };
  mode?.addEventListener('change', toggleQuestions);
  toggleQuestions();
  const update = () => {
    const selected = (document.querySelector('[name=workspace_ids]')?.value || '').split(',');
    document.querySelectorAll('[data-persona-spaces]').forEach(node => {
      const linked = JSON.parse(node.dataset.personaSpaces).some(id => selected.includes(id));
      node.querySelector('[data-persona-suggestion]').hidden = !linked;
    });
  };
  document.addEventListener('change', update);
  document.addEventListener('activitychange', update);
  update();
  const dialog = document.getElementById('persona-examples');
  const trigger = document.getElementById('persona-examples-open');
  if (dialog && trigger) {
    trigger.onclick = () => { dialog.showModal(); document.getElementById('persona-examples-title').focus(); };
    dialog.querySelectorAll('[data-persona-examples-close]').forEach(button => button.onclick = () => dialog.close());
    dialog.addEventListener('close', () => trigger.focus());
    dialog.addEventListener('click', event => {
      const box = dialog.getBoundingClientRect();
      if (event.target === dialog && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) dialog.close();
    });
  }
})();
