
import AsyncStorage from '@react-native-async-storage/async-storage';
import type {
  InteractionEvent,
  InteractionEventType,
  InteractionMetadata,
} from '@/services/interaction-tracking';

const MAX_PENDING_EVENTS = 500;
const STORAGE_KEY_PREFIX = '@ataraxia/interaction-queue/';

const ALLOWED_EVENT_TYPES: InteractionEventType[] = [
  'impression',
  'watch',
  'completion',
  'skip',
  'rewatch',
  'like',
  'unlike',
];

const ALLOWED_METADATA_KEYS = [
  'video_duration_ms',
  'watch_percentage',
  'skip_classification',
  'replay_type',
];

function isRecord(value: unknown): value is Record<string, unknown> {
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value)
  );
}

function isUuid(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value)
  );
}

function isValidMetadata(value: unknown): value is InteractionMetadata {
  if (!isRecord(value) || Object.keys(value).length > 20) {
    return false;
  }

  for (const key of Object.keys(value)) {
    if (!ALLOWED_METADATA_KEYS.includes(key)) {
      return false;
    }

    const item = value[key];

    if (
      item !== null &&
      typeof item !== 'string' &&
      typeof item !== 'number' &&
      typeof item !== 'boolean'
    ) {
      return false;
    }

    if (typeof item === 'number' && !Number.isFinite(item)) {
      return false;
    }

    if (key === 'video_duration_ms') {
      if (
        item !== null &&
        (typeof item !== 'number' || item < 0)
      ) {
        return false;
      }
    } else if (key === 'watch_percentage') {
      if (
        item !== null &&
        (
          typeof item !== 'number' ||
          item < 0 ||
          item > 100
        )
      ) {
        return false;
      }
    } else if (key === 'skip_classification') {
      if (
        item !== 'early' &&
        item !== 'mid' &&
        item !== 'late' &&
        item !== 'unknown'
      ) {
        return false;
      }
    } else if (key === 'replay_type' && item !== 'automatic_loop') {
      return false;
    }
  }

  return true;
}

function isValidInteractionEvent(value: unknown): value is InteractionEvent {
  if (!isRecord(value)) {
    return false;
  }

  const allowedEventKeys = [
    'event_id',
    'session_id',
    'video_id',
    'event_type',
    'occurred_at',
    'watch_duration_ms',
    'metadata',
  ];

  if (Object.keys(value).some(key => !allowedEventKeys.includes(key))) {
    return false;
  }

  if (!isUuid(value.event_id) || !isUuid(value.session_id)) {
    return false;
  }

  if (
    typeof value.video_id !== 'string' ||
    value.video_id.length < 1 ||
    value.video_id.length > 128 ||
    !value.video_id.trim() ||
    value.video_id !== value.video_id.trim()
  ) {
    return false;
  }

  if (
    typeof value.event_type !== 'string' ||
    !ALLOWED_EVENT_TYPES.includes(value.event_type as InteractionEventType)
  ) {
    return false;
  }

  if (
    typeof value.occurred_at !== 'string' ||
    !/[Tt].*(Z|[+-]\d{2}:\d{2})$/.test(value.occurred_at) ||
    !Number.isFinite(Date.parse(value.occurred_at))
  ) {
    return false;
  }

  if (
    value.watch_duration_ms !== undefined &&
    (
      typeof value.watch_duration_ms !== 'number' ||
      !Number.isInteger(value.watch_duration_ms) ||
      value.watch_duration_ms < 0
    )
  ) {
    return false;
  }

  if (
    value.metadata !== undefined &&
    !isValidMetadata(value.metadata)
  ) {
    return false;
  }

  return true;
}

export class PersistentInteractionQueue {
  private readonly storageKey: string;
  private events: InteractionEvent[] = [];
  private initialized = false;
  private initialization: Promise<void> | null = null;
  private operation: Promise<void> = Promise.resolve();

  constructor(userId: string) {
    if (!userId.trim()) {
      throw new Error('A user ID is required for the interaction queue.');
    }

    this.storageKey = `${STORAGE_KEY_PREFIX}${userId}`;
  }

  async initialize(): Promise<void> {
    if (this.initialized) {
      return;
    }

    if (!this.initialization) {
      this.initialization = this.enqueue(async () => {
        const stored = await AsyncStorage.getItem(this.storageKey);

        if (stored !== null) {
          let parsed: unknown;

          try {
            parsed = JSON.parse(stored);
          } catch {
            throw new Error(
              'Stored interaction queue contains invalid JSON. The stored data was preserved.'
            );
          }

          if (!Array.isArray(parsed)) {
            throw new Error(
              'Stored interaction queue has an invalid format. The stored data was preserved.'
            );
          }

          for (const event of parsed) {
            if (!isValidInteractionEvent(event)) {
              throw new Error(
                'Stored interaction queue contains an invalid event. The stored data was preserved.'
              );
            }
          }

          this.events = parsed;
        }

        this.initialized = true;
      }).finally(() => {
        this.initialization = null;
      });
    }

    await this.initialization;
  }

  async add(event: InteractionEvent): Promise<void> {
    await this.enqueue(async () => {
      this.ensureInitialized();

      if (!isValidInteractionEvent(event)) {
        throw new Error('Cannot add an invalid interaction event to the queue.');
      }

      const updatedEvents = [...this.events, event];

      if (updatedEvents.length > MAX_PENDING_EVENTS) {
        updatedEvents.shift();
        console.warn(
          '[Ataraxia Interaction] Queue limit reached; oldest event discarded.'
        );
      }

      await this.save(updatedEvents);
    });
  }

  async getPending(limit = 50): Promise<InteractionEvent[]> {
    return this.enqueue(async () => {
      this.ensureInitialized();

      return this.events.slice(0, Math.max(0, limit));
    });
  }

  async getLatestPendingFeedbackStates(
    videoIds: string[]
  ): Promise<Map<string, boolean>> {
    return this.enqueue(async () => {
      this.ensureInitialized();

      const requestedVideoIds = new Set(videoIds);
      const latestStates = new Map<string, boolean>();

      // Queue order is insertion order.
      // Later actions overwrite earlier actions for the same video.
      for (const event of this.events) {
        if (
          requestedVideoIds.has(event.video_id) &&
          (event.event_type === 'like' || event.event_type === 'unlike')
        ) {
          latestStates.set(
            event.video_id,
            event.event_type === 'like'
          );
        }
      }

      return latestStates;
    });
  }

  async acknowledge(eventIds: string[]): Promise<void> {
    if (eventIds.length === 0) {
      return;
    }

    await this.enqueue(async () => {
      this.ensureInitialized();

      const acknowledgedIds = new Set(eventIds);

      const updatedEvents = this.events.filter(
        event => !acknowledgedIds.has(event.event_id)
      );

      await this.save(updatedEvents);
    });
  }

  async getSize(): Promise<number> {
    return this.enqueue(async () => {
      this.ensureInitialized();

      return this.events.length;
    });
  }

  private async save(events: InteractionEvent[]): Promise<void> {
    await AsyncStorage.setItem(this.storageKey, JSON.stringify(events));
    this.events = events;
  }

  private ensureInitialized(): void {
    if (!this.initialized) {
      throw new Error('Interaction queue has not been initialized.');
    }
  }

  private enqueue<T>(task: () => Promise<T>): Promise<T> {
    const result = this.operation.then(task, task);

    this.operation = result.then(
      () => undefined,
      () => undefined
    );

    return result;
  }
}
