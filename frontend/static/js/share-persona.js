(() => {
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
})();
