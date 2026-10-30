const vm=require('vm'),fs=require('fs'),assert=require('assert');
const timers=new Map();let id=0,pending=[],calls=[],afterFails=false;
const api={get:async(path)=>{
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
 const M=window.Maity;
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
 // halt and resume at once, before the cancelled poll has settled: the old loop starts the next when it ends.
 const hung=[];
 api.get=async(path,opts)=>{calls.push(path);if(path.includes('limit=0'))return {next_after:'h2'};
  return new Promise((resolve,reject)=>{pending.push(resolve);hung.push(resolve);if(opts&&opts.signal)opts.signal.addEventListener('abort',()=>{aborted.push(path);setImmediate(()=>reject({code:'aborted'}));});});};
 // An answer with items: the loop asks again at once, so a poll is held when the session ends.
 pending.shift()({items:[{id:'ntf-r',kind:'card',read:true}],next_after:'n0'});await flush();
 const polls=()=>calls.filter((x)=>x.includes('after=')).length;
 const heldPolls=polls();
 M.notify.halt();M.notify.resume();
 assert.equal(polls(),heldPolls,'nothing new while the cancelled poll settles');
 await flush();await flush();
 assert.equal(polls(),heldPolls+1,'a resume during the cancellation restarts the stream once the old loop ends');
 pending.splice(0,pending.length-1);
 api.get=async(path)=>{calls.push(path);throw {status:401,code:'unauthenticated'};};
 const c401=calls.length;pending.shift()({items:[],next_after:'n'});await flush();
 [...timers.values()].forEach(f=>f());timers.clear();await flush();
 assert.equal(calls.length-c401,1,'a 401 ends the stream, no retry');
 sub();
 console.log('Shared stream: single in-flight poll, settings restart, opaque-position recovery, disposal, halt and resume, 401 end PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
