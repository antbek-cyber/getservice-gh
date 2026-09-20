self.addEventListener('push', function(e) {
  const data = e.data.json();
  self.registration.showNotification("GetService-GH 🔔", {
    body: data.message,
    icon: "/static/logo.png",
    vibrate: [300,100,300],
    badge: "/static/logo.png"
  });
});
self.addEventListener('notificationclick', function(e){
  e.notification.close();
  e.waitUntil(clients.openWindow('/'));
});
