self.addEventListener('push', function(e) {
  let data = {message: "New booking! Check dashboard"};
  try { if(e.data) data = e.data.json(); } catch(err){}
  
  e.waitUntil(
    self.registration.showNotification("GetService-GH 🔔", {
      body: data.message || "You have a new booking!",
      icon: "/static/logo.png",
      badge: "/static/logo.png",
      vibrate: [300,100,300],
      data: {url: "/worker-dashboard"}
    })
  );
});

self.addEventListener('notificationclick', function(e){
  e.notification.close();
  const url = e.notification.data?.url || '/worker-dashboard';
  e.waitUntil(clients.openWindow(url));
});
