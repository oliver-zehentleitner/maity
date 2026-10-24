const vm=require('vm'),fs=require('fs'),assert=require('assert');
const timers=new Map();let id=0,pending=[],calls=[],afterFails=false;
const api={absent:{has:()=>false,note:()=>{}},missingRoute:async()=>false,get:async(path)=>{
 calls.push(path);
 if(path.includes('limit=0'))return {next_after:'opaque-head',counts:{total:1},by_project:{}};
 if(afterFails){afterFails=false;throw {code:'invalid',details:{fields:{after:'position'}}};}
 return new Promise(resolve=>pending.push(resolve));
}};
function N(){} N.permission='granted';
const window={Maity:{dom:{},api},Notification:N,setTimeout:(fn)=>{timers.set(++id,fn);return id},clearTimeout:(i)=>timers.delete(i)};
vm.runInNewContext(fs.readFileSync(require('path').join(process.argv[2], 'js/notify.js'),'utf8'),{window,console,Date,Set,Promise,encodeURIComponent});
const flush=()=>new Promise(r=>setImmediate(r));
(async()=>{
 const M=window.Maity;M.notify.state.available=true;
 let refreshed=0;const one=M.notify.subscribe(()=>refreshed++);await flush();
 const two=M.notify.subscribe(()=>refreshed++);await flush();
 assert.equal(pending.length,1,'two consumers must share one in-flight poll');
 M.notify.startBrowser({me:{id:'human'}},{browser:{enabled:true,kinds:{},content:{}}});await flush();
 assert.equal(pending.length,1,'settings change must not overlap an in-flight poll');
 pending.shift()({items:[],next_after:'old-answer'});await flush();
 assert.equal(pending.length,1);assert.equal(calls.filter(x=>x.includes('limit=0')).length,2,'restart must get fresh opaque head');
 afterFails=true;pending.shift()({items:[{id:'ntf-x',kind:'card'}],next_after:'opaque-next'});await flush();
 assert(timers.size,'position rejection waits before retry');
 [...timers.values()].forEach(f=>f());timers.clear();await flush();
 assert(calls.filter(x=>x.includes('limit=0')).length>=3,'invalid after position must recover fresh head');
 assert(refreshed>0);one();two();M.notify.stopBrowser();pending.shift()({items:[],next_after:'end'});await flush();
 assert.equal(pending.length,0);
 console.log('Shared stream: single in-flight poll, settings restart, opaque-position recovery, disposal PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
