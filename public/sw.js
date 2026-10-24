// Only the shell. Never cache torrent, HLS, API responses or temporary tickets.
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
