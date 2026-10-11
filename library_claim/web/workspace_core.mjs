// Scope legacy controllers without navigating or creating another document.
export function componentEnvironment(root, realDocument, realWindow, url, callbacks={}) {
  const listeners=[],cleanup=[];
  const listen=(target,name,callback,options)=>{target.addEventListener(name,callback,options);listeners.push(()=>target.removeEventListener(name,callback,options));if(name==='pagehide')cleanup.push(callback);};
  const document=new Proxy(realDocument,{get(target,key){
    if(['getElementById','querySelector','querySelectorAll'].includes(key))return root[key].bind(root);
    if(key==='addEventListener')return (name,callback,options)=>listen(target,name,callback,options);
    const value=Reflect.get(target,key,target);return typeof value==='function'?value.bind(target):value;
  }});
  const window=new Proxy(realWindow,{get(target,key){
    if(key==='parent'||key==='self'||key==='window')return window;
    if(key==='addEventListener')return (name,callback,options)=>listen(target,name,callback,options);
    const value=Reflect.get(target,key,target);return typeof value==='function'?value.bind(target):value;
  }});
  return {document,environment:{...callbacks,window,location:new URL(url,realWindow.location.href),history:{replaceState(){}}},
    dispose(){for(const callback of cleanup.splice(0))callback();for(const remove of listeners.splice(0))remove();}};
}

export function workflowPath(url) {
  const routes=new Set(['/recognition','/identity','/geometry','/registration','/resolution','/valuation','/contents','/areas','/packet']);
  return routes.has(url.pathname)?url.pathname.slice(1):null;
}
