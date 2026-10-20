import { memo, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, AppState, Pressable, StyleSheet, Text, View } from 'react-native';
import { useVideoPlayer, VideoView } from 'expo-video';
import { Candidate, FeedClient } from '../services/feed';
import { AuthenticationError } from '../services/auth';

type Props = { item: Candidate; active: boolean; enabled: boolean; client: FeedClient; height: number; onAuthError: () => void };
export const FeedVideo = memo(function FeedVideo({ item, active, enabled, client, height, onAuthError }: Props) {
  const player = useVideoPlayer(null, instance => { instance.loop = true; });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const activeRef = useRef(active);
  activeRef.current = active;
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;
  const repairs = useRef(0);
  const position = useRef(0);
  const visible = useRef(AppState.currentState === 'active');
  const replacements = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    const subscription = player.addListener('statusChange', event => {
      setLoading(event.status === 'loading' || event.status === 'idle');
      if (event.status === 'error' && activeRef.current) {
        if (repairs.current++ < 1) {
          position.current = player.currentTime;
          setRetry(value => value + 1);
        } else setError(true);
      }
    });
    return () => subscription.remove();
  }, [player]);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', state => {
      visible.current = state === 'active';
      if (!visible.current) player.pause();
      else if (activeRef.current) { position.current = player.currentTime; setRetry(value => value + 1); }
    });
    return () => subscription.remove();
  }, [player]);

  useEffect(() => {
    if (active && visible.current && !error) player.play(); else player.pause();
  }, [active, error, player]);

  useEffect(() => {
    if (!active || !loading || error) return;
    const timer = setTimeout(() => {
      if (repairs.current++ < 1) { position.current = player.currentTime; setRetry(value => value + 1); }
      else { setError(true); setLoading(false); }
    }, 25000);
    return () => clearTimeout(timer);
  }, [active, error, loading, player, retry]);

  useEffect(() => {
    if (!enabled) {
      player.pause();
      position.current = player.currentTime;
      replacements.current = replacements.current.catch(() => {}).then(async () => {
        if (!enabledRef.current) await player.replaceAsync(null);
      }).catch(() => {});
      return;
    }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let cancelled = false;
    async function load(force: boolean) {
      setLoading(true); setError(false);
      try {
        const signed = await client.playback(item.video_id, controller.signal, force);
        if (cancelled) return;
        replacements.current = replacements.current.catch(() => {}).then(async () => {
          if (!cancelled) await player.replaceAsync({ uri: signed.url });
        });
        await replacements.current;
        if (cancelled) { player.pause(); return; }
        if (position.current > 0) player.currentTime = position.current;
        if (activeRef.current && visible.current) player.play(); else player.pause();
        timer = setTimeout(() => {
          if (visible.current) { position.current = player.currentTime; void load(true); }
        }, Math.max(1000, signed.expires - Date.now() - 30000));
      } catch (failure) {
        if (cancelled) return;
        if (failure instanceof AuthenticationError) onAuthError();
        else { setError(true); setLoading(false); }
      }
    }
    void load(retry > 0);
    return () => { cancelled = true; controller.abort(); clearTimeout(timer); player.pause(); };
  }, [client, enabled, item.video_id, onAuthError, player, retry]);

  return <View style={[styles.container, { height }]}>
    <VideoView player={player} style={StyleSheet.absoluteFill} contentFit="contain" nativeControls />
    <View pointerEvents="none" style={styles.caption}>
      <Text style={styles.text}>{item.title || item.video_id}</Text>
      <Text style={styles.text}>{item.category_name}</Text>
    </View>
    {active && loading && !error && <ActivityIndicator style={styles.loader} color="#5DE5E0" />}
    {active && error && <View style={styles.loader}>
      <Text style={styles.text}>Could not play this video.</Text>
      <Pressable onPress={() => { repairs.current = 0; setRetry(value => value + 1); }}><Text style={styles.action}>Retry playback</Text></Pressable>
    </View>}
  </View>;
});
const styles = StyleSheet.create({
  container: { backgroundColor: '#071E2A', width: '100%' },
  caption: { position: 'absolute', top: 48, left: 18, right: 18 },
  text: { color: 'white', marginBottom: 8 },
  action: { color: '#5DE5E0', padding: 12 },
  loader: { position: 'absolute', alignSelf: 'center', top: '45%', alignItems: 'center' },
});
