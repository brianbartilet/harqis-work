/* Member-level corrections, with the existing entity dialog and picker patterns. */
window.EntityDetach = {
  async open(entity, api, refresh) {
    const el = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
    const button = (text, action) => { const n = el('button', text); n.type = 'button'; n.onclick = action; return n; };
    const opener = document.activeElement;
    const dialog = el('dialog', undefined, 'entity-connections-dialog entity-detach-dialog');
    const title = el('h2', 'Detach members · ' + entity.label); title.id = 'detach-title';
    dialog.setAttribute('aria-labelledby', title.id);
    const header = el('header'), close = button('×', () => dialog.close()); close.setAttribute('aria-label', 'Close detach dialog');
    header.append(title, close);
    const label = el('label', 'Search members and supporting activity'), search = el('input'); search.type = 'search'; label.append(search);
    const status = el('p', 'Loading members…'); status.setAttribute('role', 'status');
    const error = el('p', '', 'detach-error'); error.setAttribute('role', 'alert');
    const list = el('div', undefined, 'detach-members'), pages = el('div', undefined, 'detach-pages');
    const preview = el('section', undefined, 'detach-preview'); preview.hidden = true;
    const footer = el('footer'); footer.append(button('Close', () => dialog.close()));
    dialog.append(header, label, status, error, list, pages, preview, footer);
    document.body.append(dialog); dialog.showModal();
    let members = [], page = 0, busy = false, generation = 0;
    const setBusy = value => {
      busy = value; dialog.setAttribute('aria-busy', String(value));
      dialog.querySelectorAll('button,input').forEach(n => n.disabled = value);
    };
    dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
    dialog.addEventListener('close', () => { generation++; dialog.remove(); if (opener?.isConnected) opener.focus(); }, {once:true});
    function activities(member, expanded = false) {
      const details = el('details'); details.open = expanded;
      details.append(el('summary', `Supporting activity · ${member.entries.length}`));
      let populated = false;
      const populate = () => {
        if (!details.open || populated) return; populated = true;
        if (!member.entries.length) details.append(el('p', 'No current supporting activities.'));
        for (const entry of member.entries) {
          const row = el('article'), link = el('a', entry.date.slice(0,10) + ' · ' + entry.title);
          link.href = entry.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
          row.append(link, el('small', entry.source), el('p', entry.text)); details.append(row);
        }
      };
      details.addEventListener('toggle', populate); populate(); return details;
    }
    function render() {
      const q = search.value.trim().toLocaleLowerCase();
      const filtered = members.filter(m => [m.label, ...m.aliases, ...m.entries.flatMap(e => [e.title,e.text,e.source])].join('\n').toLocaleLowerCase().includes(q));
      page = Math.max(0, Math.min(page, Math.ceil(filtered.length / 30) - 1));
      list.replaceChildren(); pages.replaceChildren();
      status.textContent = `${filtered.length} matching members · ${members.length} total`;
      for (const member of filtered.slice(page*30, (page+1)*30)) {
        const row = el('section', undefined, 'detach-member');
        const heading = el('div', undefined, 'detach-member-heading');
        heading.append(el('strong', member.label), button('Detach', () => review(member)));
        row.append(heading, el('small', member.path.join(' › ') + (member.group ? ' · Merged subgroup' : '')));
        if (member.aliases.length) row.append(el('p', member.aliases.join(' · '), 'detach-aliases'));
        row.append(activities(member)); list.append(row);
      }
      if (!filtered.length) list.append(el('p', 'No members match your search.'));
      if (page) pages.append(button('Previous', () => { page--; render(); }));
      if ((page+1)*30 < filtered.length) pages.append(button('Next', () => { page++; render(); }));
    }
    async function load() {
      const current = ++generation; setBusy(true); error.textContent = '';
      try {
        const data = await api('/merges/' + encodeURIComponent(entity.id) + '/members');
        if (!dialog.open || current !== generation) return;
        members = data.members; render();
      } catch (err) {
        if (!dialog.open) return;
        error.textContent = err.message; status.textContent = 'Members could not load.';
        pages.replaceChildren(button('Retry', load));
      } finally { setBusy(false); }
    }
    async function review(member) {
      setBusy(true); error.textContent = '';
      try {
        const data = await api('/merges/' + encodeURIComponent(entity.id) + '/detach-preview', {member_id:member.id});
        list.hidden = pages.hidden = label.hidden = true; preview.hidden = false; preview.replaceChildren();
        preview.append(el('h3', 'Detach “' + member.label + '”?'),
          el('p', 'This member becomes a separate identity. The remaining group keeps its identity. Automatic matching will keep the two sides separate.'),
          activities(data.member));
        for (const change of data.changes) {
          const details = el('details'); details.append(el('summary', 'Remaining group: ' + change.after.name));
          details.append(el('p', `${change.members.length} immediate members remain: ${change.members.map(m => m.label).join(' · ')}`));
          for (const key of ['aliases','partial_aliases','categories','emails','phones','references']) {
            const removed = (change.before[key] || []).filter(v => !(change.after[key] || []).includes(v));
            if (removed.length) details.append(el('p', `Remove inherited ${key.replaceAll('_',' ')}: ${removed.join(' · ')}`));
          }
          if (change.before.notes !== change.after.notes) details.append(el('p', 'Unchanged inherited notes from this member will be removed.'));
          preview.append(details);
        }
        preview.append(el('p', 'Later curated details and existing identity-review flags are retained. Review any shared or ambiguous profile details after detaching.'));
        const payload = {member_id:member.id, preview_token:data.preview_token, request_id:crypto.randomUUID()};
        const back = button('Back to members', () => { preview.hidden = true; list.hidden = pages.hidden = label.hidden = false; error.textContent = ''; search.focus(); });
        const confirm = button('Confirm detach', async () => {
          setBusy(true); error.textContent = '';
          try {
            await api('/merges/' + encodeURIComponent(entity.id) + '/detach', payload);
          } catch (err) { error.textContent = err.message; setBusy(false); return; }
          // Do not repeat a successful mutation if refreshing the directory fails.
          preview.hidden = true; list.hidden = pages.hidden = label.hidden = false;
          try { await refresh(); } catch (err) { error.textContent = 'Detached successfully. Directory refresh failed: ' + err.message; }
          await load(); status.textContent = 'Detached “' + member.label + '”. Audit saved. ' + status.textContent;
        });
        preview.append(back, confirm); setBusy(false); confirm.focus();
      } catch (err) { error.textContent = err.message; }
      finally { setBusy(false); }
    }
    search.oninput = () => { page = 0; render(); };
    await load(); search.focus();
  }
};
