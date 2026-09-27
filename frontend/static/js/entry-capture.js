(() => {
  const createDialog = document.querySelector('[data-create-entry-dialog]');
  const reviewDialog = document.querySelector('[data-entry-review-dialog]');
  const discardDialog = document.querySelector('[data-entry-discard-dialog]');
  const form = document.querySelector('[data-create-entry-form]');
  if (!createDialog || !reviewDialog || !discardDialog || !form) return;

  const errorBox = form.querySelector('[data-entry-error]');
  const reviewButton = form.querySelector('[data-entry-review]');
  const moreDetails = form.querySelector('[data-entry-more-details]');
  const fileInput = form.elements.attachments;
  const fileList = form.querySelector('[data-entry-file-list]');
  form.querySelector('[data-entry-choose-files]').addEventListener('click', () => fileInput.click());
  const confirmButton = reviewDialog.querySelector('[data-entry-confirm]');
  const previewPanel = reviewDialog.querySelector('[data-entry-preview]');
  const enrichmentPanel = reviewDialog.querySelector('[data-entry-enrichment-summary]');
  const enrichmentItems = enrichmentPanel.querySelector('[data-entry-enrichment-items]');
  const progressPanel = reviewDialog.querySelector('[data-entry-upload-progress]');
  const progressStatus = progressPanel.querySelector('[data-entry-upload-status]');
  const progressPercent = progressPanel.querySelector('[data-entry-upload-percent]');
  const progressBar = progressPanel.querySelector('[data-entry-upload-bar]');
  let initialState = '';
  let pendingPayload = null;
  let pendingFiles = [];
  let enrichmentCache = null;
  let returnActivityDate = '';
  let savingEntry = false;
  const backButton = reviewDialog.querySelector('[data-entry-review-back]');
  const setSavingEntry = value => {
    savingEntry = value;
    confirmButton.disabled = value;
    backButton.disabled = value;
    reviewButton.disabled = value;
    reviewDialog.setAttribute('aria-busy', String(value));
    confirmButton.textContent = value ? 'Saving…' : 'Confirm save';
  };

  const localDateAndTime = selectedDate => {
    const now = new Date();
    const offset = now.getTimezoneOffset() * 60000;
    const local = new Date(now.getTime() - offset).toISOString();
    form.elements.date.value = selectedDate || local.slice(0, 10);
    form.elements.time.value = selectedDate ? '' : local.slice(11, 16);
  };

  const selectedFiles = () => Array.from(fileInput.files || []);
  const receiveMedia = event => {
    if (savingEntry) return;
    const files = [...((event.clipboardData || event.dataTransfer)?.files || [])];
    if (!files.length) return;
    event.preventDefault();
    const transfer = new DataTransfer();
    [...selectedFiles(), ...files].forEach(file => transfer.items.add(file));
    fileInput.files = transfer.files;
    fileInput.dispatchEvent(new Event('change', {bubbles:true}));
  };
  form.addEventListener('paste', receiveMedia);
  form.addEventListener('drop', receiveMedia);
  form.addEventListener('dragover', event => { if ([...(event.dataTransfer?.types || [])].includes('Files')) event.preventDefault(); });

  const payload = () => {
    const values = Object.fromEntries(new FormData(form).entries());
    delete values.attachments;
    values.include_location = form.elements.include_location.checked;
    values.attachment_names = selectedFiles().map(file => file.name);
    return values;
  };
  const serialize = () => JSON.stringify(payload());
  const isDirty = () => serialize() !== initialState;
  const showError = (message) => {
    errorBox.textContent = message;
    errorBox.hidden = !message;
    if (message) errorBox.scrollIntoView({block: 'center'});
  };
  const responseMessage = (body, fallback) => {
    if (typeof body?.detail === 'string') return body.detail;
    if (Array.isArray(body?.detail)) return body.detail.map(item => item.msg).join(' ');
    return fallback;
  };
  const captureBrowserLocation = () => new Promise(resolve => {
    if (!form.elements.include_location.checked) {
      resolve({browser_location_status: 'disabled'});
      return;
    }
    if (!navigator.geolocation) {
      resolve({browser_location_status: 'unsupported'});
      return;
    }
    navigator.geolocation.getCurrentPosition(
      position => resolve({
        browser_latitude: position.coords.latitude,
        browser_longitude: position.coords.longitude,
        browser_location_status: 'available',
      }),
      error => resolve({
        browser_location_status: error.code === error.PERMISSION_DENIED ? 'denied' : 'unavailable',
      }),
      {enableHighAccuracy: false, timeout: 8000, maximumAge: 300000},
    );
  });
  const renderEnrichment = enrichment => {
    const items = [];
    if (enrichment?.location_label) {
      const source = enrichment.location_source === 'owntracks' ? 'activity timeline' : 'this device';
      items.push(`Location · ${enrichment.location_label} via ${source}`);
    }
    if (enrichment?.added_tags?.length) {
      items.push(`Tags · ${enrichment.added_tags.map(tag => `#${tag}`).join(' ')}`);
    }
    (enrichment?.notices || []).forEach(notice => items.push(notice));
    enrichmentItems.replaceChildren(...items.map(message => {
      const item = document.createElement('li');
      item.className = 'flex gap-2 leading-relaxed';
      const marker = document.createElement('span');
      marker.className = 'text-blue-400';
      marker.textContent = '•';
      const text = document.createElement('span');
      text.textContent = message;
      item.append(marker, text);
      return item;
    }));
    enrichmentPanel.hidden = items.length === 0;
  };
  const showReview = body => {
    pendingPayload = body.payload;
    reviewDialog.querySelector('[data-entry-preview-filename]').textContent = body.filename;
    previewPanel.innerHTML = body.html;
    renderEnrichment(body.enrichment);
    createDialog.close();
    reviewDialog.showModal();
  };
  const revealField = field => {
    if (!field || window.innerWidth >= 640) return;
    window.setTimeout(() => {
      field.scrollIntoView({behavior: 'smooth', block: 'center'});
    }, 120);
  };
  const openCreate = (selectedDate = '') => {
    if (savingEntry) return;
    form.querySelector('[data-entry-saved]').hidden = true;
    form.reset();
    moreDetails.open = false;
    localDateAndTime(selectedDate);
    showError('');
    pendingPayload = null;
    pendingFiles = [];
    enrichmentCache = null;
    returnActivityDate = selectedDate;
    fileList.replaceChildren();
    fileList.hidden = true;
    initialState = serialize();
    createDialog.showModal();
    form.elements.moment.focus();
  };
  const returnToForm = () => {
    if (savingEntry) return;
    if (reviewDialog.open) reviewDialog.close();
    if (discardDialog.open) discardDialog.close();
    createDialog.showModal();
  };
  const requestCancel = () => {
    if (savingEntry) return;
    if (!isDirty()) {
      createDialog.close();
      return;
    }
    createDialog.close();
    discardDialog.showModal();
  };

  document.querySelector('[data-create-entry-open]')?.addEventListener('click', () => openCreate());
  if(new URLSearchParams(location.search).get('create')==='entry'){openCreate();const url=new URL(location.href);url.searchParams.delete('create');history.replaceState(null,'',url);}
  document.addEventListener('hfl:create-entry-for-date', event => openCreate(event.detail?.date || ''));
  form.querySelectorAll('[data-entry-cancel]').forEach(button => button.addEventListener('click', requestCancel));

  createDialog.addEventListener('cancel', event => {
    event.preventDefault();
    requestCancel();
  });
  createDialog.addEventListener('click', event => {
    if (event.target === createDialog) requestCancel();
  });
  discardDialog.addEventListener('cancel', event => {
    event.preventDefault();
    returnToForm();
  });
  discardDialog.querySelector('[data-entry-keep]').addEventListener('click', returnToForm);
  discardDialog.querySelector('[data-entry-discard]').addEventListener('click', () => {
    discardDialog.close();
    form.reset();
    pendingPayload = null;
    pendingFiles = [];
    enrichmentCache = null;
    returnActivityDate = '';
  });

  const readableBytes = bytes => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };
  fileInput.addEventListener('change', () => {
    const files = selectedFiles();
    fileList.replaceChildren(...files.map(file => {
      const item = document.createElement('li');
      item.className = 'flex justify-between gap-3';
      const name = document.createElement('span');
      name.className = 'min-w-0 break-all text-slate-300';
      name.textContent = file.name;
      const size = document.createElement('span');
      size.className = 'shrink-0 font-mono';
      size.textContent = readableBytes(file.size);
      item.append(name, size);
      return item;
    }));
    fileList.hidden = files.length === 0;
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (savingEntry || reviewButton.disabled) return;
    form.querySelector('[data-entry-saved]').hidden = true;
    if (!form.checkValidity()) {
      const invalid = form.querySelector(':invalid');
      revealField(invalid);
      invalid?.focus({preventScroll: true});
      form.reportValidity();
      return;
    }
    showError('');
    reviewButton.disabled = true;
    const basePayload = payload();
    const cacheKey = JSON.stringify(basePayload);
    pendingFiles = selectedFiles();
    const originalLabel = reviewButton.textContent;
    reviewButton.textContent = 'Adding context…';
    try {
      let body = enrichmentCache?.key === cacheKey ? enrichmentCache.body : null;
      if (!body) {
        const browserLocation = await captureBrowserLocation();
        const response = await fetch('/hfl-corpus/entries/preview', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({...basePayload, ...browserLocation}),
        });
        body = await response.json();
        if (!response.ok) throw new Error(responseMessage(body, 'The preview could not be generated.'));
        enrichmentCache = {key: cacheKey, body};
      }
      showReview(body);
    } catch (error) {
      showError(error.message || 'The preview could not be generated.');
    } finally {
      reviewButton.disabled = false;
      reviewButton.textContent = originalLabel;
    }
  });

  form.addEventListener('focusin', event => {
    if (!event.target.matches('input, textarea, select')) return;
    revealField(event.target);
  });

  const backToEntry = () => returnToForm();
  reviewDialog.querySelector('[data-entry-review-back]').addEventListener('click', backToEntry);
  reviewDialog.addEventListener('cancel', event => {
    event.preventDefault();
    backToEntry();
  });
  reviewDialog.addEventListener('click', event => {
    if (event.target === reviewDialog) backToEntry();
  });

  confirmButton.addEventListener('click', async () => {
    if (!pendingPayload || savingEntry) return;
    setSavingEntry(true);
    previewPanel.hidden = true;
    progressPanel.hidden = false;
    progressStatus.textContent = 'Saving entry…';
    progressPercent.textContent = '';
    progressBar.style.width = '100%';
    try {
      let body;
      if (pendingFiles.length) {
        previewPanel.hidden = true;
        progressPanel.hidden = false;
        progressStatus.textContent = 'Uploading files…';
        progressPercent.textContent = '0%';
        progressBar.style.width = '0%';
        const upload = new FormData();
        upload.append('payload', JSON.stringify(pendingPayload));
        pendingFiles.forEach(file => upload.append('files', file, file.name));
        body = await new Promise((resolve, reject) => {
          const request = new XMLHttpRequest();
          request.open('POST', '/hfl-corpus/entries/upload');
          request.upload.addEventListener('progress', event => {
            if (!event.lengthComputable) return;
            const percent = Math.round((event.loaded / event.total) * 100);
            progressPercent.textContent = `${percent}%`;
            progressBar.style.width = `${percent}%`;
            if (percent === 100) progressStatus.textContent = 'Saving entry on the canonical host…';
          });
          request.addEventListener('load', () => {
            let result = {};
            try { result = JSON.parse(request.responseText || '{}'); } catch (_) {}
            if (request.status < 200 || request.status >= 300) {
              reject(new Error(responseMessage(result, 'The entry and files could not be saved.')));
              return;
            }
            resolve(result);
          });
          request.addEventListener('error', () => reject(new Error('The upload connection failed.')));
          request.addEventListener('abort', () => reject(new Error('The upload was interrupted.')));
          request.send(upload);
        });
      } else {
        const response = await fetch('/hfl-corpus/entries', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(pendingPayload),
        });
        body = await response.json();
        if (!response.ok) throw new Error(responseMessage(body, 'The entry could not be saved.'));
      }
      if (document.querySelector('[data-distill]')) {
        reviewDialog.close();
        progressPanel.hidden = true;
        previewPanel.hidden = false;
        setSavingEntry(false);
        openCreate();
        const saved = form.querySelector('[data-entry-saved]');
        saved.textContent = 'Entry saved. Ready for another moment.';
        saved.hidden = false;
        window.dispatchEvent(new Event('hfl:entry-saved'));
        return;
      }
      const successUrl = new URL('/hfl-corpus', window.location.origin);
      successUrl.searchParams.set('created', 'true');
      const savedActivityDate = returnActivityDate ? pendingPayload.date : '';
      if (savedActivityDate) {
        successUrl.searchParams.set('activity_year', savedActivityDate.slice(0, 4));
        successUrl.searchParams.set('date_field', 'entry');
        successUrl.searchParams.set('date_from', savedActivityDate);
        successUrl.searchParams.set('date_to', savedActivityDate);
      }
      pendingPayload = null;
      pendingFiles = [];
      progressStatus.textContent = 'Saved. Returning to Activity Corpus…';
      window.location.assign(successUrl);
    } catch (error) {
      setSavingEntry(false);
      reviewDialog.close();
      progressPanel.hidden = true;
      previewPanel.hidden = false;
      createDialog.showModal();
      showError(error.message || 'The entry could not be saved.');
    }
  });
})();
