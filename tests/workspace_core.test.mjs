import test from 'node:test';
import assert from 'node:assert/strict';
import {componentEnvironment,workflowPath} from '../library_claim/web/workspace_core.mjs';
test('component IDs, events and navigation remain isolated in one document',()=>{
 const real=new EventTarget();real.hidden=false;real.createElement=name=>({name});real.querySelector=()=>null;
 const browser=new EventTarget();browser.location={href:'http://localhost:4186/'};
 const root={getElementById:id=>({component:id}),querySelector:()=>({scoped:true}),querySelectorAll:()=>[]};
 const scope=componentEnvironment(root,real,browser,'/voice?session=one');let hidden=0,closed=0;
 assert.deepEqual(scope.document.getElementById('status'),{component:'status'});assert.deepEqual(scope.document.createElement('p'),{name:'p'});
 assert.equal(scope.environment.window.parent,scope.environment.window);assert.equal(scope.environment.location.search,'?session=one');
 scope.document.addEventListener('visibilitychange',()=>hidden++);scope.environment.window.addEventListener('pagehide',()=>closed++);
 real.dispatchEvent(new Event('visibilitychange'));assert.equal(hidden,1);scope.dispose();assert.equal(closed,1);
 real.dispatchEvent(new Event('visibilitychange'));assert.equal(hidden,1);scope.dispose();assert.equal(closed,1);
});
test('only workflow routes mount another panel',()=>{
 assert.equal(workflowPath(new URL('http://localhost/identity?session=a')),'identity');
 assert.equal(workflowPath(new URL('http://localhost/api/frames/x')),null);
});
