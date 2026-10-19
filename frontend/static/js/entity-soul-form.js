/* Shared fields for the unified Soul dialog. No independent writes. */
(() => {
  const el = (tag, text = '') => { const n = document.createElement(tag); n.textContent = text; return n; };
  const section = title => { const n = el('details'); n.className='entity-section'; n.append(el('summary',title)); return n; };
  const lines = input => input.value.split('\n').map(v=>v.trim()).filter(Boolean);
  window.createSoulDetails = (context, dirty) => {
    const soul = context.soul;
        const form = el('div'), fields = el('div'); fields.className = 'profile-fields';
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
        const rules = [], journal = [];
        const addSection = (title, hint, text, add) => {
          const section = el('section'); section.append(el('h2', title), el('p', hint));
          const list = el('div'), button = el('button', text); button.type = 'button'; button.onclick = () => { add(list); dirty(); };
          section.append(list, button); form.append(section); return list;
        };
        const remove = (node, row) => {
          const button = el('button', 'Remove'); button.type = 'button'; button.onclick = () => { row.removed = true; node.remove(); dirty(); }; node.append(button);
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

    const identity = section('Identity details'); identity.classList.add('entity-soul'); identity.append(form);
    const profile = section('Identity matching helpers'), grid = el('div'); grid.className='profile-fields'; profile.append(grid);
    const identityFields = el('div'); identityFields.className='profile-fields'; form.prepend(identityFields);
    const contacts = el('div'); contacts.className='soul-contact-fields profile-wide';
    const fieldsByName = {}, existing = context.entity.profile || {};
    for (const [key,title,multi] of [['name','Display name',false],['aliases','Aliases (one per line)',true],['partial_aliases','Partial matching hints (one per line)',true],['categories','Categories',true],['emails','Email addresses',true],['phones','Phone numbers',true],['references','References',true],['notes','Notes',true]]) {
      const value=key==='name'?(existing.name||context.entity.label):Array.isArray(existing[key])?existing[key].join('\n'):existing[key]||'';
      const parent = key==='name' ? identityFields : ['phones','references'].includes(key) ? contacts : grid;
      const input=field(parent,title,value,multi);fieldsByName[key]=input;
      if(['phones','references'].includes(key)){input.rows=1;input.parentElement.className='';}
      if(key==='name')input.parentElement.className='profile-wide';
      if(key==='name'){input.required=true;input.maxLength=120;input.readOnly=!!context.entity.is_owner;}
    }
    identityFields.append(contacts);
    if(context.entity.is_owner){const owner=el('a','Corpus owner · Change your name in /profile');owner.href='/profile';owner.target='_blank';owner.rel='noopener';identityFields.append(owner);}
    const preferred=el('input');preferred.type='checkbox';preferred.checked=!!existing.preferred_name;
    const preferLabel=el('label','Prefer this display name during automatic merges');preferLabel.prepend(preferred);profile.append(preferLabel);
    return {profile,identity,collectProfile:()=>Object.fromEntries([...Object.entries(fieldsByName).map(([k,v])=>[k,['name','notes'].includes(k)?v.value:lines(v)]),['preferred_name',preferred.checked]]),collectIdentity:()=>{
            return  {version: soul.version, markdown: markdown.value,
              identity_rules: rules.filter(r => !r.removed).map(r => ({id:r.id, observed_name:r.name.value, sources:lines(r.sources), required_context:lines(r.required), excluded_context:lines(r.excluded), enabled:r.enabled.checked})),
              relationships: soul.relationships.map(({id,target_id,relation,since,until,evidence}) => ({id,target_id,relation,since,until,evidence})),
              journal: journal.filter(r => !r.removed).map(r => ({id:r.id, text:r.text.value}))};

    }};
  };
})();
