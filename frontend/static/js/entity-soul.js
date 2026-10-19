/* Owner-authored entity knowledge; safe Markdown is rendered by the server. */
(() => {
  const el = (tag, text = '') => { const n = document.createElement(tag); n.textContent = text; return n; };
  window.entitySoulEditor = (entity, api, reload) => {
    const panel = el('details'); panel.className = 'entity-soul entity-section'; panel.append(el('summary', 'Soul and identity'));
    let loaded = false;
    panel.addEventListener('toggle', async () => {
      if (!panel.open || loaded) return;
      loaded = true;
      panel.querySelector(':scope > div')?.remove();
      const content = el('div', 'Loading entity context…'); content.setAttribute('aria-live', 'polite'); panel.append(content);
      try {
        const context = await api('/context/' + encodeURIComponent(entity.id));
        content.replaceChildren();
        const soul = context.soul;
        const form = el('form'), fields = el('div'); fields.className = 'profile-fields';
        const field = (parent, title, value = '', multiline = false) => {
          const wrapper = el('div'), label = el('label', title), input = el(multiline ? 'textarea' : 'input');
          input.id = 'soul-field-' + crypto.randomUUID(); label.htmlFor = input.id;
          input.value = value; input.defaultValue = value;
          if (multiline) { input.rows = 4; wrapper.className = 'profile-wide'; }
          wrapper.append(label, input); parent.append(wrapper); return input;
        };
        const markdown = field(fields, 'Soul (Markdown)', soul.markdown, true); markdown.maxLength = 20000;
        const preview = el('details'); preview.append(el('summary', 'Saved Markdown preview'));
        const rendered = el('div'); rendered.className = 'prose'; rendered.innerHTML = context.soul_html; preview.append(rendered);
        form.append(fields, preview, el('p', 'Describe this entity in your own words. Descriptions provide context; only the confirmed rules below authorize matching.'));
        const rules = [], relationships = [], journal = [];
        const addSection = (title, hint, text, add) => {
          const section = el('section'); section.append(el('h2', title), el('p', hint));
          const list = el('div'), button = el('button', text); button.type = 'button'; button.onclick = () => add(list);
          section.append(list, button); form.append(section); return list;
        };
        const remove = (node, row) => {
          const button = el('button', 'Remove'); button.type = 'button'; button.onclick = () => { row.removed = true; node.remove(); }; node.append(button);
        };
        const provenance = (node, data) => {
          if (data.provenance) node.append(el('p', `Confirmed by ${data.provenance.actor} · ${data.provenance.at}`));
        };
        function rule(list, data = {}) {
          const node = el('fieldset'), grid = el('div'); grid.className = 'profile-fields'; node.append(el('legend', 'Confirmed identity rule'), grid);
          const row = {id: data.id || crypto.randomUUID()};
          row.name = field(grid, 'Observed name', data.observed_name || ''); row.name.required = true;
          row.sources = field(grid, 'Activity sources (one per line)', (data.sources || []).join('\n'), true); row.sources.required = true;
          row.required = field(grid, 'Required context phrases (one per line)', (data.required_context || []).join('\n'), true);
          row.excluded = field(grid, 'Exclude when these phrases occur (one per line)', (data.excluded_context || []).join('\n'), true);
          const label = el('label', 'Use this rule for future and existing mentions'); row.enabled = el('input'); row.enabled.type = 'checkbox'; row.enabled.checked = data.enabled ?? true; label.prepend(row.enabled); node.append(label);
          node.append(el('p', 'Applies only to this entity type and these exact sources. Conflicting full names, competing rules and previous separations prevent automatic assignment.'));
          provenance(node, data); remove(node, row); list.append(node); rules.push(row);
        }
        const ruleList = addSection('Identity rules', 'Saving a rule confirms that this observed name identifies this entity within the scope you specify.', 'Add identity rule', rule);
        soul.identity_rules.forEach(r => rule(ruleList, r));
        function note(list, data = {}) {
          const node = el('fieldset'), row = {id: data.id || crypto.randomUUID()}; node.append(el('legend', 'Journal note'));
          row.text = field(node, 'Note', data.text || '', true); row.text.required = true; row.text.maxLength = 4000;
          provenance(node, data); remove(node, row); list.append(node); journal.push(row);
        }
        const journalList = addSection('Journal', 'Dated notes and corrections complement the supporting activity below. Edit history is retained in the entity audit.', 'Add journal note', note);
        soul.journal.forEach(r => note(journalList, r));
        const actions = el('div'); actions.className = 'profile-actions';
        const save = el('button', 'Save soul'), cancel = el('button', 'Cancel'), feedback = el('span'); feedback.setAttribute('role', 'status'); cancel.type = 'button';
        cancel.onclick = () => { panel.open = false; loaded = false; content.remove(); };
        actions.append(save, cancel, feedback); form.append(actions); content.append(form);
        const lines = input => input.value.split('\n').map(v => v.trim()).filter(Boolean);
        form.onsubmit = async event => {
          event.preventDefault(); save.disabled = true; cancel.disabled = true; feedback.textContent = 'Saving…';
          try {

            const payload = {version: soul.version, markdown: markdown.value,
              identity_rules: rules.filter(r => !r.removed).map(r => ({id:r.id, observed_name:r.name.value, sources:lines(r.sources), required_context:lines(r.required), excluded_context:lines(r.excluded), enabled:r.enabled.checked})),
              relationships: soul.relationships.map(({id,target_id,relation,since,until,evidence}) => ({id,target_id,relation,since,until,evidence})),
              journal: journal.filter(r => !r.removed).map(r => ({id:r.id, text:r.text.value}))};
            await api('/soul/' + encodeURIComponent(entity.id), payload);
            feedback.textContent = 'Saved. Matching has been queued.';
            // Replace this editor after saving; a stale version must not be resubmitted.
            loaded = false; panel.open = false; content.remove();
            await reload();
          } catch (error) { feedback.textContent = error.message; } finally { save.disabled = false; cancel.disabled = false; }
        };
      } catch (error) { content.textContent = error.message; loaded = false; content.append(el('p', 'Close and reopen to retry.')); }
    });
    return panel;
  };
})();
