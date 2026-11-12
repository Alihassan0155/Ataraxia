
import { memo, useEffect, useRef, useState } from 'react';
import {ActivityIndicator, AppState, Pressable, Text, View,} from 'react-native';
import { useVideoPlayer, VideoView } from 'expo-video';
import { Candidate, FeedClient } from '@/services/feed';
import { AuthenticationError } from '@/services/auth';
import {InteractionEventDetails, InteractionEventType,} from '@/services/interaction-tracking';
import styles from '@/styles/feed-video.styles';

type Props = {
  item: Candidate;
  active: boolean;
  enabled: boolean;
  client: FeedClient;
  height: number;
  onAuthError: () => void;
  onInteractionEvent?: (
    videoId: string,
    eventType: InteractionEventType,
    details?: InteractionEventDetails
  ) => void;
};

export const FeedVideo = memo(function FeedVideo({ item, active, enabled, client, height, onAuthError, onInteractionEvent,}: Props)
{
  const player = useVideoPlayer(null, instance => {
    instance.loop = true;
    instance.timeUpdateEventInterval = 1;
  });

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [playerReady, setPlayerReady] = useState(player.status === 'readyToPlay');
  const [playing, setPlaying] = useState(true);
  const [feedback, setFeedback] = useState('');
  const [retry, setRetry] = useState(0);
  const [appVisible, setAppVisible] = useState(AppState.currentState === 'active');

  const activeRef = useRef(active);
  const enabledRef = useRef(enabled);
  const playingRef = useRef(playing);
  const visibleRef = useRef(AppState.currentState === 'active');

  const callbackRef = useRef(onInteractionEvent);
  const errorRef = useRef(error);
  const loadingRef = useRef(loading);

  const tapRef = useRef<{
    time: number;
    side: 'left' | 'right';
  } | null>(null);

  const tapTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const feedbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const repairsRef = useRef(0);
  const positionRef = useRef(0);
  const replacementsRef = useRef<Promise<void>>(Promise.resolve());

  const impressionSentRef = useRef(false);
  const completedCycleRef = useRef(false);
  const awaitingLoopRef = useRef(false);

  const lastPlaybackPositionRef = useRef<number | null>(null);
  const lastPlaybackTimeRef = useRef<number | null>(null);
  const accumulatedWatchMsRef = useRef(0);

  activeRef.current = active;
  enabledRef.current = enabled;
  playingRef.current = playing;
  callbackRef.current = onInteractionEvent;
  errorRef.current = error;
  loadingRef.current = loading;

  function reportInteraction(eventType: InteractionEventType, details: InteractionEventDetails = {})
  {
    callbackRef.current?.(item.video_id, eventType, details);
  }

  function getVideoDurationMs(): number | null
  {
    const duration = player.duration;

    if (!Number.isFinite(duration) || duration <= 0)
    {
      return null;
    }

    return Math.round(duration * 1000);
  }

  function resetPlaybackBaseline()
  {
    lastPlaybackPositionRef.current = null;
    lastPlaybackTimeRef.current = null;
  }

  function flushWatchTime()
  {
    const watchDuration = Math.floor(accumulatedWatchMsRef.current);

    accumulatedWatchMsRef.current = 0;

    if (watchDuration > 0)
    {
      reportInteraction('watch', {
        watch_duration_ms: watchDuration,
        metadata: {
          video_duration_ms: getVideoDurationMs(),
        },
      });
    }

    resetPlaybackBaseline();
  }

  // Completion is accepted only from the actual playToEnd event.
  function reportCompletion()
  {
    if (completedCycleRef.current || !activeRef.current || !enabledRef.current || !visibleRef.current ||
      errorRef.current || loadingRef.current || player.status !== 'readyToPlay')
    {
      return;
    }

    flushWatchTime();

    completedCycleRef.current = true;
    awaitingLoopRef.current = true;

    reportInteraction('completion');
  }

  function handlePlaybackTimeUpdate(currentTime: number)
  {
    const canTrack = activeRef.current && enabledRef.current && visibleRef.current && playingRef.current &&
      !errorRef.current && !loadingRef.current && player.playing && player.status === 'readyToPlay';

    if (!canTrack)
    {
      resetPlaybackBaseline();
      return;
    }

    const now = Date.now();

    // A rewatch requires a previously confirmed completion followed by the automatic loop restarting near zero.
    if (awaitingLoopRef.current && currentTime <= 1.5)
    {
      awaitingLoopRef.current = false;
      reportInteraction('rewatch', {metadata: {replay_type: 'automatic_loop',},});

      lastPlaybackPositionRef.current = currentTime;
      lastPlaybackTimeRef.current = now;

      return;
    }

    const previousPosition = lastPlaybackPositionRef.current;
    const previousTime = lastPlaybackTimeRef.current;

    if (previousPosition === null || previousTime === null)
    {
      lastPlaybackPositionRef.current = currentTime;
      lastPlaybackTimeRef.current = now;
      return;
    }

    if (completedCycleRef.current && currentTime > 1.5)
    {
      completedCycleRef.current = false;
    }

    const positionDelta = currentTime - previousPosition;
    const elapsedSeconds = (now - previousTime) / 1000;

    if (positionDelta < -0.5)
    {
      resetPlaybackBaseline();

      lastPlaybackPositionRef.current = currentTime;
      lastPlaybackTimeRef.current = now;

      return;
    }

    if (positionDelta > 0)
    {
      const playbackRate = Math.max(0.1, player.playbackRate);

      const maximumPlausibleProgress = elapsedSeconds * playbackRate + 0.5;

      if (positionDelta <= maximumPlausibleProgress)
      {
        accumulatedWatchMsRef.current += positionDelta * 1000;
      }
    }

    lastPlaybackPositionRef.current = currentTime;
    lastPlaybackTimeRef.current = now;
  }

  useEffect(() => {
    const subscription = AppState.addEventListener('change', state => {
      const visible = state === 'active';

      visibleRef.current = visible;
      setAppVisible(visible);

      if (!visible)
      {
        flushWatchTime();
        player.pause();
      }
      else if (activeRef.current && enabledRef.current)
      {
        positionRef.current = player.currentTime;
        setRetry(value => value + 1);
      }
    });

    return () => subscription.remove();
  }, [player]);

  useEffect(() => {
    if (active && appVisible && playing && !error)
    {
      player.play();
    }
    else
    {
      flushWatchTime();
      player.pause();
    }
  }, [active, appVisible, playing, error, player]);

  useEffect(() => {
    const statusSubscription = player.addListener('statusChange', event => {
      setLoading(event.status === 'loading' || event.status === 'idle');
      setPlayerReady(event.status === 'readyToPlay');

      if (event.status !== 'readyToPlay')
      {
        flushWatchTime();
      }

      if (event.status === 'error' && activeRef.current) {
        if (repairsRef.current++ < 1)
        {
          positionRef.current = player.currentTime;
          setRetry(value => value + 1);
        }
        else
        {
          setError(true);
          setLoading(false);
        }
      }
    });

    const playingSubscription = player.addListener('playingChange', event => {
      if (!event.isPlaying)
      {
        flushWatchTime();
      }
      else
      {
        resetPlaybackBaseline();
      }
    });

    const timeSubscription = player.addListener('timeUpdate', event => {
      handlePlaybackTimeUpdate(event.currentTime);
    });

    const completionSubscription = player.addListener('playToEnd', () => {
      reportCompletion();
    });

    return () => {
      flushWatchTime();

      statusSubscription.remove();
      playingSubscription.remove();
      timeSubscription.remove();
      completionSubscription.remove();
    };
  }, [player]);

  useEffect(() => {
    if (active && enabled && appVisible && !loading && !error && playerReady && !impressionSentRef.current)
    {
      impressionSentRef.current = true;

      reportInteraction('impression', {
        metadata: {
          video_duration_ms: getVideoDurationMs(),
        },
      });
    }
  }, [active, enabled, appVisible, loading, error, playerReady]);

  useEffect(() => {
    if ( !active || !enabled || !appVisible || !playing || loading || error)
    {
      flushWatchTime();
    }
  }, [active, enabled, appVisible, playing, loading, error]);

  useEffect(() => {
    if (!enabled) 
    {
      flushWatchTime();

      player.pause();
      positionRef.current = player.currentTime;

      replacementsRef.current = replacementsRef.current
        .catch(() => {})
        .then(async () => {
          if (!enabledRef.current)
          {
            await player.replaceAsync(null);
          }
        })
        .catch(() => {});

      return;
    }

    const controller = new AbortController();
    let cancelled = false;

    async function loadPlayback(force: boolean)
    {
      setLoading(true);
      setError(false);

      try 
      {
        const signed = await client.playback(item.video_id, controller.signal, force);
        if (cancelled)
        {
          return;
        }

        replacementsRef.current = replacementsRef.current
          .catch(() => {})
          .then(async () => {
            if (!cancelled)
            {
              await player.replaceAsync({ uri: signed.url });
            }
          });

        await replacementsRef.current;

        if (cancelled) {
          return;
        }

        if (positionRef.current > 0) {
          player.currentTime = positionRef.current;
        }

        setLoading(false);

        if (activeRef.current && visibleRef.current && playingRef.current) {
          player.play();
        } 
        else 
        {
          player.pause();
        }

        if (refreshTimerRef.current) {
          clearTimeout(refreshTimerRef.current);
        }

        refreshTimerRef.current = setTimeout(() => {
          if (!cancelled && visibleRef.current)
          {
            flushWatchTime();
            positionRef.current = player.currentTime;
            void loadPlayback(true);
          }
        }, Math.max(1000, signed.expires - Date.now() - 30000));
      }
      catch (failure)
      {
        if (cancelled || (failure instanceof Error && failure.name === 'AbortError'))
        {
          return;
        }

        if (failure instanceof AuthenticationError)
        {
          onAuthError();
        }
        else
        {
          setError(true);
          setLoading(false);
        }
      }
    }

    void loadPlayback(retry > 0);

    return () => {
      cancelled = true;
      controller.abort();

      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }
    };
  }, [client, enabled, item.video_id, onAuthError, player, retry,]);

  useEffect(() => {
    if (!active || !loading || error)
    {
      return;
    }

    const timer = setTimeout(() => {
      if (repairsRef.current++ < 1)
      {
        positionRef.current = player.currentTime;
        setRetry(value => value + 1);
      }
      else
      {
        setError(true);
        setLoading(false);
      }
    }, 25000);

    return () => clearTimeout(timer);
  }, [active, error, loading, player, retry]);

  useEffect(() => {
    return () => {
      flushWatchTime();

      if (tapTimerRef.current) {
        clearTimeout(tapTimerRef.current);
      }

      if (feedbackTimerRef.current) {
        clearTimeout(feedbackTimerRef.current);
      }

      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }
    };
  }, []);

  function showFeedback(message: string) {
    setFeedback(message);

    if (feedbackTimerRef.current) {
      clearTimeout(feedbackTimerRef.current);
    }

    feedbackTimerRef.current = setTimeout(() => {
      setFeedback('');
    }, 650);
  }

  function togglePlayback() 
  {
    setPlaying(current => {
      const next = !current;

      if (next && activeRef.current && visibleRef.current)
      {
        player.play();
      }
      else
      {
        flushWatchTime();
        player.pause();
      }

      showFeedback(next ? 'PLAY' : 'PAUSED');
      return next;
    });
  }

  function seek(seconds: number) 
  {
    if (!activeRef.current) 
    {
      return;
    }

    resetPlaybackBaseline();
    player.seekBy(seconds);
    showFeedback(seconds < 0 ? '−5 seconds' : '+5 seconds');
  }

  function handleTap(side: 'left' | 'right')
  {
    const now = Date.now();
    const previous = tapRef.current;

    if (previous && previous.side === side && now - previous.time < 280)
    {
      if (tapTimerRef.current)
      {
        clearTimeout(tapTimerRef.current);
        tapTimerRef.current = null;
      }

      tapRef.current = null;
      seek(side === 'left' ? -5 : 5);
      return;
    }

    if (tapTimerRef.current)
    {
      clearTimeout(tapTimerRef.current);
    }

    tapRef.current = { time: now, side };

    tapTimerRef.current = setTimeout(() => {
      tapRef.current = null;
      tapTimerRef.current = null;
      togglePlayback();
    }, 280);
  }

  function retryPlayback() {
    repairsRef.current = 0;
    positionRef.current = player.currentTime;
    setRetry(value => value + 1);
  }

  return (
    <View style={[styles.container, { height }]}>
      {enabled ? (<VideoView player={player} style={styles.video} contentFit="cover" nativeControls={false}/>) : null}

      <View pointerEvents="none" style={styles.caption}>
        {item.title ? (<Text style={styles.text}>{item.title}</Text>) : null}
        {item.category_name ? (<Text style={styles.category}>{item.category_name}</Text>) : null}
      </View>

      {active && loading && !error && ( <ActivityIndicator style={styles.loader} color="#5DE5E0" size="large"/>)}

      {active && error && (
        <View style={styles.loader}>
          <Text style={styles.text}>Could not play this video.</Text>
          <Pressable onPress={retryPlayback}>
            <Text style={styles.action}>Retry playback</Text>
          </Pressable>
        </View>
      )}

      {active && feedback !== '' && (
        <View pointerEvents="none" style={styles.feedback}>
          <Text style={styles.feedbackText}>{feedback}</Text>
        </View>
      )}

      {active && !loading && !error && (
        <View style={styles.tapZones} pointerEvents="box-none">
          <Pressable style={styles.tapZone} onPress={() => handleTap('left')}/>
          <Pressable style={styles.tapZone} onPress={() => handleTap('right')}/>
        </View>
      )}
    </View>
  );
});
