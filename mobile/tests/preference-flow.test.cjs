const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/services/preference-flow.ts'), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const context = { exports: {} };
vm.runInNewContext(code, context);
const { canContinue, saveSelection } = context.exports;
const { launchDestination, loadPreferenceSelection } = context.exports;

test('fresh and returning authenticated launches always require confirmation', async () => {
  assert.equal(await launchDestination(async () => true), '/(onboarding)/interests');
  assert.equal(await launchDestination(async () => false), '/login');
  await assert.rejects(launchDestination(async () => { throw new Error('offline'); }));
});
const interest = { id: 'a', name: 'A', taxonomy_version: 'v1' };
const response = interests => ({ ok: true, json: async () => ({ interests }) });
test('saved selections preselect and empty selections remain empty', async () => {
  const saved = await loadPreferenceSelection(async () => response([interest]));
  assert.equal(saved.selectedIds.join(','), 'a');
  const empty = await loadPreferenceSelection(async path => response(path.includes('onboarding') ? [interest] : []));
  assert.equal(empty.selectedIds.length, 0);
});
test('failed and malformed preferences are never interpreted as empty', async () => {
  for (const bad of [{ ok: false }, { ok: true, json: async () => ({}) }]) {
    await assert.rejects(loadPreferenceSelection(async path => path.includes('onboarding') ? response([interest]) : bad));
  }
  await assert.rejects(loadPreferenceSelection(async () => { throw new Error('network'); }));
});
test('slow loading does not resolve before saved preferences arrive', async () => {
  let finish;
  let resolved = false;
  const pending = loadPreferenceSelection(async path => path.includes('onboarding') ? response([interest]) : new Promise(resolve => { finish = resolve; }));
  pending.then(() => { resolved = true; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(resolved, false);
  finish(response([interest]));
  await pending;
  assert.equal(resolved, true);
});
test('both independent requests start immediately and categories can render first', async () => {
  const calls = [];
  let categories, preferences;
  let rendered = false;
  const pending = loadPreferenceSelection(path => {
    calls.push(path);
    return new Promise(resolve => {
      if (path.includes('onboarding')) categories = resolve;
      else preferences = resolve;
    });
  }, () => { rendered = true; });
  assert.equal(calls.length, 2);
  categories(response([interest]));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(rendered, true);
  assert.equal(canContinue(['a'], false, true, false), false);
  preferences(response([interest]));
  const result = await pending;
  assert.equal(result.selectedIds.join(','), 'a');
});

test('Continue requires a selection and successful completed loading', () => {
  assert.equal(canContinue([], true, false, false), false);
  assert.equal(canContinue(['a'], false, false, false), false);
  assert.equal(canContinue(['a'], true, true, false), false);
  assert.equal(canContinue(['a'], true, false, true), false);
  assert.equal(canContinue(['a'], true, false, false), true);
});
test('navigation waits for successful persistence', async () => {
  const events = [];
  let finish;
  const pending = saveSelection(['a'], () => new Promise(resolve => { finish = resolve; }), () => events.push('navigate'));
  assert.deepEqual(events, []);
  finish();
  await pending;
  assert.deepEqual(events, ['navigate']);
});
test('save failure stays on screen and can be retried', async () => {
  let navigations = 0;
  await assert.rejects(saveSelection(['a'], async () => { throw new Error('unavailable'); }, () => navigations++));
  assert.equal(navigations, 0);
  await saveSelection(['a'], async () => {}, () => navigations++);
  assert.equal(navigations, 1);
});
test('empty selections cannot save or navigate', async () => {
  let called = false;
  await assert.rejects(saveSelection([], async () => { called = true; }, () => { called = true; }));
  assert.equal(called, false);
});
