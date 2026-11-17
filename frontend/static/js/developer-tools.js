(() => {
  const data = JSON.parse(document.getElementById('mcp-hub-data').textContent);
  const search = document.getElementById('mcp-search');
  const list = document.getElementById('mcp-app-list');
  const status = document.getElementById('mcp-catalogue-status');
  const more = document.getElementById('mcp-more-apps');
  let limit = 12, platform = 'mac';
  const opened = new Set();
  const tabs = [...document.querySelectorAll('.developer-tabs [role="tab"]')];
  function selectTab(tab, updateUrl = false) {
    for (const candidate of tabs) {
      const selected = candidate === tab;
      candidate.setAttribute('aria-selected', String(selected));
      candidate.tabIndex = selected ? 0 : -1;
      document.getElementById(candidate.getAttribute('aria-controls')).hidden = !selected;
    }
    if (updateUrl) history.replaceState(history.state, '', '#' + tab.getAttribute('aria-controls'));
  }
  function selectFromHash() { selectTab(tabs.find(tab => '#' + tab.getAttribute('aria-controls') === location.hash) || tabs[0]); }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectTab(tab, true));
    tab.addEventListener('keydown', event => {
      const next = {ArrowRight: (index + 1) % tabs.length, ArrowLeft: (index + tabs.length - 1) % tabs.length, Home: 0, End: tabs.length - 1}[event.key];
      if (next === undefined) return;
      event.preventDefault(); selectTab(tabs[next], true); tabs[next].focus();
    });
  });
  window.addEventListener('hashchange', selectFromHash);
  selectFromHash();
  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function render() {
    const query = search.value.trim().toLowerCase();
    const matches = data.apps.map(app => {
      const appMatch = `${app.label} ${app.key} ${app.description}`.toLowerCase().includes(query);
      const tools = appMatch ? app.tools : app.tools.filter(tool => `${tool.name} ${tool.description}`.toLowerCase().includes(query));
      return {...app, tools, matches: appMatch || tools.length > 0};
    }).filter(app => app.matches);
    list.replaceChildren();
    status.textContent = matches.length ? `Showing ${Math.min(limit, matches.length)} of ${matches.length} matching apps · ${matches.reduce((sum, app) => sum + app.tools.length, 0)} documented tools` : 'No apps or tools match. Try a different name or clear the search.';
    more.hidden = matches.length <= limit;
    for (const app of matches.slice(0, limit)) {
      const details = element('details', undefined, 'developer-app');
      const summary = element('summary');
      const heading = element('span', undefined, 'developer-app-heading');
      heading.append(element('strong', app.label), element('span', `${app.tools.length} tools`, 'developer-app-count'));
      summary.append(heading, element('span', app.description, 'developer-app-description'));
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', '0 0 20 20'); svg.setAttribute('aria-hidden', 'true');
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', 'm6 8 4 4 4-4'); svg.append(path);
      const action = element('span', undefined, 'developer-app-action');
      action.append(element('span', 'Explore tools'), svg); summary.append(action);
      const body = element('div', undefined, 'developer-app-body');
      details.append(summary, body);
      let toolLimit = 20, populated = false;
      function populate() {
        populated = true; body.replaceChildren();
        body.append(element('p', `Source: ${app.source}`, 'developer-note'));
        if (app.note) body.append(element('p', app.note));
        for (const tool of app.tools.slice(0, toolLimit)) {
          const item = element('details', undefined, 'developer-tool');
          item.append(element('summary', tool.name));
          const signature = element('pre', tool.signature); signature.tabIndex = 0;
          item.append(signature, element('p', tool.description, 'developer-tool-description'));
          body.append(item);
        }
        if (app.tools.length > toolLimit) {
          const button = element('button', 'Show more tools'); button.type = 'button';
          button.addEventListener('click', () => { toolLimit += 20; populate(); }); body.append(button);
        }
      }
      details.addEventListener('toggle', () => {
        if (details.open) { opened.add(app.key); if (!populated) populate(); }
        else opened.delete(app.key);
      });
      if (opened.has(app.key) || query) { populate(); details.open = true; }
      list.append(details);
    }
  }
  search.addEventListener('input', () => { limit = 12; render(); });
  more.addEventListener('click', () => { limit += 12; render(); });
  for (const button of document.querySelectorAll('[data-platform]')) button.addEventListener('click', () => {
    platform = button.dataset.platform;
    document.getElementById('mcp-client-config').textContent = data.examples[platform];
    document.getElementById('config-copy-status').textContent = '';
    for (const item of document.querySelectorAll('[data-platform]')) item.setAttribute('aria-pressed', String(item === button));
  });
  document.getElementById('copy-mcp-config').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(data.examples[platform]); document.getElementById('config-copy-status').textContent = 'Configuration copied. Replace the example paths before using it.'; }
    catch (_) { document.getElementById('config-copy-status').textContent = 'Copy is unavailable. Select and copy the configuration above.'; }
  });
  render();
})();
