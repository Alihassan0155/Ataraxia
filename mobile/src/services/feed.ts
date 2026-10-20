export type Candidate = { video_id: string; title: string | null; category_name: string };
export type FeedPage = { videos: Candidate[]; total: number; next_cursor: string | null };
export class FeedError extends Error {
  constructor(message: string, public status: number) { super(message); }
}
type Request = (path: string, options?: RequestInit) => Promise<Response>;

export function mergeCandidates(current: Candidate[], incoming: Candidate[]): Candidate[] {
  const seen = new Set(current.map(item => item.video_id));
  return [...current, ...incoming.filter(item => { if (seen.has(item.video_id)) return false; seen.add(item.video_id); return true; })].slice(0, 50);
}

export class FeedClient {
  private urls = new Map<string, { url: string; expires: number }>();
  constructor(private request: Request, private now = Date.now) {}

  private async json(path: string, signal?: AbortSignal) {
    for (let attempt = 0; ; attempt++) {
      if (signal?.aborted) { const error = new Error('Request cancelled.'); error.name = 'AbortError'; throw error; }
      try {
        const response = await this.request(path, { signal });
        if (!response.ok) throw new FeedError(response.status === 410 ? 'Feed expired. Refresh to load a new feed.' : 'Could not load videos. Please retry.', response.status);
        return await response.json();
      } catch (error) {
        if (signal?.aborted || (error instanceof Error && error.name === 'AuthenticationError')) throw error;
        if (attempt >= 1 || (error instanceof FeedError && error.status < 500 && error.status !== 429)) throw error;
        await new Promise<void>((resolve, reject) => {
          const abort = () => { clearTimeout(timer); signal?.removeEventListener('abort', abort); reject(new Error('Request cancelled.')); };
          const timer = setTimeout(() => { signal?.removeEventListener('abort', abort); resolve(); }, 400);
          signal?.addEventListener('abort', abort, { once: true });
        });
      }
    }
  }

  async page(cursor: string | null, signal?: AbortSignal): Promise<FeedPage> {
    const started = this.now();
    const data = await this.json('/recommendations/feed?page_size=' + (cursor ? '45&cursor=' + encodeURIComponent(cursor) : '5'), signal);
    if (!Array.isArray(data.videos) || data.videos.some((item: Candidate) => !item || typeof item.video_id !== 'string') ||
        !Number.isInteger(data.total) || data.total < 0 || data.total > 50 ||
        (data.next_cursor !== null && typeof data.next_cursor !== 'string')) throw new Error('Invalid feed response. Please retry.');
    if (!cursor && data.initial_playback && data.videos[0]) {
      this.cachePlayback(data.videos[0].video_id, data.initial_playback, started);
    }
    return data;
  }

  private cachePlayback(id: string, data: { video_id: string; playback_url: string; expires_in: number }, started: number) {
    if (data.video_id !== id || typeof data.playback_url !== 'string' || !data.playback_url.startsWith('https://') ||
        !Number.isFinite(data.expires_in) || data.expires_in <= 0) throw new Error('Invalid playback response.');
    const value = { url: data.playback_url, expires: started + Math.min(data.expires_in, 300) * 1000 };
    this.urls.delete(id);
    this.urls.set(id, value);
    if (this.urls.size > 4) this.urls.delete(this.urls.keys().next().value!);
    return value;
  }

  async playback(id: string, signal?: AbortSignal, force = false) {
    const cached = this.urls.get(id);
    if (!force && cached && cached.expires > this.now() + 30000) return cached;
    const started = this.now();
    const data = await this.json('/catalogue/videos/' + encodeURIComponent(id) + '/playback', signal);
    return this.cachePlayback(id, data, started);
  }
}
