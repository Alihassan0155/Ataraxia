
import { memo, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, AppState, Pressable, StyleSheet, Text, View,} from 'react-native';
import { useVideoPlayer, VideoView } from 'expo-video';
import { Candidate, FeedClient } from '@/services/feed';
import { AuthenticationError } from '@/services/auth';

type Props = {
  item: Candidate;
  active: boolean;
  enabled: boolean;
  client: FeedClient;
  height: number;
  onAuthError: () => void;
};

export const FeedVideo = memo(function FeedVideo({item, active, enabled, client, height, onAuthError,}: Props) 
{
  const player = useVideoPlayer(null, instance => {
    instance.loop = true;
  });

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [playing, setPlaying] = useState(true);
  const [feedback, setFeedback] = useState('');
  const [retry, setRetry] = useState(0);
  const [appVisible, setAppVisible] = useState(
    AppState.currentState === 'active'
  );

  const activeRef = useRef(active);
  const enabledRef = useRef(enabled);
  const playingRef = useRef(playing);
  const visibleRef = useRef(AppState.currentState === 'active');

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

  activeRef.current = active;
  enabledRef.current = enabled;
  playingRef.current = playing;

  useEffect(() => {
    const subscription = AppState.addEventListener('change', state => {
      const visible = state === 'active';

      visibleRef.current = visible;
      setAppVisible(visible);

      if (!visible) 
      {
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
      player.pause();
    }
  }, [active, appVisible, playing, error, player]);

  useEffect(() => {
    const subscription = player.addListener('statusChange', event => {
      setLoading(event.status === 'loading' || event.status === 'idle');

      if (event.status === 'error' && activeRef.current) 
      {
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

    return () => subscription.remove();
  }, [player]);

  useEffect(() => {
    if (!enabled) 
    {
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
        const signed = await client.playback( item.video_id, controller.signal, force);

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

        if (cancelled) 
        {
          return;
        }

        if (positionRef.current > 0) 
        {
          player.currentTime = positionRef.current;
        }

        setLoading(false);

        if (activeRef.current && visibleRef.current && playingRef.current) 
        {
          player.play();
        } 
        else 
        {
          player.pause();
        }

        if (refreshTimerRef.current) 
        {
          clearTimeout(refreshTimerRef.current);
        }

        refreshTimerRef.current = setTimeout(() => {
          if (!cancelled && visibleRef.current) 
          {
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

      if (refreshTimerRef.current) 
      {
        clearTimeout(refreshTimerRef.current);
      }
    };
  }, [client, enabled, item.video_id, onAuthError, player, retry]);

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
      if (tapTimerRef.current) 
      {
        clearTimeout(tapTimerRef.current);
      }

      if (feedbackTimerRef.current) 
      {
        clearTimeout(feedbackTimerRef.current);
      }

      if (refreshTimerRef.current) 
      {
        clearTimeout(refreshTimerRef.current);
      }
    };
  }, []);

  function showFeedback(message: string) 
  {
    setFeedback(message);

    if (feedbackTimerRef.current) 
    {
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

  function retryPlayback() 
  {
    repairsRef.current = 0;
    positionRef.current = player.currentTime;
    setRetry(value => value + 1);
  }

  return (
    <View style={[styles.container, { height }]}>
      {enabled ? (
        <VideoView player={player} style={styles.video} contentFit="cover" nativeControls={false}/>
      ) : null}

      <View pointerEvents="none" style={styles.caption}>
        {item.title ? ( <Text style={styles.text}>{item.title}</Text> ) : null}

        {item.category_name ? ( <Text style={styles.category}>{item.category_name}</Text> ) : null}
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

const styles = StyleSheet.create({
  container: {
    width: '100%',
    backgroundColor: '#071E2A',
    overflow: 'hidden',
  },
  video: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
  },
  caption: {
    position: 'absolute',
    bottom: 34,
    left: 20,
    right: 76,
  },
  category: {
    color: '#D3E4E8',
    fontSize: 12,
    marginTop: 2,
  },
  text: {
    color: '#FFFFFF',
    fontSize: 13,
    marginBottom: 6,
  },
  action: {
    color: '#5DE5E0',
    padding: 12,
  },
  loader: {
    position: 'absolute',
    alignSelf: 'center',
    top: '45%',
    alignItems: 'center',
  },
  feedback: {
    position: 'absolute',
    alignSelf: 'center',
    top: '45%',
    minWidth: 100,
    minHeight: 76,
    paddingHorizontal: 20,
    borderRadius: 40,
    backgroundColor: '#00000099',
    alignItems: 'center',
    justifyContent: 'center',
  },
  feedbackText: {
    color: '#FFFFFF',
    fontSize: 18,
    fontWeight: 'bold',
  },
  tapZones: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    flexDirection: 'row',
  },
  tapZone: {
    flex: 1,
  },
});
