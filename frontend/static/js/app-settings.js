(() => {
  const reveal = () => {
    const id = location.hash.slice(1);
    if (!['favorite_tags', 'activity-corpus', 'corpus-secrets-title'].includes(id)) return;
    const section = document.getElementById('activity-corpus');
    section.open = true;
    const target = document.getElementById(id);
    target.scrollIntoView({block: 'center'});
    if (id === 'favorite_tags') target.focus({preventScroll: true});
  };
  const form = document.querySelector('form');
  form.addEventListener('submit', () => {
    form.elements.open_sections.value = [...form.querySelectorAll('details.settings-section[open]')].map(section => section.id).join(',');
  });
  form.addEventListener('invalid', event => {
    const section = event.target.closest('details');
    if (section) section.open = true;
  }, true);
  window.addEventListener('hashchange', reveal);
  reveal();
  const notice = document.getElementById('settings-save-notice');
  if (notice) {
    setTimeout(() => notice.remove(), 4000);
    const url = new URL(location.href);
    url.searchParams.delete('saved');
    url.searchParams.delete('open');
    history.replaceState(history.state, '', url);
  }
})();
