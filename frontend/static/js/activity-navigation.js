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
    const tab = menu.closest('.activity-navigation');
    const toggle = tab.querySelector(':scope > a');
    toggle.setAttribute('aria-haspopup', 'true');
    const hover = matchMedia('(hover: hover) and (pointer: fine)');
    let closeTimer;
    tab.addEventListener('pointerenter', event => {
      if (!hover.matches || event.pointerType !== 'mouse') return;
      clearTimeout(closeTimer);
      menu.open = true;
      position(menu);
    });
    tab.addEventListener('pointerleave', event => {
      if (!hover.matches || event.pointerType !== 'mouse') return;
      closeTimer = setTimeout(() => { menu.open = false; }, 250);
    });
    // Keep the menu open when crossing the gap below the tab.
    menu.querySelector('.activity-navigation-options').addEventListener('pointerenter', () => clearTimeout(closeTimer));
    toggle.addEventListener('click', event => {
      if (!hover.matches && !menu.open && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
        event.preventDefault();
        menu.open = true;
        position(menu);
      }
    });
    toggle.setAttribute('aria-expanded', 'false');
    menu.addEventListener('toggle', () => {
      toggle.setAttribute('aria-expanded', String(menu.open));
      if (!menu.open) return;
      menus.forEach(other => { if (other !== menu) other.open = false; });
      position(menu);
    });
    tab.addEventListener('keydown', event => {
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
    menus.forEach(menu => { if (!menu.closest('.activity-navigation').contains(event.target)) menu.open = false; });
  });
  window.addEventListener('resize', () => menus.forEach(menu => { menu.open = false; }));
  document.querySelectorAll('nav[aria-label="Primary navigation"]').forEach(nav => {
    nav.addEventListener('scroll', () => menus.forEach(menu => { menu.open = false; }));
  });
})();
