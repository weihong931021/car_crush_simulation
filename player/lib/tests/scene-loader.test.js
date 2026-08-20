// registry 契約測試：模型參考幾何的隱藏規則。
// 起因（2026-07-24 審查）：wrapModel 用裸 startsWith() 比對 registry 的 hide 清單，
// "Object_4" 因此連 Object_41/43/44/46/48（車身、油箱、輪胎，533–3002 頂點）一起隱藏，
// 機車在畫面上缺件。改為「精確名稱」語意後，這裡同時鎖住規則本身與 registry 的實際內容。
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { shouldHideNode, modelFor } from '../../scene-loader.js';

const repoPath = rel => fileURLToPath(new URL(rel, import.meta.url));

// GLB 的 JSON chunk：header 12 bytes（magic/version/length）+ chunk header 8 bytes。
function glbNodeNames(file) {
  const buf = readFileSync(file);
  const jsonLen = buf.readUInt32LE(12);
  const gltf = JSON.parse(buf.subarray(20, 20 + jsonLen).toString('utf8'));
  return (gltf.nodes || []).map(n => n.name || '');
}

test('shouldHideNode: 精確名稱命中，前綴不得誤殺同前綴的其他節點', () => {
  const hide = ['Object_4'];
  assert.equal(shouldHideNode('Object_4', hide), true, '列出的名稱要隱藏');
  for (const name of ['Object_41', 'Object_43', 'Object_44', 'Object_46', 'Object_48']) {
    assert.equal(shouldHideNode(name, hide), false, `${name} 是真實零件，不得被 Object_4 誤殺`);
  }
});

test('shouldHideNode: 空清單、未列名稱、無名節點一律不隱藏', () => {
  assert.equal(shouldHideNode('Object_4', []), false);
  assert.equal(shouldHideNode('Object_4', undefined), false);
  assert.equal(shouldHideNode('Tank', ['floor_0']), false);
  assert.equal(shouldHideNode('', ['floor_0']), false, '無名節點不得被空字串之類的項目命中');
  assert.equal(shouldHideNode(undefined, ['floor_0']), false);
});

test('registry: moto.glb 的 hide 清單只命中地面圓片，不碰車體零件', () => {
  const registry = JSON.parse(readFileSync(repoPath('../../models/registry.json'), 'utf8'));
  const hide = modelFor('Two_Wheeler', registry).hide;
  const names = glbNodeNames(repoPath('../../models/moto.glb'));

  const hidden = names.filter(n => shouldHideNode(n, hide));
  assert.deepEqual(hidden.sort(), ['floor_0'],
    `moto.glb 只有 floor_0（地面圓片的父節點）該被隱藏，實得 ${JSON.stringify(hidden)}`);

  // hide 清單裡的每個名稱都必須真的存在於模型中——打錯字的項目會靜默失效。
  for (const h of hide) {
    assert.ok(names.includes(h), `hide 項目 "${h}" 在 moto.glb 找不到對應節點`);
  }
  // 場景根節點（整個模型的父節點）絕不可出現在 hide 清單：隱藏它＝整台車消失。
  assert.ok(!hide.includes('MotoCollider'), 'MotoCollider 是模型根節點，隱藏它會讓整台車消失');
});

test('modelFor: 無 hide 設定的模型回傳空清單', () => {
  const registry = JSON.parse(readFileSync(repoPath('../../models/registry.json'), 'utf8'));
  assert.deepEqual(modelFor('Car', registry).hide, [], 'car.glb 未設 hide，應得空清單而非 undefined');
});
