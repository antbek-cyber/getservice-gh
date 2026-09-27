function urlBase64ToUint8Array(b64){
  const pad='='.repeat((4-b64.length%4)%4);
  const base64=(b64+pad).replace(/-/g,'+').replace(/_/g,'/');
  const raw=atob(base64);
  const out=new Uint8Array(raw.length);
  for(let i=0;i<raw.length;i++) out[i]=raw.charCodeAt(i);
  return out;
}
const VAPID_PUBLIC="function urlBase64ToUint8Array(b64){
  const pad='='.repeat((4-b64.length%4)%4);
  const base64=(b64+pad).replace(/-/g,'+').replace(/_/g,'/');
  const raw=atob(base64);
  const out=new Uint8Array(raw.length);
  for(let i=0;i<raw.length;i++) out[i]=raw.charCodeAt(i);
  return out;
}
const VAPID_PUBLIC="BJyzhyh7uhy6YRmyX4ygYcSrDtKIpsxxhYUAxXMph8OxoRBmI8bXWboZiMEmbx2l558qU6L3l6k7QpfAHfiwDvM";

async function doSubscribe(){
  try{
    alert("Trying to subscribe...");
    const reg=await navigator.serviceWorker.register('/static/sw.js');
    await navigator.serviceWorker.ready;
    const sub=await reg.pushManager.subscribe({
      userVisibleOnly:true,
      applicationServerKey:urlBase64ToUint8Array(VAPID_PUBLIC)
    });
    const res=await fetch('/api/save-subscription',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(sub)
    });
    alert("✅ Push SAVED! Status:"+res.status);
  }catch(e){ alert("❌ FAILED: "+e.message); console.log(e); }
}

document.addEventListener('DOMContentLoaded',()=>{
  const all=document.querySelectorAll('input[type="checkbox"]');
  let pt=null;
  all.forEach(c=>{
    const t=(c.parentElement?.innerText||"").toLowerCase();
    if(t.includes("notification")) pt=c;
  });
  if(!pt) pt=document.getElementById('pushToggle')||document.getElementById('notifyToggle');
  if(pt){
    pt.addEventListener('change', async()=>{
      if(pt.checked){
        const perm=await Notification.requestPermission();
        if(perm==='granted') await doSubscribe();
        else { pt.checked=false; alert("Denied"); }
      }
    });
    if(pt.checked && Notification.permission==='granted') doSubscribe();
  }
});";

async function doSubscribe(){
  try{
    alert("Trying to subscribe...");
    const reg=await navigator.serviceWorker.register('/static/sw.js');
    await navigator.serviceWorker.ready;
    const sub=await reg.pushManager.subscribe({
      userVisibleOnly:true,
      applicationServerKey:urlBase64ToUint8Array(VAPID_PUBLIC)
    });
    const res=await fetch('/api/save-subscription',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(sub)
    });
    alert("✅ Push SAVED! Status:"+res.status);
  }catch(e){ alert("❌ FAILED: "+e.message); console.log(e); }
}

document.addEventListener('DOMContentLoaded',()=>{
  const all=document.querySelectorAll('input[type="checkbox"]');
  let pt=null;
  all.forEach(c=>{
    const t=(c.parentElement?.innerText||"").toLowerCase();
    if(t.includes("notification")) pt=c;
  });
  if(!pt) pt=document.getElementById('pushToggle')||document.getElementById('notifyToggle');
  if(pt){
    pt.addEventListener('change', async()=>{
      if(pt.checked){
        const perm=await Notification.requestPermission();
        if(perm==='granted') await doSubscribe();
        else { pt.checked=false; alert("Denied"); }
      }
    });
    if(pt.checked && Notification.permission==='granted') doSubscribe();
  }
});
