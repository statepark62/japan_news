/* 日々の便り 서비스워커
   - 앱 껍데기(HTML/아이콘/manifest)는 캐시 우선 → 오프라인에서도 열림
   - news.json / vocab.json 은 네트워크 우선 → 항상 최신, 실패 시 캐시 사용
*/
const CACHE = "hibinotayori-v1";
const SHELL = [
  "./index.html",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./icons/apple-touch-icon.png"
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  const isData = url.pathname.endsWith("news.json") || url.pathname.endsWith("vocab.json");

  if (isData) {
    // 네트워크 우선, 실패하면 캐시
    e.respondWith(
      fetch(e.request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      }).catch(() => caches.match(e.request))
    );
    return;
  }

  // 그 외(앱 껍데기): 캐시 우선, 없으면 네트워크
  e.respondWith(
    caches.match(e.request).then((hit) => hit || fetch(e.request).then((res) => {
      if (e.request.method === "GET" && res.ok && url.origin === location.origin) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
      }
      return res;
    }).catch(() => caches.match("./index.html")))
  );
});
