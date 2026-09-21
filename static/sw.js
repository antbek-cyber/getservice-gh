self.addEventListener('push', function(event){
  const data = event.data? event.data.json() : {title:'GetService-GH', body:'New job request!'};
  event.waitUntil(
    self.registration.showNotification(data.title,{
      body: data.body,
      icon: '/static/icon-192.png',
      badge: '/static/icon-192.png'
    })
  );
});
self.addEventListener('notificationclick', function(event){
  event.notification.close();
  event.waitUntil(clients.openWindow('/worker_dashboard'));
});
