// Controlled request-latency benchmark; not a production/iPhone login result.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const source = fs.readFileSync(path.join(__dirname, '../src/services/preference-flow.ts'), 'utf8');
const context = { exports: {} };
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context);
const { loadPreferenceSelection } = context.exports;
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const interests = [{ id: 'a', name: 'A', taxonomy_version: 'test' }];
const med = list => [...list].sort((a, b) => a - b)[Math.floor(list.length / 2)];
(async () => {
  const before = [], after = [], cached = [];
  for (let n = 0; n < 5; n++) {
    const request = async route => {
      await wait(route.includes('onboarding') ? 120 : 200);
      return { ok: true, json: async () => ({ interests }) };
    };
    let started = performance.now();
    await request('/onboarding/interests'); await request('/users/me/interests');
    before.push(performance.now() - started);
    started = performance.now(); await loadPreferenceSelection(request); after.push(performance.now() - started);
    started = performance.now(); await loadPreferenceSelection(route => route.includes('onboarding')
      ? Promise.resolve({ ok: true, json: async () => ({ interests }) }) : request(route));
    cached.push(performance.now() - started);
  }
  const result = { scope: 'Controlled Node request fixture: categories=120 ms, saved preferences=200 ms; excludes login, native storage and rendering.',
    runs: 5, before_serial_median_ms: +med(before).toFixed(2), after_parallel_median_ms: +med(after).toFixed(2),
    after_prefetched_median_ms: +med(cached).toFixed(2), production_login_ms: null, iphone_render_ms: null };
  const dir = path.join(__dirname, '../../backend/reports/login_latency_20261020'); fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'controlled_comparison.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
})().catch(() => { console.error('Onboarding fixture profile failed.'); process.exitCode = 1; });
