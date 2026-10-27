// Network-first pass-through: the installed app always loads the latest page from the web,
// so publishing an update needs no app reinstall. Nothing is cached, so nothing goes stale.
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', e => { /* default network fetch */ });
