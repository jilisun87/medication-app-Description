/* ============================================================
 * Service Worker
 * 患者用药管理 PWA - 离线缓存
 *
 * 策略：
 *  - 应用外壳（HTML/CSS/JS/manifest）: Cache First
 *  - 导航请求（页面跳转）: Network First，回退到缓存
 *  - 其他 GET 请求: Network First，回退到缓存
 * ============================================================ */

const CACHE_VERSION = 'pma-v1.0.0';                  // 缓存版本（更新时改版本号即可失效旧缓存）
const STATIC_ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png'
];

// 安装阶段：预缓存应用外壳
self.addEventListener('install', event => {
  console.log('[SW] 安装中，版本:', CACHE_VERSION);
  event.waitUntil(
    caches.open(CACHE_VERSION)
      .then(cache => cache.addAll(STATIC_ASSETS))
      .then(() => self.skipWaiting())   // 立即激活新版
  );
});

// 激活阶段：清理旧版本缓存
self.addEventListener('activate', event => {
  console.log('[SW] 激活中');
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(key => key !== CACHE_VERSION)
            .map(key => caches.delete(key))
      )
    ).then(() => self.clients.claim())  // 立即接管所有页面
  );
});

// 拦截请求
self.addEventListener('fetch', event => {
  const req = event.request;

  // 只处理 GET 请求
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // 同源资源走缓存策略
  if (url.origin === self.location.origin) {
    // 导航请求（HTML 页面）: Network First
    if (req.mode === 'navigate') {
      event.respondWith(networkFirst(req));
      return;
    }
    // 静态资源: Cache First
    event.respondWith(cacheFirst(req));
  }
});

/* ----------------------------------------------------------
 * 缓存策略实现
 * ---------------------------------------------------------- */

/** Cache First: 命中缓存直接返回，否则网络请求并缓存 */
async function cacheFirst(req) {
  const cache = await caches.open(CACHE_VERSION);
  const cached = await cache.match(req);
  if (cached) return cached;

  try {
    const resp = await fetch(req);
    if (resp && resp.status === 200) {
      cache.put(req, resp.clone());
    }
    return resp;
  } catch (e) {
    // 离线 + 没缓存：返回兜底
    return new Response('离线模式 + 资源未缓存', {
      status: 503,
      statusText: 'Service Unavailable',
      headers: { 'Content-Type': 'text/plain; charset=utf-8' }
    });
  }
}

/** Network First: 先尝试网络，失败回退到缓存 */
async function networkFirst(req) {
  const cache = await caches.open(CACHE_VERSION);
  try {
    const resp = await fetch(req);
    if (resp && resp.status === 200) {
      cache.put(req, resp.clone());
    }
    return resp;
  } catch (e) {
    const cached = await cache.match(req) || await cache.match('./index.html');
    if (cached) return cached;
    return new Response('离线模式 + 页面未缓存', {
      status: 503,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' }
    });
  }
}

/* ----------------------------------------------------------
 * 消息处理：支持页面通知 skipWaiting
 * ---------------------------------------------------------- */
self.addEventListener('message', event => {
  if (event.data === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});