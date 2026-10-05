
(() => {
  const activityStateKey = 'hfl-corpus:activity-expanded';
  const readActivityState = () => {
    try { return window.sessionStorage.getItem(activityStateKey); }
    catch (error) { return null; }
  };
  const writeActivityState = expanded => {
    try { window.sessionStorage.setItem(activityStateKey, String(expanded)); }
    catch (error) { /* Storage can be unavailable in private contexts. */ }
  };
  const syncYearState = value => {
    if (document.querySelector('[data-activity-panel][data-readonly="true"]')) return;
    const pageUrl = new URL(window.location.href);
    pageUrl.searchParams.set('activity_year', value);
    pageUrl.searchParams.delete('page');
    if (pageUrl.searchParams.get('date_field') === 'entry') {
      pageUrl.searchParams.delete('date_field');
      pageUrl.searchParams.delete('date_from');
      pageUrl.searchParams.delete('date_to');
    }
    window.history.replaceState({}, '', pageUrl);
    const hiddenYear = document.querySelector('input[name="activity_year"]');
    if (hiddenYear) hiddenYear.value = value;
    document.querySelectorAll('a[href^="/hfl-corpus"]').forEach(link => {
      const linkUrl = new URL(link.href);
      if (linkUrl.pathname !== '/hfl-corpus') return;
      linkUrl.searchParams.set('activity_year', value);
      link.href = `${linkUrl.pathname}${linkUrl.search}${linkUrl.hash}`;
    });
  };

  const initActivityPanel = panel => {
    if (!panel || panel.dataset.activityReady === 'true') return;
    panel.dataset.activityReady = 'true';
    const readOnly = panel.dataset.readonly === 'true';
    if (readOnly) {
      panel.addEventListener('click', event => { if (event.target.closest('[data-activity-day]')) { event.preventDefault(); event.stopImmediatePropagation(); } }, true);
      document.querySelectorAll('[data-memory-dialog], [data-agent-history-dialog]').forEach(dialog => { dialog.inert = true; });
    }
    const scroll = panel.querySelector('[data-activity-scroll]');
    const previousYearCoachmark = panel.querySelector('[data-activity-previous-year]');
    const nextYearCoachmark = panel.querySelector('[data-activity-next-year]');
    const year = panel.querySelector('[data-activity-year]');
    const yearControls = panel.querySelector('.activity-year-controls');
    const yearTrigger = panel.querySelector('[data-activity-year-trigger]');
    const yearTriggerValue = panel.querySelector('[data-activity-year-trigger-value]');
    const yearList = panel.querySelector('[data-activity-year-list]');
    const yearOptions = Array.from(panel.querySelectorAll('[data-activity-year-option]'));
    const toggle = panel.querySelector('[data-activity-toggle]');
    const body = panel.querySelector('[data-activity-body]');
    let days = Array.from(panel.querySelectorAll('[data-activity-day]'));
    let interactiveDays = days.filter(day => !day.disabled);
    const timelineData = JSON.parse(document.querySelector('[data-activity-timeline]')?.textContent || '{}');
    const menu = panel.querySelector('[data-activity-day-menu]');
    const menuDate = menu?.querySelector('[data-activity-menu-date]');
    const createEntry = menu?.querySelector('[data-activity-menu-create]');
    const pinDates = menu?.querySelector('[data-activity-menu-pin]');
    const showDocument = menu?.querySelector('[data-activity-menu-document]');
    const matchingEntries = menu?.querySelector('[data-activity-menu-matches]');
    const matchingPanel = menu?.querySelector('[data-activity-menu-matches-panel]');
    const matchingContent = menu?.querySelector('[data-activity-menu-matches-content]');
    const memoryDialog = document.querySelector('[data-memory-dialog]');
    const memoryForm = memoryDialog?.querySelector('[data-memory-form]');
    const pinList = panel.querySelector('[data-activity-pin-list]');
    const todayShortcuts = Array.from(panel.querySelectorAll('[data-activity-today]'));
    const selectionStatus = panel.querySelector('[data-pin-selection-status]');
    if (!scroll || !previousYearCoachmark || !nextYearCoachmark || !year || !body || !menu || !menuDate || !createEntry || !pinDates || !showDocument || !matchingEntries || !matchingPanel || !matchingContent || !memoryDialog || !memoryForm || !pinList) return;
    const activityController = new AbortController();
    panel.activityAbortController = activityController;
    const menuHeader = menu.querySelector('.activity-day-menu-header');
    const menuHeaderObserver = new ResizeObserver(() => {
      menu.style.setProperty('--day-menu-header-height', `${menuHeader.getBoundingClientRect().height}px`);
    });
    menuHeaderObserver.observe(menuHeader);
    activityController.signal.addEventListener('abort', () => menuHeaderObserver.disconnect(), {once:true});
    let menuTrigger = null;
    let matchingAbortController = null;
    let memoryState = JSON.parse(document.querySelector('[data-memory-pins]')?.textContent || '{"categories":[],"ranges":[],"palette":[]}');
    const memoryCsrf = JSON.parse(document.querySelector('[data-memory-csrf]')?.textContent || '""');
    let pinStart = '';
    let editingRange = null;
    let editingCategory = null;
    let selectedColor = memoryState.palette[0];
    let wireDays = () => {};
    const yearLoads = new Map();


    const memoryRefs = {
      title: memoryDialog.querySelector('[data-memory-dialog-title]'),
      summary: memoryDialog.querySelector('[data-memory-range-summary]'),
      error: memoryDialog.querySelector('[data-memory-error]'),
      categorySelect: memoryDialog.querySelector('[data-memory-category-select]'),
      categoryEditor: memoryDialog.querySelector('[data-memory-category-editor]'),
      categoryName: memoryDialog.querySelector('[data-memory-category-name]'),
      categoryWorkspaces: memoryDialog.querySelector('[data-memory-category-workspaces]'),
      palette: memoryDialog.querySelector('[data-memory-palette]'),
      categorySave: memoryDialog.querySelector('[data-memory-category-save]'),
      categoryDelete: memoryDialog.querySelector('[data-memory-category-delete]'),
      rangeFields: memoryDialog.querySelector('[data-memory-range-fields]'),
      start: memoryDialog.querySelector('[data-memory-start]'),
      end: memoryDialog.querySelector('[data-memory-end]'),
      note: memoryDialog.querySelector('[data-memory-note]'),
      pinTitle: memoryDialog.querySelector('[data-memory-pin-title]'),
      rangeDelete: memoryDialog.querySelector('[data-memory-range-delete]'),
      rangeSave: memoryDialog.querySelector('[data-memory-range-save]'),
    };

    const formatDate = value => new Date(`${value}T12:00:00`).toLocaleDateString(undefined, {year:'numeric', month:'short', day:'numeric'});
    const formatRange = range => range.start_date === range.end_date
      ? formatDate(range.start_date)
      : `${formatDate(range.start_date)} – ${formatDate(range.end_date)}`;
    const formatPinnedEnd = range => {
      const value = new Date(`${range.end_date}T12:00:00`);
      const day = String(value.getDate()).padStart(2, '0');
      const month = value.toLocaleDateString('en-GB', {month:'short'}).slice(0, 3).toUpperCase();
      return `ENDS ${day} ${month} ${value.getFullYear()}`;
    };
    const categoryFor = id => memoryState.categories.find(category => category.id === Number(id));
    const selectedWorkspaceIds = () => {
      const params = new URLSearchParams(location.search);
      return (params.get('views') || params.get('workspace') || params.get('workspace_ids') || '').split(',').filter(Boolean);
    };
    const visibleRanges = () => {
      const selected = selectedWorkspaceIds();
      return selected.length ? memoryState.ranges.filter(range =>
        (categoryFor(range.category_id)?.workspace_ids || []).some(id => selected.includes(id))) : memoryState.ranges;
    };
    const rangeDuration = range => Date.parse(`${range.end_date}T00:00:00Z`)
      - Date.parse(`${range.start_date}T00:00:00Z`);
    const rangesForDate = value => visibleRanges()
      .filter(range => range.start_date <= value && value <= range.end_date)
      .sort((a, b) => rangeDuration(a) - rangeDuration(b)
        || b.updated_at.localeCompare(a.updated_at)
        || Number(b.id) - Number(a.id));

    const showMemoryError = message => {
      memoryRefs.error.textContent = message;
      memoryRefs.error.hidden = !message;
    };
    const postMemory = async payload => {
      if (readOnly) throw new Error('This heatmap is read-only.');
      const response = await fetch('/hfl-corpus/memory-pins', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({csrf: memoryCsrf, ...payload}),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Memory Signal changes could not be saved.');
      memoryState = result;
      renderMemoryState();
      return result;
    };
    const promptEditors = {};
    memoryDialog.querySelectorAll('[data-prompt-editor]').forEach(el => {
      const input=el.querySelector('[data-prompt-input]'), preview=el.querySelector('[data-prompt-preview]'), toggle=el.querySelector('[data-prompt-toggle]');
      let version=0;
      const showPreview=async () => {
        const ticket=++version;
        input.hidden=true;preview.hidden=false;toggle.textContent='Edit';toggle.setAttribute('aria-expanded','false');
        preview.textContent=input.value.trim()?'Loading preview…':'Select edit to add';
        if(!input.value.trim())return;
        try {
          const response=await fetch('/hfl-corpus/memory-pins',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf:memoryCsrf,action:'preview_prompt',prompt:input.value})});
          const result=await response.json();if(!response.ok)throw new Error(result.detail||'Preview unavailable');
          if(ticket===version)preview.innerHTML=result.html;
        } catch(error) {if(ticket===version)preview.textContent='Preview unavailable. Select Edit to view your text.';}
      };
      toggle.addEventListener('click',()=>{
        if(input.hidden){++version;input.hidden=false;preview.hidden=true;toggle.textContent='Preview';toggle.setAttribute('aria-expanded','true');input.focus();}
        else void showPreview();
      });
      promptEditors[el.dataset.promptEditor]={input,set(value){input.value=value||'';void showPreview();}};
    });
    const scrollToDate = async (value, {behavior='', focus=true}={}) => {
      const selectedYear = value.slice(0, 4);
      const segment = panel.querySelector(`[data-activity-year-segment="${selectedYear}"]`);
      await loadYear(segment, {retry:true});
      const target = panel.querySelector(`[data-activity-day="${value}"]`);
      if (!target) return;
      year.value = selectedYear;
      yearOptions.forEach(option => option.setAttribute('aria-selected', String(option.dataset.activityYearOption === selectedYear)));
      syncYearState(selectedYear);
      updateYearCoachmarks(selectedYear);
      centerSelectedYear();
      window.requestAnimationFrame(() => {
        target.scrollIntoView({
          behavior: behavior || (window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'),
          block:'nearest',
          inline:'center',
        });
        if (focus) target.focus({preventScroll:true});
      });
    };
    const midpoint = range => {
      const start = Date.parse(`${range.start_date}T00:00:00Z`);
      const end = Date.parse(`${range.end_date}T00:00:00Z`);
      return new Date((start + end) / 2).toISOString().slice(0, 10);
    };
    const populateCategories = selectedId => {
      memoryRefs.categorySelect.replaceChildren();
      if (!memoryState.categories.length) {
        const empty = document.createElement('option');
        empty.value = '';
        empty.textContent = 'Create a category first';
        memoryRefs.categorySelect.append(empty);
      }
      memoryState.categories.forEach(category => {
        const option = document.createElement('option');
        option.value = category.id;
        option.textContent = category.name;
        option.selected = category.id === Number(selectedId);
        memoryRefs.categorySelect.append(option);
      });
      memoryRefs.categorySelect.disabled = !memoryState.categories.length;
      memoryRefs.rangeSave.disabled = !memoryState.categories.length;
    };
    const renderPalette = () => {
      memoryRefs.palette.replaceChildren();
      memoryState.palette.forEach(color => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'memory-color';
        button.style.setProperty('--pin-color', color);
        button.setAttribute('aria-label', `Use ${color}`);
        button.setAttribute('aria-pressed', String(color === selectedColor));
        button.addEventListener('click', () => {
          selectedColor = color;
          memoryRefs.palette.querySelectorAll('button').forEach(swatch => swatch.setAttribute('aria-pressed', String(swatch === button)));
        });
        memoryRefs.palette.append(button);
      });
    };
    const historyDialog = document.querySelector('[data-agent-history-dialog]');
    const openCategoryEditor = category => {
      if (readOnly) return;
      editingCategory = category || null;
      selectedColor = category?.color || memoryState.palette.find(color => !memoryState.categories.some(item => item.color === color)) || memoryState.palette[0];
      memoryRefs.categoryName.value = category?.name || '';
      memoryRefs.categoryWorkspaces.replaceChildren();
      memoryRefs.workspacePicker = window.HflWorkspacePicker(memoryRefs.categoryWorkspaces, {
        selected: category?.workspace_ids || (category ? [] : selectedWorkspaceIds()),
        empty: 'No workspace', name: 'workspace_ids',
      });
      promptEditors.category.set(category?.instructions);
      memoryRefs.categoryDelete.hidden = !category;
      memoryRefs.categoryDelete.textContent = category?.archived_at ? 'Restore category' : 'Archive category';
      const history = memoryDialog.querySelector('[data-category-history]');
      history.hidden = !category;
      historyDialog.querySelector('[data-category-events]').replaceChildren();
      historyDialog.querySelector('[data-history-more]').hidden = true;
      memoryRefs.categoryEditor.hidden = false;
      renderPalette();
      memoryRefs.categoryName.focus();
    };
    const openMemoryDialog = ({range=null, start='', end='', categoryOnly=false, category=null}={}) => {
      if (readOnly) return;
      if (!memoryDialog.inputAttachments) memoryDialog.inputAttachments = new window.HflInputAttachments(memoryDialog.querySelector('[data-input-editor]'), 'pin');
      memoryDialog.inputAttachments.reset(range?.id);
      editingRange = range;
      editingCategory = null;
      showMemoryError('');
      memoryRefs.title.textContent = categoryOnly ? 'Manage category' : (range ? 'Edit pinned block' : 'Pin a date block');
      memoryRefs.summary.textContent = categoryOnly ? 'Create or rename a color-coded memory category.' : formatRange({start_date:start || range?.start_date, end_date:end || range?.end_date});
      memoryRefs.rangeFields.hidden = categoryOnly;
      memoryRefs.rangeSave.hidden = categoryOnly;
      memoryRefs.rangeDelete.hidden = categoryOnly || !range;
      memoryRefs.categoryEditor.hidden = !categoryOnly;
      memoryRefs.start.value = start || range?.start_date || '';
      memoryRefs.end.value = end || range?.end_date || '';
      memoryRefs.start.min = timelineData.start;
      memoryRefs.start.max = timelineData.calendar_end;
      memoryRefs.end.min = timelineData.start;
      memoryRefs.end.max = timelineData.calendar_end;
      memoryRefs.note.value = range?.note || '';
      memoryRefs.pinTitle.value = range?.title || '';
      memoryRefs.pinTitle.required = !categoryOnly;
      promptEditors.range.set(range?.prompt);
      const savedHour = range?.execution_hour ?? 0;
      document.getElementById('pin-execution-hour').value = savedHour % 12 || 12;
      document.getElementById('pin-execution-period').value = savedHour >= 12 ? 'PM' : 'AM';
      document.getElementById('pin-agent-enabled').checked = range ? Boolean(range.agent_enabled) : true;
      updatePinScheduleHelp();
      populateCategories(range?.category_id || memoryState.categories[0]?.id);
      if (categoryOnly) openCategoryEditor(category);
      else if (!memoryState.categories.length) openCategoryEditor(null);
      memoryDialog.showModal();
    };
    function updatePinScheduleHelp() {
      const enabled = document.getElementById('pin-agent-enabled').checked;
      const hour = document.getElementById('pin-execution-hour');
      const period = document.getElementById('pin-execution-period');
      const timezone = document.querySelector('[data-pin-timezone]').dataset.pinTimezone;
      hour.disabled = period.disabled = !enabled;
      document.querySelector('[data-pin-schedule-help]').textContent = enabled
        ? `Runs daily at ${hour.value}:00 ${period.value} (${timezone}) during this pinned period. Recent missed runs are caught up automatically.`
        : `Daily runs are off. Enable Run instructions daily to schedule these instructions (${timezone}).`;
    }
    for (const id of ['pin-agent-enabled', 'pin-execution-hour', 'pin-execution-period']) {
      document.getElementById(id).addEventListener('change', updatePinScheduleHelp);
    }
    const renderMemoryState = () => {
      const archived = memoryDialog.querySelector('[data-archived-categories]');
      const archivedList = memoryDialog.querySelector('[data-archived-list]');
      archived.hidden = !(memoryState.archived_categories || []).length;
      archivedList.replaceChildren();
      (memoryState.archived_categories || []).forEach(category => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'text-left rounded-lg border border-slate-700 p-2 text-xs text-slate-200';
        button.textContent = `${category.name} · View history / restore`;
        button.addEventListener('click', () => openCategoryEditor(category));
        archivedList.append(button);
      });
      days.forEach(day => {
        const matches = rangesForDate(day.dataset.activityDay);
        const primary = matches[0];
        const category = primary && categoryFor(primary.category_id);
        day.dataset.pinned = String(Boolean(category));
        if (category) day.style.setProperty('--pin-color', category.color);
        else day.style.removeProperty('--pin-color');
        const base = day.getAttribute('aria-label')?.split(' · Pinned:')[0] || '';
        const details = matches.map(range => {
          const itemCategory = categoryFor(range.category_id);
          return `${itemCategory?.name || 'Pinned'}${range.note ? ` — ${range.note}` : ''}`;
        });
        const label = details.length ? `${base} · Pinned: ${details.join('; ')}` : base;
        day.setAttribute('aria-label', label);
        day.title = label;
      });
      const collapsedCategories = new Set(
        [...pinList.querySelectorAll('details:not([open])')].map(details => details.dataset.categoryId)
      );
      const pinScrollTop = pinList.scrollTop;
      pinList.replaceChildren();
      const pinnedRanges = visibleRanges();
      if (!pinnedRanges.length) {
        const empty = document.createElement('p');
        empty.className = 'activity-pin-empty';
        empty.textContent = 'Nothing here';
        pinList.append(empty);
        return;
      }
      const todayStamp = Date.parse(`${timelineData.end}T00:00:00Z`);
      const categoryDistance = new Map();
      pinnedRanges.forEach(range => {
        const start = Date.parse(`${range.start_date}T00:00:00Z`);
        const end = Date.parse(`${range.end_date}T00:00:00Z`);
        const distance = Math.max(start - todayStamp, todayStamp - end, 0);
        categoryDistance.set(range.category_id, Math.min(categoryDistance.get(range.category_id) ?? Infinity, distance));
      });
      const sortedCategories = [...memoryState.categories].sort((a, b) =>
        (categoryDistance.get(a.id) ?? Infinity) - (categoryDistance.get(b.id) ?? Infinity)
        || a.name.localeCompare(b.name) || a.id - b.id);
      sortedCategories.forEach(category => {
        const categoryRanges = pinnedRanges
          .filter(range => range.category_id === category.id)
          .sort((a, b) => b.end_date.localeCompare(a.end_date)
            || b.start_date.localeCompare(a.start_date)
            || Number(b.id) - Number(a.id));
        if (!categoryRanges.length) return;
        const details = document.createElement('details');
        details.className = 'activity-category';
        details.dataset.categoryId = String(category.id);
        details.open = !collapsedCategories.has(String(category.id));
        const summary = document.createElement('summary');
        summary.className = 'activity-category-button cursor-pointer list-none';
        const dot = document.createElement('span');
        dot.className = 'activity-category-dot';
        dot.style.setProperty('--pin-color', category.color);
        const name = document.createElement('span');
        name.className = 'activity-category-name flex-1';
        name.textContent = category.name;
        const edit = document.createElement('button');
        edit.type = 'button';
        edit.textContent = 'Edit';
        edit.className = 'text-[9px] text-slate-500 hover:text-white';
        edit.addEventListener('click', event => { event.preventDefault(); openMemoryDialog({categoryOnly:true, category}); });
        summary.append(dot, name);
        if (!readOnly) summary.append(edit);
        const rangeList = document.createElement('div');
        rangeList.className = 'activity-category-ranges';
        categoryRanges.forEach(range => {
          const row = document.createElement('div');
          row.className = 'activity-range-row';
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'activity-range-button';
          const label = document.createElement('span');
          label.className = 'activity-range-label';
          label.textContent = range.title || 'Untitled pin';
          button.append(label);
          button.title = `${label.textContent} ${formatPinnedEnd(range)}`;
          button.addEventListener('click', () => scrollToDate(midpoint(range)));
          if (!readOnly) button.addEventListener('click', () => window.dispatchEvent(new CustomEvent('hfl:timeline-period',{detail:{start:range.start_date,end:range.end_date}})));
          const editRange = document.createElement('button');
          editRange.type = 'button';
          editRange.className = 'activity-range-edit';
          editRange.textContent = 'Edit';
          editRange.setAttribute('aria-label', `Edit ${range.title || 'Untitled pin'}`);
          editRange.addEventListener('click', () => openMemoryDialog({range}));
          const agentWork = document.createElement('button');
          agentWork.type = 'button'; agentWork.className = 'activity-range-edit'; agentWork.textContent = 'Agent';
          agentWork.setAttribute('aria-label', `Agent work for ${range.title || 'Untitled pin'}`);
          agentWork.addEventListener('click', () => window.hflAgentBridge.open('pin', range.id, range.title || 'Untitled pin'));
          row.append(button);
          if (!readOnly) row.append(editRange, agentWork);
          rangeList.append(row);
        });
        details.append(summary, rangeList);
        pinList.append(details);
      });
      pinList.scrollTop = pinScrollTop;
    };
    const previewRange = end => {
      const low = pinStart < end ? pinStart : end;
      const high = pinStart < end ? end : pinStart;
      days.forEach(day => { day.dataset.rangePreview = String(low <= day.dataset.activityDay && day.dataset.activityDay <= high); });
    };
    const clearPreview = () => days.forEach(day => { delete day.dataset.rangePreview; });
    const finishPinRange = end => {
      const start = pinStart < end ? pinStart : end;
      const finish = pinStart < end ? end : pinStart;
      pinStart = '';
      clearPreview();
      if (selectionStatus) selectionStatus.hidden = true;
      openMemoryDialog({start, end:finish});
    };
    const enableDragScroll = (element, axis, canStart=() => true) => {
      let pointerId = null;
      let startPosition = 0;
      let startScroll = 0;
      let dragged = false;
      let suppressNextClick = false;
      const coordinate = event => axis === 'x' ? event.clientX : event.clientY;
      element.addEventListener('pointerdown', event => {
        if (event.button !== 0 || !canStart()) return;
        pointerId = event.pointerId;
        startPosition = coordinate(event);
        startScroll = axis === 'x' ? element.scrollLeft : element.scrollTop;
        dragged = false;
      });
      element.addEventListener('pointermove', event => {
        if (event.pointerId !== pointerId) return;
        const delta = coordinate(event) - startPosition;
        if (!dragged && Math.abs(delta) < 5) return;
        if (!dragged) element.setPointerCapture?.(pointerId);
        dragged = true;
        element.dataset.dragging = 'true';
        if (axis === 'x') element.scrollLeft = startScroll - delta;
        else element.scrollTop = startScroll - delta;
        event.preventDefault();
      });
      const finish = event => {
        if (event.pointerId !== pointerId) return;
        if (dragged) {
          suppressNextClick = true;
        }
        delete element.dataset.dragging;
        if (element.hasPointerCapture?.(pointerId)) element.releasePointerCapture(pointerId);
        pointerId = null;
      };
      element.addEventListener('pointerup', finish);
      element.addEventListener('pointercancel', finish);
      element.addEventListener('click', event => {
        if (!suppressNextClick) return;
        suppressNextClick = false;
        event.preventDefault();
        event.stopPropagation();
      }, true);
    };
    const enableWheelScroll = element => {
      element.addEventListener('wheel', event => {
        const maxScroll = element.scrollWidth - element.clientWidth;
        if (maxScroll <= 0) return;
        const rawDelta = Math.abs(event.deltaX) > Math.abs(event.deltaY)
          ? event.deltaX
          : event.deltaY;
        if (!rawDelta) return;
        const scale = event.deltaMode === WheelEvent.DOM_DELTA_LINE
          ? 16
          : event.deltaMode === WheelEvent.DOM_DELTA_PAGE
            ? element.clientWidth
            : 1;
        const delta = rawDelta * scale;
        const canContinue = delta < 0
          ? element.scrollLeft > 0
          : element.scrollLeft < maxScroll;
        if (!canContinue) return;
        event.preventDefault();
        element.scrollLeft = Math.min(maxScroll, Math.max(0, element.scrollLeft + delta));
      }, {passive:false});
    };
    const isoWeek = value => {
      const target = new Date(Date.UTC(value.getFullYear(), value.getMonth(), value.getDate()));
      target.setUTCDate(target.getUTCDate() + 4 - (target.getUTCDay() || 7));
      const yearStart = new Date(Date.UTC(target.getUTCFullYear(), 0, 1));
      return Math.ceil((((target - yearStart) / 86400000) + 1) / 7);
    };
    const calendarWeekCount = selectedYear => {
      const first = new Date(`${selectedYear}-01-01T12:00:00`);
      const last = new Date(`${selectedYear}-12-31T12:00:00`);
      first.setDate(first.getDate() - ((first.getDay() + 6) % 7));
      last.setDate(last.getDate() + (7 - (last.getDay() || 7)));
      return Math.floor((last - first) / 604800000) + 1;
    };
    panel.querySelectorAll('[data-activity-year-segment]').forEach(segment => {
      segment.style.setProperty('--activity-weeks', calendarWeekCount(Number(segment.dataset.activityYearSegment)));
    });
    const hydrateYear = (segment, {animate=false}={}) => {
      if (!segment || segment.dataset.activityHydrated === 'true') return;
      const selectedYear = Number(segment.dataset.activityYearSegment);
      const first = new Date(`${selectedYear}-01-01T12:00:00`);
      const last = new Date(`${selectedYear}-12-31T12:00:00`);
      const cursor = new Date(first);
      cursor.setDate(cursor.getDate() - ((cursor.getDay() + 6) % 7));
      const final = new Date(last);
      final.setDate(final.getDate() + (7 - (final.getDay() || 7)));
      const yearCounts = Object.entries(timelineData.counts || {}).filter(([key]) => key.startsWith(`${selectedYear}-`)).map(([, count]) => Number(count));
      const peak = Math.max(0, ...yearCounts);
      const stagger = animate && !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const reveal = [];
      let weekIndex = 0;
      let lastMonth = null;
      while (cursor <= final) {
        const week = document.createElement('div');
        week.className = 'activity-week';
        week.dataset.activityWeek = isoWeek(cursor);
        let monthLabel = '';
        const weekDays = [];
        for (let offset = 0; offset < 7; offset += 1) {
          const value = new Date(cursor);
          value.setDate(cursor.getDate() + offset);
          const iso = `${value.getFullYear()}-${String(value.getMonth()+1).padStart(2,'0')}-${String(value.getDate()).padStart(2,'0')}`;
          const inRange = value.getFullYear() === selectedYear && timelineData.start <= iso && iso <= timelineData.calendar_end;
          if (inRange && value.getMonth() !== lastMonth) {
            monthLabel = value.toLocaleDateString(undefined, {month:'short'});
            lastMonth = value.getMonth();
          }
          if (!inRange) { weekDays.push(document.createElement('span')); weekDays.at(-1).className = 'activity-day-blank'; continue; }
          const count = Number(timelineData.counts?.[iso] || 0);
          const level = count && peak ? Math.min(4, Math.max(1, Math.ceil(Math.log1p(count) / Math.log1p(peak) * 4))) : 0;
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'activity-day';
          button.dataset.activityDay = iso;
          button.dataset.level = stagger && level ? 0 : level;
          if (stagger && level) reveal.push({button, level, delay:weekIndex * 11});
          button.dataset.today = String(iso === timelineData.end);
          button.dataset.selected = String(iso === timelineData.selected_day);
          button.dataset.count = count;
          const path = timelineData.documents?.[iso] || '';
          button.dataset.documentUrl = path ? `/hfl-corpus/document/${path.split('/').map(encodeURIComponent).join('/')}` : '';
          const matches = new URL(`/hfl-corpus/day-matches/${iso}`, window.location.origin);
          matches.searchParams.set('scope', timelineData.scope || '');
          matches.searchParams.set('q', timelineData.query || '');
          matches.searchParams.set('source', timelineData.source || '');
          if (timelineData.show_secrets) matches.searchParams.set('show_secrets', 'true');
          button.dataset.matchesUrl = `${matches.pathname}${matches.search}`;
          const isFuture = iso > timelineData.end;
          button.dataset.future = String(isFuture);
          const label = `${value.toLocaleDateString(undefined, {weekday:'long', year:'numeric', month:'long', day:'numeric'})} · Week ${isoWeek(value)} · ${count} ${count === 1 ? 'entry' : 'entries'}${isFuture ? ' · Future date' : ''}`;
          button.setAttribute('aria-label', label);
          button.setAttribute('aria-pressed', String(iso === timelineData.selected_day));
          button.setAttribute('aria-haspopup', 'menu');
          button.setAttribute('aria-expanded', 'false');
          button.title = label;
          weekDays.push(button);
        }
        const month = document.createElement('span');
        month.className = 'activity-month';
        month.setAttribute('aria-hidden', 'true');
        month.textContent = monthLabel;
        const number = document.createElement('span');
        number.className = 'activity-week-number';
        number.setAttribute('aria-hidden', 'true');
        const weekNumber = isoWeek(cursor);
        number.textContent = weekIndex % 4 === 0 || weekNumber === 1 ? String(weekNumber).padStart(2,'0') : '';
        week.append(month, ...weekDays, number);
        segment.append(week);
        cursor.setDate(cursor.getDate() + 7);
        weekIndex += 1;
      }
      segment.style.setProperty('--activity-weeks', weekIndex);
      segment.dataset.activityHydrated = 'true';
      wireDays();
      renderMemoryState();
      if (reveal.length) {
        window.requestAnimationFrame(() => reveal.forEach(item => {
          window.setTimeout(() => { item.button.dataset.level = item.level; }, item.delay);
        }));
      }
    };

    const loadYear = (segment, {retry=false}={}) => {
      if (!segment) return Promise.resolve(false);
      if (segment.dataset.activityLoaded === 'true') {
        hydrateYear(segment);
        return Promise.resolve(true);
      }
      const selectedYear = segment.dataset.activityYearSegment;
      if (yearLoads.has(selectedYear)) return yearLoads.get(selectedYear);
      if (segment.dataset.activityLoadFailed === 'true' && !retry) return Promise.resolve(false);
      segment.dataset.activityLoading = 'true';
      delete segment.dataset.activityLoadFailed;
      const endpoint = new URL(`/hfl-corpus/activity-year/${selectedYear}`, window.location.origin);
      endpoint.searchParams.set('scope', timelineData.scope || '');
      endpoint.searchParams.set('q', timelineData.query || '');
      endpoint.searchParams.set('source', timelineData.source || '');
      if (timelineData.show_secrets) endpoint.searchParams.set('show_secrets', 'true');
      const request = fetch(`${endpoint.pathname}${endpoint.search}`, {headers:{Accept:'application/json'}})
        .then(async response => {
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.detail || `Activity for ${selectedYear} could not be loaded.`);
          timelineData.counts = Object.assign(timelineData.counts || {}, payload.counts || {});
          timelineData.documents = Object.assign(timelineData.documents || {}, payload.documents || {});
          segment.dataset.activityLoaded = 'true';
          delete segment.dataset.activityLoading;
          hydrateYear(segment, {animate:true});
          return true;
        })
        .catch(() => {
          delete segment.dataset.activityLoading;
          segment.dataset.activityLoadFailed = 'true';
          return false;
        })
        .finally(() => yearLoads.delete(selectedYear));
      yearLoads.set(selectedYear, request);
      return request;
    };

    const setActivityExpanded = expanded => {
      toggle?.setAttribute('aria-expanded', String(expanded));
      toggle?.setAttribute('aria-label', `${expanded ? 'Hide' : 'Show'} activity heat map`);
      body.hidden = !expanded;
    };
    const storedActivityState = toggle ? readActivityState() : 'true';
    if (storedActivityState !== null) {
      setActivityExpanded(storedActivityState === 'true');
    }

    const closeDayMenu = (restoreFocus = false) => {
      if (menu.hidden) return;
      menu.hidden = true;
      menu.querySelector('.activity-day-create').open = false;
      window.dispatchEvent(new Event('hfl:timeline-close'));
      menuTrigger?.setAttribute('aria-expanded', 'false');
      if (restoreFocus) menuTrigger?.focus();
      resetMatchingEntries();
      menuTrigger = null;
    };
    const resetMatchingEntries = () => {
      matchingAbortController?.abort();
      matchingAbortController = null;
      matchingEntries.setAttribute('aria-expanded', 'false');
      matchingPanel.hidden = true;
      matchingContent.replaceChildren();
      matchingContent.dataset.loaded = 'false';
      menu.dataset.matchesExpanded = 'false';
    };
    const positionDayMenu = button => {
      const safeTop = Math.max(8, (document.querySelector('body > header')?.getBoundingClientRect().bottom || 0) + 8);
      menu.style.setProperty('--day-menu-top', `${safeTop}px`);
      if (window.matchMedia('(max-width: 639px)').matches) {
        menu.style.removeProperty('left');
        menu.style.removeProperty('top');
        return;
      }
      const rect = button.getBoundingClientRect();
      const left = Math.min(
        window.innerWidth - menu.offsetWidth - 8,
        Math.max(8, rect.left + rect.width / 2 - menu.offsetWidth / 2),
      );
      const below = rect.bottom + 8;
      const top = below + menu.offsetHeight <= window.innerHeight - 8
        ? below
        : Math.max(safeTop, rect.top - menu.offsetHeight - 8);
      menu.style.left = `${left}px`;
      menu.style.top = `${Math.max(safeTop, Math.min(top, window.innerHeight - menu.offsetHeight - 8))}px`;
    };
    const dayCreate = menu.querySelector('.activity-day-create');
    dayCreate.addEventListener('keydown', event => {
      if (event.key === 'Escape' && dayCreate.open) {
        event.preventDefault(); event.stopPropagation(); dayCreate.open = false; dayCreate.querySelector('summary').focus();
      }
    });
    menu.addEventListener('click', event => {
      if (!event.target.closest('.activity-day-create > summary')) dayCreate.open = false;
    });
    dayCreate.addEventListener('focusout', event => {
      if (event.relatedTarget && !dayCreate.contains(event.relatedTarget)) dayCreate.open = false;
    });
    const selectDaySection = selected => {
      if (selected === 'ideas' && menu.querySelector('[data-activity-menu-ideas]').disabled) selected = 'actions';
      for (const name of ['matches','ideas','actions']) {
        const content = name === 'matches' ? matchingPanel : menu.querySelector(`[data-day-${name}]`);
        content.hidden = name !== selected;
        menu.querySelector(`[data-activity-menu-${name}]`).setAttribute('aria-expanded', String(name === selected));
      }
      menu.dataset.matchesExpanded = String(selected === 'matches');
      if (menuTrigger && !menu.hidden) positionDayMenu(menuTrigger);
    };
    for (const name of ['ideas','actions']) {
      menu.querySelector(`[data-activity-menu-${name}]`).addEventListener('click', event => {
        selectDaySection(event.currentTarget.getAttribute('aria-expanded') === 'true' ? null : name);
      });
    }
    window.addEventListener('hfl:day-section', event => selectDaySection(event.detail.section), {signal: activityController.signal});
    window.addEventListener('hfl:timeline-rendered', () => { if (!menu.hidden && menuTrigger) positionDayMenu(menuTrigger); }, {signal: activityController.signal});
    const openDayMenu = button => {
      if (readOnly) return;
      menu.scrollTop = 0;
      selectDaySection(null);
      window.dispatchEvent(new CustomEvent('hfl:timeline-period',{detail:{start:button.dataset.activityDay,end:button.dataset.activityDay}}));
      menuTrigger?.setAttribute('aria-expanded', 'false');
      resetMatchingEntries();
      menuTrigger = button;
      button.setAttribute('aria-expanded', 'true');
      const selectedDate = new Date(`${button.dataset.activityDay}T12:00:00`);
      menu.querySelector('[data-date-connections]').dataset.dateConnections = button.dataset.activityDay;
      const count = Number(button.dataset.count || 0);
      menuDate.textContent = `${selectedDate.toLocaleDateString(undefined, {
        weekday: 'short', year: 'numeric', month: 'short', day: 'numeric',
      })} · ${count} ${count === 1 ? 'entry' : 'entries'}`;
      const documentUrl = button.dataset.documentUrl;
      const matchesUrl = button.dataset.matchesUrl;
      const isFuture = button.dataset.future === 'true';
      const ideasToggle = menu.querySelector('[data-activity-menu-ideas]');
      ideasToggle.disabled = isFuture;
      ideasToggle.setAttribute('aria-disabled', String(isFuture));
      ideasToggle.classList.toggle('activity-day-menu-disabled', isFuture);
      selectDaySection('actions');
      const hasDocument = !isFuture && Boolean(documentUrl);
      const canShowMatches = !isFuture && Boolean(matchesUrl && (hasDocument || count > 0));
      createEntry.disabled = isFuture;
      createEntry.classList.toggle('activity-day-menu-disabled', isFuture);
      createEntry.setAttribute('aria-disabled', String(isFuture));
      showDocument.classList.toggle('activity-day-menu-disabled', !hasDocument);
      showDocument.setAttribute('aria-disabled', String(!hasDocument));
      showDocument.tabIndex = hasDocument ? 0 : -1;
      if (hasDocument) showDocument.href = documentUrl;
      else showDocument.removeAttribute('href');
      matchingEntries.disabled = !canShowMatches;
      matchingEntries.classList.toggle('activity-day-menu-disabled', !canShowMatches);
      matchingEntries.setAttribute('aria-disabled', String(!canShowMatches));
      menu.hidden = false;
      menu.scrollTop = 0;
      positionDayMenu(button);
      (isFuture ? pinDates : createEntry).focus();
    };

    let draggingRange = false;
    let suppressRangeClick = false;
    wireDays = () => {
      days = Array.from(panel.querySelectorAll('[data-activity-day]'));
      interactiveDays = days.filter(day => !day.disabled);
      interactiveDays.forEach((button, index) => {
      if (button.dataset.activityWired === 'true') return;
      button.dataset.activityWired = 'true';
      if (readOnly) { button.removeAttribute('aria-haspopup'); button.removeAttribute('aria-expanded'); button.removeAttribute('aria-pressed'); }
      button.addEventListener('click', () => {
        if (readOnly) return;
        if (suppressRangeClick) { suppressRangeClick = false; return; }
        if (pinStart) finishPinRange(button.dataset.activityDay);
        else openDayMenu(button);
      });
      button.addEventListener('pointerdown', event => {
        if (!pinStart || event.button !== 0) return;
        draggingRange = true;
        previewRange(button.dataset.activityDay);
      });
      button.addEventListener('pointerenter', () => {
        if (draggingRange && pinStart) previewRange(button.dataset.activityDay);
      });
      button.addEventListener('pointerup', event => {
        if (!draggingRange || !pinStart) return;
        draggingRange = false;
        suppressRangeClick = true;
        finishPinRange(button.dataset.activityDay);
      });
      button.addEventListener('keydown', event => {
        const movement = {
          ArrowLeft: -7,
          ArrowRight: 7,
          ArrowUp: -1,
          ArrowDown: 1,
        }[event.key];
        if (!movement) return;
        event.preventDefault();
        const currentIndex = interactiveDays.indexOf(button);
        interactiveDays[Math.min(interactiveDays.length - 1, Math.max(0, currentIndex + movement))]?.focus();
      });
      });
    };
    wireDays();
    enableDragScroll(scroll, 'x', () => !pinStart);
    enableWheelScroll(scroll);
    enableDragScroll(pinList, 'y');
    const yearObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => { if (entry.isIntersecting) void loadYear(entry.target); });
    }, {root: scroll, rootMargin:'0px 100%'});
    panel.querySelectorAll('[data-activity-year-segment]').forEach(segment => yearObserver.observe(segment));
    createEntry.addEventListener('click', () => {
      const selectedDate = menuTrigger?.dataset.activityDay;
      closeDayMenu();
      if (selectedDate) {
        document.dispatchEvent(new CustomEvent('hfl:create-entry-for-date', {detail: {date: selectedDate}}));
      }
    });
    menu.querySelector('[data-activity-menu-create-action]').addEventListener('click', () => {
      const selectedDate = menuTrigger?.dataset.activityDay;
      closeDayMenu();
      window.dispatchEvent(new CustomEvent('hfl:create-action', {detail: {date: selectedDate}}));
    });
    menu.querySelector('[data-activity-menu-create-idea]').addEventListener('click', () => {
      const selectedDate = menuTrigger?.dataset.activityDay;
      closeDayMenu();
      window.dispatchEvent(new CustomEvent('hfl:create-idea', {detail: {date: selectedDate}}));
    });
    pinDates.addEventListener('click', () => {
      pinStart = menuTrigger?.dataset.activityDay || '';
      closeDayMenu();
      if (!pinStart) return;
      previewRange(pinStart);
      if (selectionStatus) selectionStatus.hidden = false;
    });
    panel.querySelector('[data-memory-category-new]')?.addEventListener('click', () => openMemoryDialog({categoryOnly:true}));
    todayShortcuts.forEach(shortcut => shortcut.addEventListener('click', () => {
        closeDayMenu();
        setYearMenuOpen(false);
        void scrollToDate(timelineData.end);
      }, {signal: activityController.signal}));
    memoryDialog.querySelectorAll('[data-memory-dialog-close]').forEach(button => button.addEventListener('click', () => memoryDialog.close()));
    memoryDialog.querySelector('[data-memory-category-toggle]')?.addEventListener('click', () => {
      const selected = categoryFor(memoryRefs.categorySelect.value);
      openCategoryEditor(selected || null);
    });
    memoryRefs.categorySave.addEventListener('click', async () => {
      showMemoryError('');
      try {
        const name = memoryRefs.categoryName.value;
        memoryRefs.workspacePicker.close();
        await postMemory({
          action:'save_category',
          category_id:editingCategory?.id || null,
          name,
          color:selectedColor,
          instructions:promptEditors.category.input.value,
          workspace_ids: Array.from(memoryRefs.categoryWorkspaces.querySelectorAll('input[type="hidden"]'), input => input.value),
        });
        const saved = memoryState.categories.find(category => category.name.toLocaleLowerCase() === name.trim().toLocaleLowerCase());
        populateCategories(saved?.id);
        editingCategory = saved || null;
        if (memoryRefs.rangeFields.hidden) memoryDialog.close();
        else memoryRefs.categoryEditor.hidden = true;
      } catch (error) { showMemoryError(error.message); }
    });
    memoryRefs.categoryDelete.addEventListener('click', async () => {
      if (!editingCategory) return;
      const restore = Boolean(editingCategory.archived_at);
      if (!restore && !window.confirm(`Archive ${editingCategory.name}? Pins and agent history will be retained and hidden from the heatmap.`)) return;
      try {
        await postMemory({action:restore ? 'restore_category' : 'archive_category', category_id:editingCategory.id});
        memoryDialog.close();
      } catch (error) { showMemoryError(error.message); }
    });
    let historyVersion = 0;
    const loadAgentHistory = async (older = false) => {
      const categoryId = editingCategory?.id;
      if (!categoryId) return;
      const ticket = ++historyVersion;
      const list = historyDialog.querySelector('[data-category-events]');
      const more = historyDialog.querySelector('[data-history-more]');
      const before = older ? Number(more.dataset.before || 0) : 0;
      if (!older) list.textContent = 'Loading history…';
      more.disabled = true;
      try {
        const response = await fetch('/hfl-corpus/memory-pins', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({csrf:memoryCsrf, action:'agent_history', category_id:categoryId, before_id:before})});
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || 'Could not load history.');
        if (ticket !== historyVersion || categoryId !== editingCategory?.id) return;
        if (!older) list.replaceChildren();
        if (!result.events.length && !older) list.textContent = 'No agent events yet. Recorded outputs will appear here.';
        result.events.forEach(event => {
          const card = document.createElement('article');
          card.className = 'rounded-lg border border-slate-700 p-3 text-xs';
          const summary = document.createElement('h4');
          summary.className = 'font-semibold text-slate-200 break-words';
          summary.textContent = `${event.period_title} · ${event.status} · ${new Date(event.created_at).toLocaleString()}`;
          card.append(summary);
          const meta = document.createElement('p');
          meta.className = 'my-2 text-slate-400';
          meta.textContent = `${event.start_date} – ${event.end_date} · ${event.agent}${event.model ? ' · ' + event.model : ''}`;
          card.append(meta);
          const output = document.createElement('div');
          output.className = 'memory-prompt-preview markdown-body';
          output.innerHTML = event.output_html; // Server-rendered, sanitized Markdown only.
          card.append(output);
          const prompts = document.createElement('details');
          const label = document.createElement('summary');
          label.className = 'mt-3 cursor-pointer text-cyan-200';
          label.textContent = 'Prompt snapshots';
          prompts.append(label);
          const text = document.createElement('pre');
          text.style.cssText = 'white-space:pre-wrap;overflow-wrap:anywhere;max-height:16rem;overflow:auto';
          text.textContent = `System prompt / category guidance\n${event.system_prompt || '(empty)'}\n\nPin instructions\n${event.instructions || '(empty)'}`;
          prompts.append(text);card.append(prompts);list.append(card);
        });
        more.hidden = result.events.length < 20;
        more.dataset.before = result.events.at(-1)?.id || '';
      } catch (error) {
        if (ticket === historyVersion && categoryId === editingCategory?.id) {
          if (!older) list.textContent = error.message;
          else showMemoryError(error.message);
        }
      } finally { if (ticket === historyVersion) more.disabled = false; }
    };
    memoryDialog.querySelector('[data-category-history]').addEventListener('click', () => {
      historyDialog.querySelector('[data-history-category]').textContent = editingCategory?.name || '';
      historyDialog.querySelector('[data-history-more]').hidden = true;
      historyDialog.showModal();
      void loadAgentHistory();
    });
    historyDialog.querySelector('[data-history-close]').addEventListener('click', () => historyDialog.close());
    historyDialog.addEventListener('close', () => { ++historyVersion; });
    historyDialog.querySelector('[data-history-more]').addEventListener('click', () => void loadAgentHistory(true));
    memoryForm.addEventListener('submit', async event => {
      event.preventDefault();
      if (memoryRefs.rangeSave.disabled) return;
      memoryRefs.rangeSave.disabled = true;
      showMemoryError('');
      try {
        const attachments = memoryDialog.inputAttachments;
        attachments.validate();
        attachments.root.inert = true;
        const changed = attachments.changed;
        const payload = {
          action:'save_range',
          range_id:editingRange?.id || null,
          category_id:Number(memoryRefs.categorySelect.value),
          start_date:memoryRefs.start.value,
          end_date:memoryRefs.end.value,
          note:memoryRefs.note.value,
          title:memoryRefs.pinTitle.value,
          prompt:promptEditors.range.input.value,
          execution_hour:Number(document.getElementById('pin-execution-hour').value) % 12 + (document.getElementById('pin-execution-period').value === 'PM' ? 12 : 0),
          agent_enabled:document.getElementById('pin-agent-enabled').checked,
        };
        const result = await postMemory({...payload, ...(changed ? {prompt:''} : {})});
        editingRange = result.ranges.find(range => range.id === result.saved_range_id);
        if (changed) {
          await attachments.save(editingRange.id);
          await postMemory({...payload, range_id:editingRange.id});
        }
        memoryDialog.close();
      } catch (error) { showMemoryError(error.message); }
      finally { memoryDialog.inputAttachments.root.inert = false; memoryRefs.rangeSave.disabled = !memoryState.categories.length; }
    });
    memoryRefs.rangeDelete.addEventListener('click', async () => {
      if (!editingRange) return;
      try {
        await postMemory({action:'delete_range', range_id:editingRange.id});
        memoryDialog.close();
      } catch (error) { showMemoryError(error.message); }
    });
    [memoryRefs.start, memoryRefs.end].forEach(input => input.addEventListener('change', () => {
      if (memoryRefs.start.value && memoryRefs.end.value) {
        memoryRefs.summary.textContent = formatRange({start_date:memoryRefs.start.value, end_date:memoryRefs.end.value});
      }
    }));
    memoryDialog.addEventListener('close', () => { editingRange = null; editingCategory = null; showMemoryError(''); });
    renderMemoryState();
    matchingEntries.addEventListener('click', async () => {
      if (matchingEntries.disabled || !menuTrigger) return;
      const expanding = matchingPanel.hidden;
      selectDaySection(expanding ? 'matches' : null);
      positionDayMenu(menuTrigger);
      if (!expanding || matchingContent.dataset.loaded === 'true') return;
      matchingContent.textContent = 'Loading matching entries…';
      const requestController = new AbortController();
      matchingAbortController = requestController;
      try {
        const response = await fetch(menuTrigger.dataset.matchesUrl, {
          headers: {'X-Requested-With': 'activity-day-matches'},
          signal: requestController.signal,
        });
        if (!response.ok) throw new Error(`Matching entries request failed: ${response.status}`);
        matchingContent.innerHTML = await response.text();
        matchingContent.dataset.loaded = 'true';
        window.htmx?.process(matchingContent);
        positionDayMenu(menuTrigger);
      } catch (error) {
        if (error.name === 'AbortError') return;
        matchingContent.textContent = 'Matching entries could not be loaded. Try again.';
        matchingContent.dataset.loaded = 'false';
        positionDayMenu(menuTrigger);
      } finally {
        if (matchingAbortController === requestController) matchingAbortController = null;
      }
    });
    document.addEventListener('pointerdown', event => {
      if (document.querySelector('#followup-editor[open], #followup-history[open], .action-connections-dialog[open]')) return;
      if (menu.hidden || menu.contains(event.target) || event.target === menuTrigger) return;
      closeDayMenu();
    }, {signal: activityController.signal});
    document.addEventListener('keydown', event => {
      if (event.key !== 'Escape') return;
      if (document.querySelector('#followup-editor[open], #followup-history[open], .action-connections-dialog[open]')) return;
      if (pinStart) {
        pinStart = '';
        clearPreview();
        if (selectionStatus) selectionStatus.hidden = true;
        return;
      }
      if (menu.hidden) return;
      event.preventDefault();
      closeDayMenu(true);
    }, {signal: activityController.signal});

    const updateYearCoachmarks = value => {
      const previousValue = String(Number(value) - 1);
      const hasPrevious = Boolean(panel.querySelector(`[data-activity-year-segment="${previousValue}"]`));
      previousYearCoachmark.textContent = hasPrevious ? previousValue : '';
      previousYearCoachmark.hidden = !hasPrevious;
      const nextValue = String(Number(value) + 1);
      const hasNext = Boolean(panel.querySelector(`[data-activity-year-segment="${nextValue}"]`));
      nextYearCoachmark.textContent = hasNext ? nextValue : '';
      nextYearCoachmark.hidden = !hasNext;
    };
    const setYearMenuOpen = open => {
      if (!yearControls || !yearTrigger || !yearList) return;
      yearControls.dataset.yearMenuOpen = String(open);
      yearTrigger.setAttribute('aria-expanded', String(open));
      if (!open) return;
      window.requestAnimationFrame(() => {
        yearList.querySelector('[aria-selected="true"]')?.scrollIntoView({block:'nearest'});
      });
    };
    const syncYearPicker = value => {
      if (yearTriggerValue) yearTriggerValue.textContent = value;
    };
    const centerDateForYear = value => {
      if (value === timelineData.end.slice(0, 4)) return timelineData.end;
      const midpoint = `${value}-07-01`;
      if (midpoint < timelineData.start) return timelineData.start;
      if (midpoint > timelineData.calendar_end) return timelineData.calendar_end;
      return midpoint;
    };
    const scrollToYear = async value => {
      const segment = panel.querySelector(`[data-activity-year-segment="${value}"]`);
      if (!segment) return;
      await scrollToDate(centerDateForYear(value), {focus:false});
    };
    year.addEventListener('change', () => scrollToYear(year.value));
    yearTrigger?.addEventListener('click', event => {
      event.stopPropagation();
      setYearMenuOpen(yearTrigger.getAttribute('aria-expanded') !== 'true');
    }, {signal: activityController.signal});
    yearTrigger?.addEventListener('keydown', event => {
      if (event.key === 'Escape') setYearMenuOpen(false);
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setYearMenuOpen(true);
        yearList?.querySelector('[aria-selected="true"]')?.focus();
      }
    }, {signal: activityController.signal});
    yearOptions.forEach(option => option.addEventListener('click', () => {
      setYearMenuOpen(false);
      scrollToYear(option.dataset.activityYearOption);
    }));
    document.addEventListener('click', event => {
      if (!yearControls?.contains(event.target)) setYearMenuOpen(false);
    }, {signal: activityController.signal});
    const centerSelectedYear = () => {
      if (body.hidden || !yearList || !window.matchMedia('(min-width: 640px)').matches) return;
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => {
          const selectedYear = yearList.querySelector('[aria-selected="true"]');
          if (!selectedYear) return;
          const listRect = yearList.getBoundingClientRect();
          const selectedRect = selectedYear.getBoundingClientRect();
          yearList.scrollTop = Math.max(
            0,
            yearList.scrollTop + selectedRect.top - listRect.top
              - (yearList.clientHeight - selectedRect.height) / 2,
          );
        });
      });
    };
    const centerSelectedDay = async () => {
      if (body.hidden) return;
      await scrollToDate(timelineData.end, {behavior:'auto', focus:false});
    };
    const yearAtViewportCenter = () => {
      const center = (scroll.getBoundingClientRect().left + scroll.getBoundingClientRect().right) / 2;
      return Array.from(panel.querySelectorAll('[data-activity-year-segment]')).reduce((best, segment) => {
        const rect = segment.getBoundingClientRect();
        const distance = center < rect.left ? rect.left - center : center > rect.right ? center - rect.right : 0;
        return !best || distance < best.distance ? {segment, distance} : best;
      }, null)?.segment;
    };
    let yearScrollFrame = 0;
    scroll.addEventListener('scroll', () => {
      if (yearScrollFrame) return;
      yearScrollFrame = window.requestAnimationFrame(() => {
        yearScrollFrame = 0;
        const value = yearAtViewportCenter()?.dataset.activityYearSegment;
        if (!value) return;
        updateYearCoachmarks(value);
        if (year.value === value) return;
        year.value = value;
        yearOptions.forEach(option => option.setAttribute('aria-selected', String(option.dataset.activityYearOption === value)));
        syncYearPicker(value);
        syncYearState(value);
        centerSelectedYear();
      });
    }, {signal: activityController.signal, passive:true});
    updateYearCoachmarks(year.value);
    centerSelectedYear();
    centerSelectedDay();
    window.addEventListener('pageshow', () => {
      centerSelectedYear();
      void centerSelectedDay();
    }, {signal: activityController.signal});
    toggle?.addEventListener('click', () => {
      const expanded = toggle.getAttribute('aria-expanded') === 'true';
      closeDayMenu();
      const nextExpanded = !expanded;
      setActivityExpanded(nextExpanded);
      writeActivityState(nextExpanded);
      if (nextExpanded) {
        centerSelectedYear();
        centerSelectedDay();
      }
    });
  };

  window.HflActivityHeatmap = {init: initActivityPanel};
  initActivityPanel(document.querySelector('[data-activity-panel]'));
})();
