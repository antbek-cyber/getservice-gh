function urlBase64ToUint8Array(base64String){
  const padding='='.repeat((4-base64String.length%4)%4);
  const base64=(base64String+padding).replace(/-/g,'+').replace(/_/g,'/');
  const rawData=window.atob(base64);
  const outputArray=new Uint8Array(rawData.length);
  for(let i=0;i<rawData.length;++i){ outputArray[i]=rawData.charCodeAt(i); }
  return outputArray;
}

const VAPID_PUBLIC="BJyzhyh7uhy6YRmyX4ygYcSrDtKIpsxxhYUAxXMph8OxoRBmI8bXWboZiMEmbx2l558qU6L3l6k7QpfAHfiwDvM"; // PASTE YOUR REAL KEY HERE

async function doSubscribe(){
  try{
    const reg = await navigator.serviceWorker.register('/static/sw.js');
    await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly:true,
      applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC)
    });
    const r = await fetch('/api/save-subscription',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(sub)
    });
    alert("✅ Push SAVED! Status:"+r.status+" You will now get buzz when locked!");
  }catch(e){ alert("❌ Push FAILED:"+e.message); console.error(e); }
}
