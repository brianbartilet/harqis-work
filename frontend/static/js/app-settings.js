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
  document.querySelector('form').addEventListener('invalid', event => {
    const section = event.target.closest('details');
    if (section) section.open = true;
  }, true);
  window.addEventListener('hashchange', reveal);
  reveal();
})();
