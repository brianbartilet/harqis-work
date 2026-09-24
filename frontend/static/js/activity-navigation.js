(() => {
  const menus = [...document.querySelectorAll('.activity-navigation-menu')];
  function position(menu) {
    const panel = menu.querySelector('.activity-navigation-options');
    const bounds = menu.closest('.activity-navigation').getBoundingClientRect();
    // The sticky header establishes the fixed-position containing block.
    const header = menu.closest('header').getBoundingClientRect();
    panel.style.left = `${Math.max(8, Math.min(bounds.left, innerWidth - panel.offsetWidth - 8)) - header.left}px`;
    panel.style.top = `${bounds.bottom + 8 - header.top}px`;
  }
  for (const menu of menus) {
    const toggle = menu.querySelector('summary');
    toggle.setAttribute('aria-expanded', 'false');
    menu.addEventListener('toggle', () => {
      toggle.setAttribute('aria-expanded', String(menu.open));
      if (!menu.open) return;
      menus.forEach(other => { if (other !== menu) other.open = false; });
      position(menu);
    });
    menu.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        menu.open = false;
        toggle.focus();
      } else if (event.key === 'ArrowDown' && event.target === toggle) {
        event.preventDefault();
        menu.open = true;
        position(menu);
        menu.querySelector('a').focus();
      }
    });
    menu.addEventListener('click', event => {
      if (event.target.closest('a')) menu.open = false;
    });
  }
  document.addEventListener('click', event => {
    menus.forEach(menu => { if (!menu.contains(event.target)) menu.open = false; });
  });
  window.addEventListener('resize', () => menus.forEach(menu => { menu.open = false; }));
  document.querySelectorAll('nav[aria-label="Primary navigation"]').forEach(nav => {
    nav.addEventListener('scroll', () => menus.forEach(menu => { menu.open = false; }));
  });
})();
