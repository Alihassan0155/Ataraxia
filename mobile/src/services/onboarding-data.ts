import { apiFetch } from './request';

/** Cache only public taxonomy, never a user's preferences or authentication. */
export class CategoryCatalogue {
  private value: unknown;
  private expires = 0;
  private pending: Promise<unknown> | null = null;
  constructor(private request: () => Promise<Response>, private now = Date.now) {}
  async get(): Promise<unknown> {
    if (this.value && this.expires > this.now()) return this.value;
    if (!this.pending) {
      this.pending = this.request().then(async response => {
        if (!response.ok) throw new Error('Could not load interest categories. Please retry.');

        const data = await response.json();
        if (!Array.isArray(data.interests) || data.interests.some((item: {id: string; name: string; taxonomy_version: string}) =>
          !item || typeof item.id !== 'string' || typeof item.name !== 'string' || typeof item.taxonomy_version !== 'string')) {
          throw new Error('Invalid interest categories. Please retry.');
        }
        this.value = data; this.expires = this.now() + 300000;
        return data;
      }).finally(() => { this.pending = null; });
    }
    return this.pending;
  }
}
const catalogue = new CategoryCatalogue(() => {
  const base = process.env.EXPO_PUBLIC_API_URL;
  if (!base) throw new Error('API address is not configured.');
  return apiFetch(base + '/onboarding/interests');
});
export function prefetchCategories() { void catalogue.get().catch(() => {}); }
export async function publicCategories(): Promise<Response> {
  const data = await catalogue.get();
  return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } });
}
