self.addEventListener('push', function(e){
  const data = e.data.json();
  self.registration.showNotification("GetService-GH", {
    body: data.message,
    icon: "/static/logo.png",
    vibrate: [200,100,200],
    badge: "/static/logo.png"
  });
});
