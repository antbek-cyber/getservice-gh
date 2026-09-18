if (Notification && Notification.permission !== "granted") {
    Notification.requestPermission();
}
function checkPush() {
    fetch('/api/check-notifications')
    .then(r => r.json())
    .then(data => {
        if (data.has_new && Notification.permission === "granted") {
            new Notification("GetService GH", {
                body: data.message,
                icon: "/static/icon.png"
            });
        }
    });
}
setInterval(checkPush, 10000);
