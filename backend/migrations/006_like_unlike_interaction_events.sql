-- Allow Like and Unlike actions to be stored in the existing interaction history.
-- Apply only after explicit approval.

BEGIN;

ALTER TABLE public.interactions
    DROP CONSTRAINT IF EXISTS interactions_valid_event_type;

ALTER TABLE public.interactions
    ADD CONSTRAINT interactions_valid_event_type
    CHECK (
        event_type IN (
            'impression',
            'watch',
            'completion',
            'skip',
            'rewatch',
            'like',
            'unlike'
        )
    );

COMMIT;