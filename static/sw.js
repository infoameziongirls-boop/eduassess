/* EduAssess service worker - lets key pages open with no network. */
const VERSION = 'eduassess-v4';
const SHELL = VERSION + '-shell';
const PAGE_CACHE_PREFIX = VERSION + '-pages-';
const META = VERSION + '-meta';
const ACTIVE_USER_KEY = new Request(location.origin + '/__eduassess_active_user');
const SHELL_ASSETS = [
  '/static/css/bootstrap.min.css', '/static/css/bootstrap-icons.css',
  '/static/js/bootstrap.bundle.min.js', '/static/js/offline.js',
  '/static/js/pwa.js', '/static/manifest.webmanifest', '/static/pwa-icon.svg',
  '/static/pwa-192.png', '/static/pwa-512.png'
];
const PAGE_RE = /^\/($|dashboard$|assessments\/new$|student\/quizzes$|student\/quizzes\/\d+\/take$|student\/dashboard$|api\/roster-tree$)/;
const NETWORK_TIMEOUT = 6000;

self.addEventListener('install', e => {
  e.waitUntil(caches.open(SHELL).then(cache => cache.addAll(SHELL_ASSETS)));
  self.skipWaiting();
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(k => k.startsWith('eduassess-') && !k.startsWith(VERSION))
      .map(k => caches.delete(k))
  )).then(() => self.clients.claim()));
});

async function setActiveUser(user) {
  const cache = await caches.open(META);
  if (user && /^\d+$/.test(String(user))) {
    await cache.put(ACTIVE_USER_KEY, new Response(String(user)));
  } else {
    await cache.delete(ACTIVE_USER_KEY);
  }
}

async function getActiveUser() {
  const cache = await caches.open(META);
  const response = await cache.match(ACTIVE_USER_KEY);
  return response ? response.text() : null;
}

self.addEventListener('message', e => {
  const data = e.data;
  if (data && data.type === 'SET_USER') {
    e.waitUntil(setActiveUser(data.user));
    return;
  }
  if (data === 'CLEAR_PAGES' || (data && data.type === 'CLEAR_PAGES')) {
    e.waitUntil((async () => {
      const user = (data && data.user) || await getActiveUser();
      if (user && /^\d+$/.test(String(user))) {
        await caches.delete(PAGE_CACHE_PREFIX + user);
      }
      if (!data || !data.user || String(data.user) === String(await getActiveUser())) {
        await setActiveUser(null);
      }
      if (e.ports && e.ports[0]) e.ports[0].postMessage({ok: true});
    })());
  }
});

function offlinePage() {
  return new Response(
    '<!doctype html><meta name=viewport content="width=device-width,initial-scale=1"><body style="font-family:system-ui;padding:40px;text-align:center">' +
    '<h2>You are offline</h2><p>This page was not saved on this device yet. Open it once while online and it will be available offline.</p>' +
    '<p><a href="/">Back to dashboard</a></p></body>', {headers: {'Content-Type': 'text/html'}});
}

function networkFirst(req, url) {
  const key = new Request(url.href);
  return new Promise(resolve => {
    let settled = false;
    const fallback = async () => {
      const user = await getActiveUser();
      if (user && /^\d+$/.test(user)) {
        const cache = await caches.open(PAGE_CACHE_PREFIX + user);
        const hit = await cache.match(key);
        if (hit) return hit;
      }
      if (req.mode === 'navigate') return offlinePage();
      return Response.error();
    };
    const timer = setTimeout(() => {
      if (!settled) {
        settled = true;
        fallback().then(resolve);
      }
    }, NETWORK_TIMEOUT);
    fetch(req).then(async res => {
      clearTimeout(timer);
      const loginRedirect = res.redirected && /\/(student\/)?login/.test(res.url);
      const user = res.headers.get('X-EduAssess-User');
      const cacheControl = res.headers.get('Cache-Control') || '';
      if (res.ok && !loginRedirect && !/\bno-store\b/i.test(cacheControl) &&
          user && /^\d+$/.test(user)) {
        try {
          const cache = await caches.open(PAGE_CACHE_PREFIX + user);
          await cache.put(key, res.clone());
          await setActiveUser(user);
        } catch (error) {
          console.error('Unable to cache this EduAssess page:', error);
        }
      }
      if (!settled) {
        settled = true;
        resolve(res);
      }
    }).catch(() => {
      clearTimeout(timer);
      if (!settled) {
        settled = true;
        fallback().then(resolve);
      }
    });
  });
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;

  if (url.pathname.startsWith('/static/')) {
    e.respondWith(caches.open(SHELL).then(c => c.match(req).then(hit => {
      const net = fetch(req).then(res => {
        if (res.ok) c.put(req, res.clone());
        return res;
      }).catch(() => hit);
      return hit || net;
    })));
    return;
  }
  if (PAGE_RE.test(url.pathname)) e.respondWith(networkFirst(req, url));
});
