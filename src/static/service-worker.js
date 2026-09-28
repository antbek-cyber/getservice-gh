self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => self.clients.claim());

self.addEventListener('push', function(event) {
  console.log('PUSH RECEIVED');
  let data = {title:'🔔 NEW BOOKING!', body:'Someone booked you - Open now!'};
  if (event.data) {
    try { data = event.data.json(); } catch(e) { data.body = event.data.text(); }
  }
  const options = {
    body: data.body,
    vibrate: [500, 200, 500],
    requireInteraction: true,
    tag: 'new-booking',
    renotify: true,
    data: { url: '/worker_dashboard' }
  };
  event.waitUntil(self.registration.showNotification(data.title, options));
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  event.waitUntil(clients.openWindow('/worker_dashboard'));
});
