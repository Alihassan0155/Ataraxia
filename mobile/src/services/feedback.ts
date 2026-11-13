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

  return 'Could not save or load video feedback. Please try again.';
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

export async function setVideoFeedback(
  videoId: string,
  isLiked: boolean
): Promise<FeedbackState> {
  const response = await authenticatedFetch(
    `/feedback/videos/${encodeURIComponent(videoId)}`,
    {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify({
        is_liked: isLiked,
      }),
    }
  );

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  const data = (await response.json()) as FeedbackState;

  if (
    !data ||
    data.video_id !== videoId ||
    typeof data.is_liked !== 'boolean' ||
    typeof data.has_feedback !== 'boolean'
  ) {
    throw new Error('Invalid feedback response from the server.');
  }

  return data;
}
