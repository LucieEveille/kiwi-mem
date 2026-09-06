import assert from 'node:assert/strict';
import { secretLabel, providerLabel, secretWriter } from '../admin-panel/js/secret-fields.mjs';
assert.equal(secretLabel({has_value: true, last4:'abcd'}), '已配置 · 尾号 abcd');
assert.equal(secretLabel({has_value: true, last4:''}), '已配置');
assert.equal(secretLabel({has_value: false}), '未配置');
assert.equal(providerLabel({api_key_preview: 'old-prefix'}),'未配置');
let writes=[], release;
const input={value:'',isConnected:true};
let meta;
const writer=secretWriter(input,{
  write: async value=>{writes.push(value); await new Promise(r=>{release=r;});},
  refresh: async()=>({has_value:true,last4:'tail'}), update:value=>{meta=value;},
});
await writer.submit(); assert.equal(writes.length,0);
input.value='first-key'; writer.changed(); const first=writer.submit();
await new Promise(r=>setImmediate(r));
input.value='new-input';writer.changed(); release(); await first;
assert.equal(input.value,'new-input'); assert.equal(meta.last4,'tail');
const second=writer.submit(); await new Promise(r=>setImmediate(r));release();await second;
assert.equal(input.value,''); assert.deepEqual(writes,[{value:'first-key'},{value:'new-input'}]);
await writer.submit(); assert.equal(writes.length,2);
const clear=writer.submit(true); await new Promise(r=>setImmediate(r));release();await clear;
assert.deepEqual(writes.at(-1),{clear:true});
console.log('PASS: admin secret metadata, blank no-op, ordered writes, stale response isolation, explicit clear');
