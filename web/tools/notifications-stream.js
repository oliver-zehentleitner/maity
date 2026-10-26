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
vm.runInNewContext(fs.readFileSync(require('path').join(process.argv[2], 'js/notify.js'),'utf8'),{window,console,Date,Set,Promise,encodeURIComponent,AbortController});
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
 const realGet=api.get;
 api.get=async(path)=>{ if(path.includes('after='))throw {status:404}; return {next_after:'new-head'}; };
 api.missingRoute=async()=>true;
 M.notify.startBrowser({me:{id:'human'}},{browser:{enabled:true,kinds:{}}});await flush();
 assert.equal(M.notify.state.available,false);
 assert.equal(M.notify.running(),false,'missing endpoint must not look like a live browser stream');
 api.get=realGet;api.missingRoute=async()=>false;M.notify.state.available=true;
 M.notify.startBrowser({me:{id:'human'}},{browser:{enabled:true,kinds:{}}});await flush();
 assert.equal(pending.length,1,'stream restarts after the endpoint returns');
 M.notify.stopBrowser();pending.shift()({items:[]});await flush();
 // A session ended on purpose (password change, sign-out): halt cancels the held poll,
 // nothing goes out until resume, and a 401 on the stream ends it instead of retrying.
 const aborted=[];pending.length=0;
 api.get=async(path,opts)=>{calls.push(path);if(path.includes('limit=0'))return {next_after:'h'};
  return new Promise((resolve,reject)=>{pending.push(resolve);if(opts&&opts.signal)opts.signal.addEventListener('abort',()=>{aborted.push(path);reject({code:'aborted'});});});};
 const sub=M.notify.subscribe(()=>{});await flush();
 assert.equal(pending.length,1,'the stream holds one long-poll');
 M.notify.halt();await flush();
 assert.equal(aborted.length,1,'halt cancels the held long-poll');
 const quiet=calls.length;[...timers.values()].forEach(f=>f());timers.clear();await flush();
 assert.equal(calls.length,quiet,'nothing goes out while halted');
 pending.length=0;M.notify.resume();await flush();
 assert.equal(pending.length,1,'resume starts the stream again');
 api.get=async(path)=>{calls.push(path);throw {status:401,code:'unauthenticated'};};
 const c401=calls.length;pending.shift()({items:[],next_after:'n'});await flush();
 [...timers.values()].forEach(f=>f());timers.clear();await flush();
 assert.equal(calls.length-c401,1,'a 401 ends the stream, no retry');
 sub();
 console.log('Shared stream: single in-flight poll, settings restart, opaque-position recovery, disposal, endpoint recovery, halt and resume, 401 end PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
