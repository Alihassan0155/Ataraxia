export function canContinue(ids: string[], loaded: boolean, loading: boolean, saving: boolean): boolean {
  return loaded && !loading && !saving && ids.length > 0;
}

export async function launchDestination(restore: () => Promise<boolean>): Promise<'/(onboarding)/interests' | '/login'> {
  return await restore() ? '/(onboarding)/interests' : '/login';
}

type Interest = { id: string; name: string; taxonomy_version: string };
export async function loadPreferenceSelection(request: (path: string) => Promise<Response>, onCategories?: (items: Interest[]) => void): Promise<{ interests: Interest[]; selectedIds: string[] }> {
  async function read(path: string): Promise<Interest[]> {
    const response = await request(path);
    if (!response.ok) throw new Error('Could not load your interests. Please retry.');
    const data = await response.json();
    if (!Array.isArray(data.interests) || data.interests.some((item: Interest) =>
      !item || typeof item.id !== 'string' || typeof item.name !== 'string' || typeof item.taxonomy_version !== 'string')) {
      throw new Error('Invalid interest response. Please retry.');
    }
    return data.interests;
  }
  const [interests, saved] = await Promise.all([
    read('/onboarding/interests').then(items => { onCategories?.(items); return items; }),
    read('/users/me/interests'),
  ]);
  if (saved.some(item => !interests.some(category => category.id === item.id))) {
    throw new Error('Saved interests are unavailable. Please retry.');
  }
  return { interests, selectedIds: saved.map(item => item.id) };
}

export async function saveSelection(ids: string[], save: () => Promise<void>, navigate: () => void): Promise<void> {
  if (ids.length === 0) throw new Error('Select at least one interest.');
  await save();
  navigate();
}
