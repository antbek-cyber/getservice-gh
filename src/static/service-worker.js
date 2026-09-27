self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => self.clients.claim());

self.addEventListener('push', function(event) {
  let data = {title:'GetService-GH', body:'New job request! Open app'};
  if (event.data) {
    try { data = event.data.json(); } catch(e) { data = {title:'GetService-GH', body: event.data.text()}; }
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      badge: '/static/favicon.ico',
      vibrate: [200,100,200,100,200],
      requireInteraction: true,
      data: { url: '/worker_dashboard' }
    })
  );
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data.url || '/worker_dashboard'));
});
