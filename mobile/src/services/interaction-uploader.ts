
import { authenticatedFetch } from '@/services/auth';
import type { InteractionEvent } from '@/services/interaction-tracking';
import type { PersistentInteractionQueue } from '@/services/interaction-queue';

type SessionRegistrationResponse = {
  session_id: string;
  registered: boolean;
};

type InteractionBatchResponse = {
  accepted_event_ids: string[];
  accepted_count: number;
};

type SessionCloseResponse = {
  session_id: string;
  ended_at: string;
};

async function getErrorMessage(response: Response): Promise<string> {
  try {
    const data = await response.json();

    if (typeof data.detail === 'string') {
      return data.detail;
    }
  } catch {
    // The response may not contain JSON.
  }

  return `Interaction request failed (${response.status}).`;
}

export async function registerInteractionSession(
  sessionId: string
): Promise<SessionRegistrationResponse> {
  const response = await authenticatedFetch('/interactions/sessions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({
      session_id: sessionId,
    }),
  });

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  const data: unknown = await response.json();

  if (
    typeof data !== 'object' ||
    data === null ||
    !('session_id' in data) ||
    data.session_id !== sessionId ||
    !('registered' in data) ||
    typeof data.registered !== 'boolean'
  ) {
    throw new Error('The interaction server returned an invalid session response.');
  }

  return data as SessionRegistrationResponse;
}

export async function uploadInteractionBatch(
  events: InteractionEvent[]
): Promise<InteractionBatchResponse> {
  if (events.length === 0) {
    return {
      accepted_event_ids: [],
      accepted_count: 0,
    };
  }

  if (events.length > 50) {
    throw new Error('An interaction batch cannot contain more than 50 events.');
  }

  const response = await authenticatedFetch('/interactions/batch', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({
      events,
    }),
  });

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  const data: unknown = await response.json();

  if (
    typeof data !== 'object' ||
    data === null ||
    !('accepted_event_ids' in data) ||
    !Array.isArray(data.accepted_event_ids) ||
    !('accepted_count' in data) ||
    typeof data.accepted_count !== 'number' ||
    !Number.isInteger(data.accepted_count) ||
    data.accepted_count < 0
  ) {
    throw new Error('The interaction server returned an invalid acknowledgement.');
  }

  const acceptedIds: unknown[] = data.accepted_event_ids;

  if (
    acceptedIds.some(eventId => typeof eventId !== 'string') ||
    data.accepted_count !== acceptedIds.length
  ) {
    throw new Error('The interaction server returned an inconsistent acknowledgement.');
  }

  const uniqueAcceptedIds = new Set(acceptedIds as string[]);

  if (uniqueAcceptedIds.size !== acceptedIds.length) {
    throw new Error('The interaction server returned duplicate event IDs.');
  }

  const sentIds = new Set(events.map(event => event.event_id));

  if ((acceptedIds as string[]).some(eventId => !sentIds.has(eventId))) {
    throw new Error('The interaction server acknowledged an event that was not submitted.');
  }

  return {
    accepted_event_ids: acceptedIds as string[],
    accepted_count: data.accepted_count,
  };
}

export async function closeInteractionSession(
  sessionId: string
): Promise<SessionCloseResponse> {
  const response = await authenticatedFetch(
    `/interactions/sessions/${encodeURIComponent(sessionId)}/close`,
    {
      method: 'POST',
      headers: {
        Accept: 'application/json',
      },
    }
  );

  if (!response.ok) {
    throw new Error(await getErrorMessage(response));
  }

  const data: unknown = await response.json();

  if (
    typeof data !== 'object' ||
    data === null ||
    !('session_id' in data) ||
    data.session_id !== sessionId ||
    !('ended_at' in data) ||
    typeof data.ended_at !== 'string' ||
    !Number.isFinite(Date.parse(data.ended_at))
  ) {
    throw new Error('The interaction server returned an invalid session-close response.');
  }

  return data as SessionCloseResponse;
}

export async function flushPendingInteractions(
  queue: PersistentInteractionQueue
): Promise<number> {
  let totalAccepted = 0;

  while (true) {
    const events = await queue.getPending(50);

    if (events.length === 0) {
      return totalAccepted;
    }

    const sessionIds = Array.from(
      new Set(events.map(event => event.session_id))
    );

    for (const sessionId of sessionIds) {
      await registerInteractionSession(sessionId);
    }

    const response = await uploadInteractionBatch(events);

    if (response.accepted_event_ids.length === 0) {
      return totalAccepted;
    }

    await queue.acknowledge(response.accepted_event_ids);

    totalAccepted += response.accepted_count;

    if (response.accepted_count < events.length) {
      return totalAccepted;
    }
  }
}
