import * as Crypto from 'expo-crypto';

export type InteractionEventType =
  | 'impression'
  | 'watch'
  | 'completion'
  | 'skip'
  | 'rewatch';

export type InteractionMetadata = {
  [key: string]: string | number | boolean | null;
};

export type InteractionEvent = {
  event_id: string;
  session_id: string;
  video_id: string;
  event_type: InteractionEventType;
  occurred_at: string;
  watch_duration_ms?: number;
  metadata?: InteractionMetadata;
};

export type InteractionEventDetails = {
  watch_duration_ms?: number;
  metadata?: InteractionMetadata;
};

const MAX_PENDING_EVENTS = 500;

export function createInteractionId(): string {
  return Crypto.randomUUID();
}

export function createInteractionEvent(
  sessionId: string,
  videoId: string,
  eventType: InteractionEventType,
  details: InteractionEventDetails = {}
): InteractionEvent {
  const event: InteractionEvent = {
    event_id: createInteractionId(),
    session_id: sessionId,
    video_id: videoId,
    event_type: eventType,
    occurred_at: new Date().toISOString(),
  };

  if (details.watch_duration_ms !== undefined) {
    event.watch_duration_ms = details.watch_duration_ms;
  }

  if (details.metadata !== undefined) {
    event.metadata = details.metadata;
  }

  return event;
}

export class InteractionEventBuffer {
  private events: InteractionEvent[] = [];

  add(event: InteractionEvent): void {
    if (this.events.length >= MAX_PENDING_EVENTS) {
      this.events.shift();
    }

    this.events.push(event);
  }

  getPending(limit = 50): InteractionEvent[] {
    return this.events.slice(0, Math.max(0, limit));
  }

  acknowledge(eventIds: string[]): void {
    const acknowledgedIds = new Set(eventIds);

    this.events = this.events.filter(
      event => !acknowledgedIds.has(event.event_id)
    );
  }

  get size(): number {
    return this.events.length;
  }

  clear(): void {
    this.events = [];
  }
}