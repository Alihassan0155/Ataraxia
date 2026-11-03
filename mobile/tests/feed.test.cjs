const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const vm = require('node:vm');

function load(name, extra = {}) {
  const source = fs.readFileSync(path.join(__dirname, '../src/services/', name + '.ts'), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const context = { exports: {}, Response, AbortController, setTimeout, clearTimeout, performance, process: { env: { EXPO_PUBLIC_API_URL: 'http://test.invalid' } }, ...extra };
  vm.runInNewContext(code, context);
  return context.exports;
}
const { FeedClient, mergeCandidates } = load('feed');
const response = (data, status = 200) => new Response(JSON.stringify(data), { status });

test('pages preserve retry cursor and deduplicate without exceeding fifty', async () => {
  const calls = [];
  const client = new FeedClient(async url => {
    calls.push(url);
    if (calls.length === 1) return response({}, 503);
    return response({ videos: [{ video_id: 'a' }], total: 50, next_cursor: 'cursor:5' });
  });
  await client.page('cursor:0');
  assert.equal(calls.length, 2); assert.equal(calls[0], calls[1]);
  assert.equal(mergeCandidates([{ video_id: 'a' }], [{ video_id: 'a' }, { video_id: 'b' }]).length, 2);
  assert.equal(mergeCandidates([], Array.from({ length: 80 }, (_, n) => ({ video_id: String(n) }))).length, 50);
});
test('expired snapshots never silently resample or retry and auth failures do not retry', async () => {
  for (const status of [401, 410]) {
    let calls = 0;
    const client = new FeedClient(async () => { calls++; return response({}, status); });
    await assert.rejects(client.page('old:5')); assert.equal(calls, 1);
  }
});
test('playback URLs cache near use, renew before expiry, and force refresh after errors', async () => {
  let now = 0, calls = 0;
  const client = new FeedClient(async () => { calls++; return response({ video_id: 'a', playback_url: 'https://example.invalid/private', expires_in: 300 }); }, () => now);
  await client.playback('a'); await client.playback('a'); assert.equal(calls, 1);
  now = 271000; await client.playback('a'); assert.equal(calls, 2);
  await client.playback('a', undefined, true); assert.equal(calls, 3);
});
test('first page carries only the first near-playback URL and avoids another request', async () => {
  let calls = 0;
  const client = new FeedClient(async () => {
    calls++;
    return response({ videos: [{ video_id: 'a' }], total: 1, next_cursor: null,
      initial_playback: { video_id: 'a', playback_url: 'https://example.invalid/private', expires_in: 300 } });
  });
  await client.page(null); await client.playback('a'); assert.equal(calls, 1);
});
test('cancelled requests do not fetch or retry; malformed responses rejected', async () => {
  let calls = 0;
  const client = new FeedClient(async () => { calls++; return response({}); });
  const controller = new AbortController(); controller.abort();
  await assert.rejects(client.page(null, controller.signal)); assert.equal(calls, 0);
  await assert.rejects(client.page(null));
  await assert.rejects(client.playback('a'));
});
test('partial background failure retains the already delivered page and resumes same cursor', async () => {
  let broken = true;
  const client = new FeedClient(async url => {
    if (!url.includes('cursor=')) return response({ videos: [{ video_id: 'a' }], total: 2, next_cursor: 'same:1' });
    if (broken) return response({}, 503);
    return response({ videos: [{ video_id: 'b' }], total: 2, next_cursor: null });
  });
  const first = await client.page(null);
  await assert.rejects(client.page(first.next_cursor));
  assert.equal(first.videos.length, 1);
  broken = false;
  const rest = await client.page(first.next_cursor);
  assert.equal(mergeCandidates(first.videos, rest.videos).length, 2);
});

test('API timeout includes slow body download and cancellation stays distinguishable', async () => {
  const { apiFetch } = load('request', { fetch: async (_, options) => ({
    text: () => new Promise((resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('aborted')))),
  }) });
  await assert.rejects(apiFetch('http://test.invalid', {}, 10), /timed out/);
  const controller = new AbortController();
  const pending = apiFetch('http://test.invalid', { signal: controller.signal }, 1000);
  await new Promise(resolve => setImmediate(resolve)); controller.abort();
  await assert.rejects(pending, error => error.name === 'AbortError');
});

test('simultaneous 401 responses share one refresh, including late stale responses', async () => {
  const store = new Map([['ataraxia_access_token', 'old'], ['ataraxia_refresh_token', 'refresh']]);
  let refreshes = 0;
  const mockFetch = async (url, options) => {
    if (url.endsWith('/auth/refresh')) {
      refreshes++; await new Promise(resolve => setTimeout(resolve, 10));
      return response({ access_token: 'new', refresh_token: 'rotated' });
    }
    return response({}, options.headers.Authorization === 'Bearer old' ? 401 : 200);
  };
  const auth = load('auth', { require: name => {

    if (name === './request') return { apiFetch: mockFetch };
    if (name === 'react-native') return { Platform: { OS: 'ios' } };
    if (name === 'expo-secure-store') return {
      getItemAsync: async key => store.get(key) || null,
      setItemAsync: async (key, value) => store.set(key, value), deleteItemAsync: async key => store.delete(key),
    };
    throw new Error('Unexpected dependency');
  } });
  const results = await Promise.all([auth.authenticatedFetch('/a'), auth.authenticatedFetch('/b')]);
  assert.equal(refreshes, 1); assert.equal(results.every(r => r.status === 200), true);
});
