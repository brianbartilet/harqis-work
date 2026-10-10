/* Live inherited agent settings in both action editors. */
(() => {
  window.HflActionAgentSettings = (form, sourceId) => {
    const section = form.querySelector('[data-action-agent-settings]');
    if (!section) return;
    section.open = false;
    const summary = section.querySelector('[data-agent-settings-summary]');
    const status = section.querySelector('[data-agent-settings-status]');
    const identity = Symbol();
    section.settingsRequest = identity;
    summary.replaceChildren();
    async function refresh() {
      status.hidden = false;
      status.textContent = 'Loading agent settings…';
      try {
        const path = sourceId ? '/actions/' + encodeURIComponent(sourceId) + '/configuration' : '/configuration/defaults';
        const response = await fetch('/hfl-corpus/agent-bridge' + path);
        if (!response.ok) throw new Error('Could not load agent settings. Reopen this section to retry.');
        const config = await response.json();
        if (section.settingsRequest !== identity) return;
        const s = config.effective;
        const configuration = (config.card.preset || 'App Settings defaults') + (Object.keys(config.card.overrides).length ? ' · Action overrides' : '');
        summary.replaceChildren();
        for (const [label, value] of [['Agent','Hermes'],['Configuration',configuration],['Profile',s.hermes_profile || 'Worker profile'],['Permissions',s.agent_mode],['Repository',s.agent_repository || 'Isolated worktree'],['Idle expiry',s.agent_session_expiry_minutes + ' minutes']]) {
          const term = document.createElement('dt'), detail = document.createElement('dd');
          term.textContent = label; detail.textContent = value; summary.append(term, detail);
        }
        status.hidden = true;
      } catch (error) {
        if (section.settingsRequest !== identity) return;
        summary.replaceChildren(); status.textContent = error.message;
      }
    }
    section.ontoggle = () => { if (section.open) void refresh(); };
  };
})();
