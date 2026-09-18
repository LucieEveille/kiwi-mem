#!/usr/bin/env node
// Deterministic panel behavior guards. No provider or browser network traffic.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const moduleURL = new URL('../admin-panel/js/embedding-panel.mjs', import.meta.url);
let mod;
try { await fs.access(moduleURL); mod = await import(moduleURL); }
catch (e) { if (e.code !== 'ENOENT') throw e; }
let failed = 0;
async function check(name, body) {
  try { assert.ok(mod, 'missing_seam:embedding-panel.mjs'); await body(); console.log(`PASS ${name}`); }
  catch (e) { if (!(e instanceof assert.AssertionError)) throw e; failed++; console.log(`FAIL ${name}: ${e.message}`); }
}
function harness() {
  const calls=[]; const rendered=[];
  const state=new mod.ProbeCoordinator({probe:({signal})=>new Promise(resolve=>calls.push({signal,resolve})),render:r=>rendered.push(r)});
  state.edit('A');
  return {state,calls,rendered};
}
await check('T-EMB-15 duplicate saves retain one live probe',async()=>{
  const {state,calls}=harness();
  const generation=state.generation;
  state.saved({value:'A',generation,saveId:1});
  state.saved({value:'A',generation,saveId:2});
  assert.equal(calls.length,1);
  assert.equal(calls[0].signal.aborted,false);
  calls[0].resolve({ok:true,model_id:'A'}); await new Promise(r=>setImmediate(r));
  assert.equal(state.result.ok,true);
});
await check('T-EMB-15 old save A after A-B-A cannot start a probe',async()=>{
  const {state,calls}=harness(); const old=state.generation;
  state.edit('B'); state.edit('A');
  state.saved({value:'A',generation:old,saveId:1});
  assert.equal(calls.length,0);
  state.saved({value:'A',generation:state.generation,saveId:2});
  assert.equal(calls.length,1);
  state.unmount(); assert.equal(calls[0].signal.aborted,true);
});
await check('T-EMB-15 route edits invalidate without auto-charging',async()=>{
  const {state,calls}=harness();
  state.saved({value:'A',generation:state.generation,saveId:1});
  state.invalidate(); assert.equal(calls[0].signal.aborted,true);
  assert.equal(state.result,null); assert.equal(calls.length,1);
  calls[0].resolve({ok:true}); await new Promise(r=>setImmediate(r));
  assert.equal(state.result,null);
  state.saved({value:'A',generation:state.generation,saveId:2});
  assert.equal(calls.length,2); state.unmount();
});
await check('T-EMB-17 failure receipt and partial finish',async()=>{
  assert.match(mod.describeProbe({ok:false,error_code:'timeout'}),/^设置已保存，本次嵌入测试失败/);
  const base={route:{available:true},totals:{current:3,pending_rows:2,pending_characters:20}};
  const message=mod.describeAlignment({...base,job:{state:'done',done:3,failed:2,skipped:1}});
  assert.match(message.text,/本轮已结束/); assert.match(message.text,/失败 2/);
  assert.doesNotMatch(message.text,/已重新计入|全部完成/);
  assert.equal(mod.describeAlignment({...base,job:{state:'running',lease_expired:false}}).poll,true);
  assert.equal(mod.describeAlignment({...base,job:{state:'running',lease_expired:true}}).disabled,false);
});
await check('T-EMB-17 input changes and unmount suppress late responses',async()=>{
  const {state,calls,rendered}=harness();
  state.saved({value:'A',generation:state.generation,saveId:1});
  state.edit('B'); calls[0].resolve({ok:true}); await new Promise(r=>setImmediate(r));
  assert.equal(state.result,null);
  state.saved({value:'B',generation:state.generation,saveId:2});
  state.unmount(); const count=rendered.length;
  calls[1].resolve({ok:true}); await new Promise(r=>setImmediate(r));
  assert.equal(rendered.length,count);
});
await check('T-EMB-15 model selector and probe share the same page',async()=>{
  const {CONFIG_PAGES}=await import('../admin-panel/js/config-schema.js');
  const keys=CONFIG_PAGES.providers.groups.flatMap(g=>g.keys || []);
  assert.ok(keys.includes('default_embedding_model'),'embedding selector must render beside alignment, so automatic probe can capture its generation');
});
console.log(`EMB panel: ${6-failed} PASS / ${failed} FAIL / 0 ERROR; pure runtime state, no real provider`);
process.exitCode=failed?1:0;
