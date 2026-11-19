/* Shared, non-blocking feedback. Validation and progress stay with their forms. */
(() => {
  if (window.HarqisToast) return;
  const selector = '[data-entry-success],[data-entry-saved],#settings-save-notice,.profile-success,[data-success-toast],.editor-save-confirmation,.corpus-action-toast,#role-status.role-save-notice,#space-status.role-save-notice';
  const seen = new WeakMap();
  function show(message, {persistent = false, parent = document.body} = {}) {
    if (!message.trim()) return;
    const owner = parent.closest?.('dialog[open]') || document.body;
    let stack = owner.querySelector(':scope > .notification-stack');
    if (!stack) {
      stack = document.createElement('div'); stack.className = 'notification-stack';
      stack.setAttribute('aria-label', 'Notifications'); owner.append(stack);
    }
    const toast = document.createElement('div'); toast.className = 'notification-toast';
    const text = document.createElement('span'); text.setAttribute('role', 'status');
    text.setAttribute('aria-live', 'polite'); text.textContent = message;
    const close = document.createElement('button'); close.type = 'button';
    close.className = 'notification-close'; close.textContent = '×';
    close.setAttribute('aria-label', 'Dismiss notification');
    let timer;
    const pause = () => clearTimeout(timer);
    const dismiss = () => { pause(); toast.remove(); if (!stack.children.length) stack.remove(); };
    const resume = () => { pause(); if (!persistent && !toast.matches(':hover,:focus-within')) timer = setTimeout(dismiss, 6000); };
    close.addEventListener('click', dismiss);
    toast.addEventListener('mouseenter', pause); toast.addEventListener('mouseleave', resume);
    toast.addEventListener('focusin', pause); toast.addEventListener('focusout', () => setTimeout(resume, 0));
    toast.append(text, close); stack.append(toast); resume();
    return dismiss;
  }
  function collect() {
    document.querySelectorAll(selector).forEach(source => {
      const copy = source.cloneNode(true); copy.querySelectorAll('button').forEach(button => button.remove());
      const message = copy.textContent.trim();
      if (!message || seen.get(source) === message) return;
      seen.set(source, message);
      show(message, {parent: source, persistent: source.hasAttribute('data-notification-persistent')});
      if (source.matches('#role-status,#space-status,[data-entry-saved]')) {
        source.textContent = ''; source.classList.remove('role-save-notice'); seen.delete(source);
      } else {
        source.setAttribute('data-notification-source', ''); source.hidden = true;
      }
    });
  }
  window.HarqisToast = {show};
  const start = () => {
    collect();
    new MutationObserver(collect).observe(document.body, {childList:true, subtree:true, characterData:true, attributes:true, attributeFilter:['class']});
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once:true});
  else start();
})();
