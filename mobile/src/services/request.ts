/** Time out the complete small JSON response, including body download. */
export async function apiFetch(input: string, options: RequestInit = {}, timeoutMs = 20000): Promise<Response> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (options.signal?.aborted) controller.abort();
  options.signal?.addEventListener('abort', abort, { once: true });
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  try {
    const response = await fetch(input, { ...options, signal: controller.signal });
    const body = await response.text();
    return new Response(response.status === 204 ? null : body, {
      status: response.status, statusText: response.statusText, headers: response.headers,
    });
  } catch {
    if (options.signal?.aborted) { const error = new Error('Request cancelled.'); error.name = 'AbortError'; throw error; }
    throw new Error(timedOut ? 'Request timed out. Please retry.' : 'Could not connect. Check your network and retry.');
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener('abort', abort);
  }
}
