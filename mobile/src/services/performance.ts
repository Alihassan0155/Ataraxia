/** In-memory confirmation revision; refresh candidates after preferences change. */
let revision = 0;
export function confirmPreferences() { revision++; }
export function preferenceRevision() { return revision; }
