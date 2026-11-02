import { memo, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  AppState,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useVideoPlayer, VideoView } from 'expo-video';
import { Candidate, FeedClient } from '@/services/feed';

type Props = {
  item: Candidate;
  active: boolean;
  enabled: boolean;
  client: FeedClient;
  height: number;
};

export const FeedVideo = memo(function FeedVideo({
  item,
  active,
  enabled,
  client,
  height,
}: Props) {
  const player = useVideoPlayer(null, (instance) => {
    instance.loop = true;
  });

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [playing, setPlaying] = useState(true);
  const [feedback, setFeedback] = useState('');
  const [appVisible, setAppVisible] = useState(
    AppState.currentState === 'active'
  );

  const activeRef = useRef(active);
  const enabledRef = useRef(enabled);
  const tapRef = useRef<{
    time: number;
    side: 'left' | 'right';
  } | null>(null);
  const tapTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const feedbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestRef = useRef(0);

  activeRef.current = active;
  enabledRef.current = enabled;

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => {
      setAppVisible(state === 'active');
    });

    return () => subscription.remove();
  }, []);

  useEffect(() => {
    if (active && appVisible && playing && !error) {
      player.play();
    } else {
      player.pause();
    }
  }, [active, appVisible, playing, error, player]);

  useEffect(() => {
    if (!enabled) {
      player.pause();
      return;
    }

    const controller = new AbortController();
    const requestId = ++requestRef.current;
    let cancelled = false;

    async function loadPlayback() {
      setLoading(true);
      setError(false);

      try {
        const playback = await client.playback(
          item.video_id,
          controller.signal
        );

        if (cancelled || requestId !== requestRef.current) {
          return;
        }

        await player.replaceAsync({ uri: playback.url });

        if (cancelled || requestId !== requestRef.current) {
          player.pause();
          return;
        }

        setLoading(false);

        if (activeRef.current && appVisible && playing) {
          player.play();
        } else {
          player.pause();
        }
      } catch (failure) {
        if (
          cancelled ||
          (failure instanceof Error && failure.name === 'AbortError')
        ) {
          return;
        }

        setError(true);
        setLoading(false);
      }
    }

    void loadPlayback();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [client, enabled, item.video_id, player]);

  useEffect(() => {
    return () => {
      if (tapTimerRef.current) {
        clearTimeout(tapTimerRef.current);
      }

      if (feedbackTimerRef.current) {
        clearTimeout(feedbackTimerRef.current);
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

  function togglePlayback() {
    setPlaying((current) => {
      const next = !current;

      if (next && activeRef.current && appVisible) {
        player.play();
      } else {
        player.pause();
      }

      showFeedback(next ? 'PLAY' : 'PAUSED');
      return next;
    });
  }

  function seek(seconds: number) {
    if (!activeRef.current) {
      return;
    }

    player.seekBy(seconds);
    showFeedback(seconds < 0 ? '−5 seconds' : '+5 seconds');
  }

  function handleTap(side: 'left' | 'right') {
    const now = Date.now();
    const previous = tapRef.current;

    if (
      previous &&
      previous.side === side &&
      now - previous.time < 280
    ) {
      if (tapTimerRef.current) {
        clearTimeout(tapTimerRef.current);
        tapTimerRef.current = null;
      }

      tapRef.current = null;
      seek(side === 'left' ? -5 : 5);
      return;
    }

    if (tapTimerRef.current) {
      clearTimeout(tapTimerRef.current);
    }

    tapRef.current = { time: now, side };

    tapTimerRef.current = setTimeout(() => {
      tapRef.current = null;
      tapTimerRef.current = null;
      togglePlayback();
    }, 280);
  }

  return (
    <View style={[styles.container, { height }]}>
      {enabled ? (
        <VideoView
          player={player}
          style={StyleSheet.absoluteFill}
          contentFit="cover"
          nativeControls={false}
        />
      ) : null}

      <View pointerEvents="none" style={styles.caption}>
        {item.title ? <Text style={styles.text}>{item.title}</Text> : null}
        {item.category_name ? <Text style={styles.category}>{item.category_name}</Text> : null}
      </View>

      {active && loading && (
        <ActivityIndicator
          style={styles.loader}
          color="#5DE5E0"
          size="large"
        />
      )}

      {active && error && (
        <View style={styles.loader}>
          <Text style={styles.text}>Could not play this video.</Text>
        </View>
      )}

      {active && feedback !== '' && (
        <View pointerEvents="none" style={styles.feedback}>
          <Text style={styles.feedbackText}>{feedback}</Text>
        </View>
      )}

      {active && !loading && !error && (
        <View style={styles.tapZones} pointerEvents="box-none">
          <Pressable
            style={styles.tapZone}
            onPress={() => handleTap('left')}
          />
          <Pressable
            style={styles.tapZone}
            onPress={() => handleTap('right')}
          />
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
    ...StyleSheet.absoluteFill,
    flexDirection: 'row',
  },
  tapZone: {
    flex: 1,
  },
});






