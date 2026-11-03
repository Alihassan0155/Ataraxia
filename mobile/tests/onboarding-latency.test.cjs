const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
function load(name, mocks = {}) {
  const code = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src/services/', name + '.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const context = { exports: {}, Response, performance, process: { env: { EXPO_PUBLIC_API_URL: 'http://fixture.invalid' } },
    require: name => {

      if (mocks[name]) return mocks[name];
      throw new Error('Unexpected dependency');
    } };
  vm.runInNewContext(code, context);
  return context.exports;
}
const data = { interests: [{ id: 'a', name: 'A', taxonomy_version: 'v1' }] };
const response = () => new Response(JSON.stringify(data));

test('public taxonomy prefetch coalesces, caches and expires without caching user data', async () => {
  const { CategoryCatalogue } = load('onboarding-data', { './request': {} });
  let calls = 0, now = 0, finish;
  const catalogue = new CategoryCatalogue(() => { calls++; return new Promise(resolve => { finish = resolve; }); }, () => now);
  const one = catalogue.get(), two = catalogue.get();
  assert.equal(calls, 1); finish(response()); await Promise.all([one, two]);
  await catalogue.get(); assert.equal(calls, 1);
  now = 300001; const fresh = catalogue.get(); assert.equal(calls, 2); finish(response()); await fresh;
});
test('failed taxonomy prefetch remains retryable', async () => {
  const { CategoryCatalogue } = load('onboarding-data', { './request': {} });
  let calls = 0;
  const catalogue = new CategoryCatalogue(async () => ++calls === 1 ? new Response('{}', { status: 503 }) : response());
  await assert.rejects(catalogue.get()); await catalogue.get(); assert.equal(calls, 2);
});
test('Strict Mode concurrent restoration uses one session verification', async () => {
  let verifies = 0;
  const auth = load('auth', {
    'react-native': { Platform: { OS: 'ios' } },
    'expo-secure-store': { getItemAsync: async () => 'fixture-token' },
    './request': { apiFetch: async () => { verifies++; await new Promise(resolve => setTimeout(resolve, 10)); return new Response('{}'); } },
  });
  const result = await Promise.all([auth.restoreSession(), auth.restoreSession()]);
  assert.equal(result.every(Boolean), true); assert.equal(verifies, 1);
});
test('secure token writes start together and finish before session resolves', async () => {
  const writes = [], finish = [];
  const auth = load('auth', {
    'react-native': { Platform: { OS: 'ios' } }, './request': {},
    'expo-secure-store': { setItemAsync: async key => { writes.push(key); await new Promise(resolve => finish.push(resolve)); } },
  });
  let saved = false;
  const pending = auth.saveSession('fixture-access', 'fixture-refresh').then(() => { saved = true; });
  assert.equal(writes.length, 2); assert.equal(saved, false);
  finish.forEach(resolve => resolve()); await pending; assert.equal(saved, true);
});
test('a failed token write settles both writes before clearing partial credentials', async () => {
  const removed = [];
  let finish;
  const auth = load('auth', {
    'react-native': { Platform: { OS: 'ios' } }, './request': {},
    'expo-secure-store': {
      setItemAsync: key => key.includes('access') ? Promise.reject(new Error('storage')) : new Promise(resolve => { finish = resolve; }),
      deleteItemAsync: async key => { removed.push(key); },
    },
  });
  const pending = auth.saveSession('fixture-access', 'fixture-refresh');
  await new Promise(resolve => setImmediate(resolve)); assert.equal(removed.length, 0);
  finish(); await assert.rejects(pending); assert.equal(removed.length, 2);
});
