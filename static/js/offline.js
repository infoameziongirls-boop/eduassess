/* EduAssess offline outbox: saves score entries / quiz answers on the device
   when the network is down and sends them automatically when it returns. */
(function () {
  'use strict';
  const USER = (document.currentScript && document.currentScript.dataset.user) || '';
  const DB_NAME = 'eduassess-offline', STORE = 'queue';
  const ENDPOINT = {assessment: '/api/offline/assessment', quiz: '/api/offline/quiz'};
  const PAGE_START = Date.now();
  let syncing = false;
  let syncMessage = 'Ready';
  let draftStorageWarned = false;

  /* ---------- IndexedDB ---------- */
  const openDb = () => new Promise((ok, bad) => {
    const r = indexedDB.open(DB_NAME, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(STORE, {keyPath: 'id'});
    r.onsuccess = () => {
      r.result.onversionchange = () => r.result.close();
      ok(r.result);
    };
    r.onerror = () => bad(r.error);
  });
  async function run(mode, fn) {
    const db = await openDb();
    return new Promise((ok, bad) => {
      let req;
      try {
        const t = db.transaction(STORE, mode);
        req = fn(t.objectStore(STORE));
        t.oncomplete = () => { db.close(); ok(req && req.result); };
        t.onerror = () => { db.close(); bad(t.error); };
        t.onabort = () => { db.close(); bad(t.error || new Error('Offline storage transaction aborted')); };
      } catch (error) {
        db.close();
        bad(error);
      }
    });
  }
  const qPut = item => run('readwrite', s => s.put(item));
  const qDel = id => run('readwrite', s => s.delete(id));
  const qAll = async () => ((await run('readonly', s => s.getAll())) || [])
    .filter(i => i.user === USER && !i.draft);

  function draftKey(form) {
    const formKey = form.dataset.offline === 'quiz'
      ? 'quiz-' + form.dataset.quizId : 'assessment';
    return `eduassess-draft-${USER}-${formKey}`;
  }
  function submissionId(form) {
    if (!form.dataset.submissionId) {
      form.dataset.submissionId = (window.crypto && crypto.randomUUID)
        ? crypto.randomUUID()
        : Date.now() + '-' + Math.random().toString(36).slice(2) + '-' + Math.random().toString(36).slice(2);
    }
    return form.dataset.submissionId;
  }
  function saveFormDraft(form) {
    if (form.dataset.draftCleared) return true;
    const values = {};
    for (const [name, value] of new FormData(form).entries()) {
      if (name === 'csrf_token') continue;
      (values[name] || (values[name] = [])).push(value);
    }
    const draft = {submission_id: submissionId(form), values, saved_at: Date.now()};
    try {
      localStorage.setItem(draftKey(form), JSON.stringify(draft));
      if (!form.dataset.draftNotice) {
        form.dataset.draftNotice = '1';
        toast('Draft saved on this device. Review it before submitting.');
      }
      return true;
    } catch (error) {
      if (!draftStorageWarned) {
        draftStorageWarned = true;
        console.error('Unable to persist the offline form draft:', error);
        toast('This browser could not save a draft. Keep this page open until you submit.');
      }
      return false;
    }
  }
  function restoreFormDraft(form) {
    let draft;
    try {
      const raw = localStorage.getItem(draftKey(form));
      if (!raw) return;
      draft = JSON.parse(raw);
    } catch (error) {
      console.error('Unable to read the offline form draft:', error);
      toast('A saved draft could not be read from this browser.');
      return;
    }
    if (!draft || !draft.values || typeof draft.values !== 'object') return;
    if (typeof draft.submission_id === 'string') form.dataset.submissionId = draft.submission_id;
    for (const element of Array.from(form.elements)) {
      if (!element.name || element.name === 'csrf_token') continue;
      const values = draft.values[element.name] || [];
      if (element.type === 'radio' || element.type === 'checkbox') {
        element.checked = values.includes(element.value);
      } else if (element.multiple) {
        Array.from(element.options).forEach(option => { option.selected = values.includes(option.value); });
      } else if (values.length) {
        element.value = values[0];
      }
      element.dispatchEvent(new Event('input', {bubbles: true}));
      element.dispatchEvent(new Event('change', {bubbles: true}));
    }
    form.dataset.draftNotice = '1';
    toast('Restored unsent form answers from this device.');
  }
  function clearFormDraft(form) {
    try {
      localStorage.removeItem(draftKey(form));
      form.dataset.draftCleared = '1';
      delete form.dataset.submissionId;
      delete form.dataset.draftNotice;
    } catch (error) {
      console.error('Unable to clear the offline form draft:', error);
      toast('The submitted draft remains stored on this device.');
    }
  }
  function clearSyncedDraft(item) {
    const formKey = item.type === 'quiz'
      ? 'quiz-' + item.payload.quiz_id : 'assessment';
    const key = `eduassess-draft-${USER}-${formKey}`;
    try {
      if (item.type === 'quiz') {
        localStorage.removeItem(key);
        return;
      }
      const draft = JSON.parse(localStorage.getItem(key) || 'null');
      if (draft && draft.submission_id === item.payload.submission_id) {
        localStorage.removeItem(key);
      }
    } catch (error) {
      console.error('Unable to remove a synchronized form draft:', error);
    }
  }

  /* ---------- UI: status pill + toast ---------- */
  const css = document.createElement('style');
  css.textContent = `
  #eo-pill{position:fixed;left:16px;bottom:16px;z-index:2000;font:600 .78rem system-ui;padding:8px 14px;border-radius:99px;color:#fff;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.25);display:none}
  #eo-pill.off{background:#b45309}#eo-pill.pend{background:#2563eb}#eo-pill.err{background:#c0392b}
  #eo-panel{position:fixed;left:16px;bottom:58px;z-index:2000;width:320px;max-height:60vh;overflow:auto;background:#fff;border:1px solid #e7ddc9;border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.2);padding:12px;display:none;font:.8rem system-ui;color:#0b1623}
  #eo-panel .it{border-bottom:1px solid #eee;padding:8px 0}#eo-panel .er{color:#c0392b}
  #eo-panel button{font:600 .72rem system-ui;border:0;border-radius:7px;padding:5px 10px;margin:4px 6px 0 0;cursor:pointer;background:#c9a84c}
  #eo-toast{position:fixed;right:16px;bottom:16px;z-index:2100;max-width:340px;background:#0b1623;color:#fff;font:.82rem system-ui;padding:11px 16px;border-radius:12px;opacity:0;transform:translateY(8px);transition:.25s;pointer-events:none}
  #eo-toast.show{opacity:1;transform:none}`;
  document.head.appendChild(css);
  const pill = document.createElement('div'); pill.id = 'eo-pill';
  const panel = document.createElement('div'); panel.id = 'eo-panel';
  const toastEl = document.createElement('div'); toastEl.id = 'eo-toast';
  document.addEventListener('DOMContentLoaded', () => document.body.append(pill, panel, toastEl));
  let toastTimer;
  function toast(msg) {
    toastEl.textContent = msg; toastEl.classList.add('show');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => toastEl.classList.remove('show'), 4500);
  }
  async function cachedQuizCount() {
    if (!('caches' in window)) return null;
    const names = (await caches.keys()).filter(name =>
      name.startsWith('eduassess-') && name.includes('-pages-') &&
      name.endsWith('-pages-' + USER));
    const paths = new Set();
    for (const name of names) {
      const cache = await caches.open(name);
      for (const request of await cache.keys()) {
        const path = new URL(request.url).pathname;
        if (/^\/student\/quizzes\/\d+\/take$/.test(path)) paths.add(path);
      }
    }
    return paths.size;
  }
  async function isQuizPageCached(url) {
    if (!('caches' in window)) return false;
    const names = (await caches.keys()).filter(name =>
      name.startsWith('eduassess-') && name.includes('-pages-') &&
      name.endsWith('-pages-' + USER));
    for (const name of names) {
      const cache = await caches.open(name);
      if (await cache.match(url)) return true;
    }
    return false;
  }
  async function refreshDashboard(items) {
    const dashboard = document.getElementById('offlineManager');
    if (!dashboard) return;
    const connection = document.getElementById('offlineConnectionStatus');
    const pending = document.getElementById('offlinePendingCount');
    const lastSync = document.getElementById('offlineLastSync');
    const quizCount = document.getElementById('offlineQuizCount');
    const progress = document.getElementById('offlineSyncProgress');
    const syncButton = document.getElementById('offlineSyncNow');
    const clearButton = document.getElementById('offlineClearQueue');

    connection.textContent = navigator.onLine ? 'Online' : 'Offline';
    connection.className = 'badge rounded-pill ' + (navigator.onLine ? 'bg-success' : 'bg-warning text-dark');
    pending.textContent = Array.isArray(items) ? `${items.length} pending` : 'Unavailable';
    progress.textContent = syncMessage;
    syncButton.disabled = syncing || !navigator.onLine || !items || items.length === 0;
    clearButton.disabled = !items || items.length === 0;

    try {
      const count = await cachedQuizCount();
      quizCount.textContent = count === null ? 'Not supported in this browser' :
        `${count} saved on this device`;
    } catch (error) {
      console.error('Unable to count saved offline quizzes:', error);
      quizCount.textContent = 'Unable to check saved quizzes';
    }

    try {
      const timestamp = Number(localStorage.getItem(`eduassess-last-sync-${USER}`));
      lastSync.textContent = timestamp ? new Date(timestamp).toLocaleString() : 'No sync recorded';
    } catch (error) {
      console.error('Unable to read the last sync time:', error);
      lastSync.textContent = 'Unavailable';
    }
  }
  async function refreshPill() {
    let items;
    try { items = await qAll(); }
    catch (error) {
      console.error('Unable to read the offline queue:', error);
      pill.className = 'err'; pill.textContent = '⚠ Offline storage unavailable';
      pill.style.display = 'block';
      syncMessage = 'Offline storage unavailable';
      refreshDashboard(null);
      return;
    }
    const failed = items.filter(i => i.error).length;
    if (failed) { pill.className = 'err'; pill.textContent = `⚠ ${failed} entr${failed > 1 ? 'ies need' : 'y needs'} attention`; }
    else if (items.length) { pill.className = navigator.onLine ? 'pend' : 'off'; pill.textContent = `⟳ ${items.length} waiting to sync`; }
    else if (!navigator.onLine) { pill.className = 'off'; pill.textContent = 'Offline - entries are saved on this device'; }
    else {
      pill.style.display = 'none'; panel.style.display = 'none';
      refreshDashboard(items);
      return;
    }
    pill.style.display = 'block';
    refreshDashboard(items);
  }
  pill.addEventListener('click', async () => {
    if (panel.style.display === 'block') { panel.style.display = 'none'; return; }
    const items = await qAll(); panel.replaceChildren();
    if (!items.length) panel.textContent = 'Nothing waiting.';
    items.forEach(i => {
      const d = document.createElement('div'); d.className = 'it';
      d.append(document.createTextNode(i.label));
      if (i.error) { const e = document.createElement('div'); e.className = 'er'; e.textContent = i.error; d.append(e); }
      const b = document.createElement('button'); b.textContent = 'Discard';
      b.onclick = async () => { if (confirm('Discard this saved entry?')) { await qDel(i.id); refreshPill(); pill.click(); pill.click(); } };
      d.append(b); panel.append(d);
    });
    const s = document.createElement('button'); s.textContent = 'Sync now'; s.onclick = () => sync(true); panel.append(s);
    panel.style.display = 'block';
  });
  document.addEventListener('click', event => {
    if (event.target.closest('#offlineSyncNow')) sync(true);
    if (event.target.closest('#offlineClearQueue')) {
      qAll().then(async items => {
        if (!items.length || !confirm(`Permanently clear ${items.length} pending submission${items.length === 1 ? '' : 's'} from this device? This work cannot be recovered.`)) return;
        await Promise.all(items.map(item => qDel(item.id)));
        syncMessage = 'Pending submissions cleared from this device';
        toast('Pending submissions were removed from this device.');
        refreshPill();
      }).catch(error => {
        console.error('Unable to clear pending submissions:', error);
        toast('Pending submissions could not be cleared.');
      });
    }
  });

  /* ---------- network ---------- */
  async function post(type, payload) {
    const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 12000);
    try {
      const r = await fetch(ENDPOINT[type], {method: 'POST', credentials: 'same-origin', signal: ctl.signal,
        headers: {'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'},
        body: JSON.stringify(payload)});
      let data = {}; try { data = await r.json(); } catch (_) {}
      return {status: r.status, data};
    } catch (_) { return null; } finally { clearTimeout(t); }
  }

  async function sync(manual) {
    if (syncing || !navigator.onLine) return;
    syncing = true; let sent = 0;
    syncMessage = 'Synchronizing…';
    refreshPill();
    try {
      const queuedItems = await qAll();
      for (const [index, item] of queuedItems.entries()) {
        syncMessage = `Synchronizing ${index + 1} of ${queuedItems.length}…`;
        refreshPill();
        const r = await post(item.type, item.payload);
        if (!r) break;                                         // network still bad - stop, retry later
        if (r.status === 401) { if (manual) toast('Please sign in again to sync your saved entries.'); break; }
        if (r.status >= 500) break;
        if (r.status >= 200 && r.status < 300) {
          await qDel(item.id);
          clearSyncedDraft(item);
          sent++;
          try { localStorage.setItem(`eduassess-last-sync-${USER}`, String(Date.now())); }
          catch (error) { console.error('Unable to save the last sync time:', error); }
        }
        else { item.error = r.data.message || 'Rejected by server'; await qPut(item); }
      }
    } catch (error) {
      console.error('Offline synchronization could not complete:', error);
      toast('Sync paused. Your saved entries remain on this device.');
    } finally { syncing = false; syncMessage = 'Ready'; }
    if (sent) toast(`✓ ${sent} saved entr${sent > 1 ? 'ies' : 'y'} synced.`);
    refreshPill();
  }

  /* ---------- form interception (data-offline="assessment|quiz") ---------- */
  function build(form) {
    const type = form.dataset.offline;
    const fd = Object.fromEntries(new FormData(form)); delete fd.csrf_token;
    const submission_id = submissionId(form);
    if (type === 'quiz') {
      const answers = {};
      Object.keys(fd).forEach(k => { if (k.startsWith('answer_')) answers[k.slice(7)] = fd[k]; });
      return {id: 'quiz-' + form.dataset.quizId, type, user: USER, created: Date.now(),
        label: 'Quiz answers (' + document.title.replace(/ - .*/, '') + ')',
        payload: {submission_id, quiz_id: form.dataset.quizId, answers,
          time_taken: Math.round((Date.now() - PAGE_START) / 1000)}};
    }
    const sel = form.querySelector('select[name=student_name]');
    const who = sel ? sel.options[sel.selectedIndex].text : fd.student_name;
    const cat = form.querySelector('[name=category]');
    return {id: 'as-' + Date.now() + '-' + Math.random().toString(36).slice(2, 7), type, user: USER,
      created: Date.now(), label: `${who} - ${cat ? cat.options[cat.selectedIndex].text : fd.category}: ${fd.score}`,
      payload: {...fd, submission_id}};
  }

  async function handle(form) {
    if (form.dataset.sending) return;
    form.dataset.sending = '1';
    const item = build(form);
    const btn = form.querySelector('[type=submit]'); if (btn) btn.disabled = true;
    const r = navigator.onLine ? await post(item.type, item.payload) : null;
    delete form.dataset.sending;

    if (r && r.status >= 200 && r.status < 300) {
      clearFormDraft(form);
      if (item.type === 'quiz') { location.href = r.data.redirect || '/student/quizzes'; return; }
      toast('✓ ' + (r.data.message || 'Saved'));
      ['score', 'comments'].forEach(n => { const f = form.querySelector('[name=' + n + ']'); if (f) f.value = ''; });
      const percentage = form.querySelector('#percentage');
      if (percentage) percentage.textContent = '0.0%';
      if (btn) btn.disabled = false;
      const sc = form.querySelector('[name=score]'); if (sc) sc.focus();
      return;
    }
    if (r && r.status >= 400 && r.status < 500 && r.status !== 401) {   // real validation problem: tell the user, do not queue
      toast('✗ ' + (r.data.message || 'Entry rejected')); if (btn) btn.disabled = false; return;
    }
    try {
      await qPut(item);                                                 // offline / flaky / expired session: keep it safely
    } catch (error) {
      console.error('Unable to queue the offline submission:', error);
      toast('Could not save this submission in browser storage. Keep this page open and try again.');
      if (btn) btn.disabled = false;
      return;
    }
    clearFormDraft(form);
    refreshPill();
    if (item.type === 'quiz') {
      form.dataset.sending = '1';
      toast('Saved on this device. It will be submitted automatically when the network returns.');
      setTimeout(() => { location.href = '/student/quizzes'; }, 1800);
    } else {
      toast('Saved on this device - will sync when the network returns.');
      ['score', 'comments'].forEach(n => { const f = form.querySelector('[name=' + n + ']'); if (f) f.value = ''; });
      const percentage = form.querySelector('#percentage');
      if (percentage) percentage.textContent = '0.0%';
      if (btn) btn.disabled = false;
    }
  }

  document.addEventListener('submit', e => {          // bubbles after the page's own handlers (e.g. quiz confirm())
    const f = e.target;
    if (!(f instanceof HTMLFormElement) || !f.dataset.offline || e.defaultPrevented) return;
    e.preventDefault(); handle(f);
  });
  const nativeSubmit = HTMLFormElement.prototype.submit;   // quiz timer auto-submit calls form.submit() directly
  HTMLFormElement.prototype.submit = function () {
    if (this.dataset && this.dataset.offline) { handle(this); return; }
    nativeSubmit.call(this);
  };

  /* ---------- "Save for offline" buttons on the quiz list ---------- */
  function decorateQuizList() {
    if (location.pathname !== '/student/quizzes') return;
    document.querySelectorAll('a[href$="/take"]').forEach(a => {
      if (a.dataset.eo) return; a.dataset.eo = '1';
      const b = document.createElement('button'); b.type = 'button'; b.className = 'btn btn-outline btn-sm ms-2';
      b.textContent = 'Save for offline';
      isQuizPageCached(a.href).then(cached => {
        if (cached) { b.textContent = '✓ Available offline'; b.disabled = true; }
      }).catch(error => console.error('Unable to inspect quiz download status:', error));
      b.onclick = async () => {
        b.disabled = true; b.textContent = 'Saving…';
        try {
          const r = await fetch(a.href, {credentials: 'same-origin'});
          const cached = r.ok && await isQuizPageCached(a.href);
          b.textContent = cached ? '✓ Available offline' : 'Failed - not saved';
          b.disabled = cached;
          refreshPill();
        }
        catch (_) { b.textContent = 'Failed - try again'; b.disabled = false; }
      };
      a.after(b);
    });
  }

  async function messageServiceWorker(message) {
    if (!('serviceWorker' in navigator)) return false;
    const registration = await navigator.serviceWorker.getRegistration('/');
    const worker = navigator.serviceWorker.controller || (registration && registration.active);
    if (!worker) return false;
    return new Promise((resolve, reject) => {
      const channel = new MessageChannel();
      const timeout = setTimeout(() => {
        channel.port1.close();
        reject(new Error('Service worker did not confirm the cache operation'));
      }, 2000);
      channel.port1.onmessage = event => {
        clearTimeout(timeout);
        channel.port1.close();
        if (event.data && event.data.ok) resolve(true);
        else reject(new Error('Service worker cache operation failed'));
      };
      worker.postMessage(message, [channel.port2]);
    });
  }

  /* ---------- logout safety on shared computers ---------- */
  document.addEventListener('click', e => {
    const a = e.target instanceof Element
      ? e.target.closest('a[href$="/logout"], a[href$="/student/logout"]') : null;
    if (!a) return;
    e.preventDefault();
    (async () => {
      let n = 0;
      try { n = (await qAll()).length; }
      catch (error) { console.error('Unable to inspect queued entries before logout:', error); }
      if (n && !confirm(`${n} entr${n > 1 ? 'ies are' : 'y is'} not synced yet. They stay on this device and sync after you sign in again. Sign out now?`)) return;
      try {
        localStorage.removeItem('roster_tree_v1');
        await messageServiceWorker({type: 'CLEAR_PAGES', user: USER});
      } catch (error) {
        console.error('Unable to clear the offline page cache during logout:', error);
        toast('Offline pages could not be cleared. Close this browser before another student uses this device.');
      }
      location.assign(a.href);
    })();
  }, true);

  /* ---------- boot ---------- */
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js', {updateViaCache: 'none'})
      .then(() => navigator.serviceWorker.ready)
      .then(registration => {
        const worker = navigator.serviceWorker.controller || registration.active;
        if (worker) worker.postMessage({type: 'SET_USER', user: USER});
      })
      .catch(error => {
        console.error('Service worker registration failed:', error);
        toast('Offline pages could not be prepared. Keep this page open while connected.');
      });
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (navigator.serviceWorker.controller) {
        navigator.serviceWorker.controller.postMessage({type: 'SET_USER', user: USER});
      }
    });
  } else {
    console.warn('This browser does not support offline pages.');
  }
  window.addEventListener('online', () => { refreshPill(); sync(); });
  window.addEventListener('offline', refreshPill);
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('form[data-offline]').forEach(form => {
      restoreFormDraft(form);
      const saveAfterEdit = () => {
        delete form.dataset.draftCleared;
        saveFormDraft(form);
      };
      form.addEventListener('input', saveAfterEdit);
      form.addEventListener('change', saveAfterEdit);
      window.addEventListener('pagehide', () => saveFormDraft(form));
    });
    decorateQuizList();
    refreshPill();
    sync();
  });
  setInterval(sync, 30000);
})();
