import { authenticatedFetch } from '@/services/auth';

export type FeedbackState = {
  video_id: string;
  is_liked: boolean;
  has_feedback: boolean;
};

type FeedbackBatchResponse = {
  states: FeedbackState[];
};

async function getErrorMessage(response: Response): Promise<string> {
  try {
    const data = await response.json();

    if (typeof data.detail === 'string') {
      return data.detail;
    }
  }
  catch {
    // Use the fallback message if the response is not JSON.
  }

  return 'Could not load video feedback. Please try again.';
}

export async function getFeedbackStates(
  videoIds: string[],
  signal?: AbortSignal
): Promise<FeedbackState[]> {
  const states: FeedbackState[] = [];

  // The backend accepts a maximum of 50 video IDs per request.
  for (let start = 0; start < videoIds.length; start += 50) {
    if (signal?.aborted) {
      const error = new Error('Request cancelled.');
      error.name = 'AbortError';
      throw error;
    }

    const batch = videoIds.slice(start, start + 50);

    if (batch.length === 0) {
      continue;
    }

    const response = await authenticatedFetch('/feedback/batch-state', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({
        video_ids: batch,
      }),
      signal,
    });

    if (!response.ok) {
      throw new Error(await getErrorMessage(response));
    }

    const data = (await response.json()) as FeedbackBatchResponse;

    if (
      !data ||
      !Array.isArray(data.states) ||
      data.states.length !== batch.length ||
      data.states.some(state =>
        !state ||
        typeof state.video_id !== 'string' ||
        typeof state.is_liked !== 'boolean' ||
        typeof state.has_feedback !== 'boolean'
      )
    ) {
      throw new Error('Invalid feedback response from the server.');
    }

    states.push(...data.states);
  }

  return states;
}