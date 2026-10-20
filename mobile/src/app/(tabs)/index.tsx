import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, StyleSheet, Text, View, ViewToken } from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { authenticatedFetch, AuthenticationError } from '@/services/auth';
import { Candidate, FeedClient, FeedError, mergeCandidates } from '@/services/feed';
import { FeedVideo } from '@/components/feed-video';
import { preferenceRevision } from '@/services/performance';

export default function HomeScreen() {
  const client = useMemo(() => new FeedClient(authenticatedFetch), []);
  const [videos, setVideos] = useState<Candidate[]>([]);
  const [total, setTotal] = useState(0);
  const [active, setActive] = useState(0);
  const [height, setHeight] = useState(0);
  const [focused, setFocused] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [expired, setExpired] = useState(false);
  const [retry, setRetry] = useState(0);
  const cursor = useRef<string | null>(null);
  const initialized = useRef(false);
  const redirected = useRef(false);
  const revision = useRef(preferenceRevision());
  const viewability = useRef({ itemVisiblePercentThreshold: 80 });
  const changed = useRef(({ viewableItems }: { viewableItems: ViewToken[] }) => {
    if (viewableItems[0]?.index != null) setActive(viewableItems[0].index);
  });
  const authError = useCallback(() => {
    if (!redirected.current) { redirected.current = true; router.replace('/login'); }
  }, []);
  useFocusEffect(useCallback(() => {
    if (revision.current !== preferenceRevision()) {
      revision.current = preferenceRevision();
      initialized.current = false; cursor.current = null;
      setVideos([]); setActive(0); setExpired(false);
    }
    setFocused(true);
    return () => setFocused(false);
  }, []));

  useEffect(() => {
    if (!focused) return;
    const controller = new AbortController();
    let cancelled = false;
    async function load() {
      setLoading(!initialized.current); setError('');
      const visited = new Set<string>();
      try {
        do {
          const requested = cursor.current;
          if (requested && visited.has(requested)) throw new Error('Invalid feed cursor. Please refresh.');
          if (requested) visited.add(requested);
          const page = await client.page(requested, controller.signal);
          if (cancelled) return;
          if (page.next_cursor && page.next_cursor === requested) throw new Error('Invalid feed cursor. Please refresh.');
          initialized.current = true;
          cursor.current = page.next_cursor;
          setVideos(current => mergeCandidates(current, page.videos));
          setTotal(page.total);
          setLoading(false);
          if (!page.next_cursor) break;
          // Yield so the first page can render before the next network request.
          await new Promise(resolve => setTimeout(resolve, 0));
        } while (!cancelled);
      } catch (failure) {
        if (cancelled) return;
        if (failure instanceof AuthenticationError) authError();
        else {
          setExpired(failure instanceof FeedError && failure.status === 410);
          setError(failure instanceof Error ? failure.message : 'Could not load videos. Please retry.');
        }
      } finally { if (!cancelled) setLoading(false); }
    }
    if (!initialized.current || cursor.current) void load();
    return () => { cancelled = true; controller.abort(); };
  }, [client, focused, retry, authError]);

  function refresh() {
    initialized.current = false; cursor.current = null;
    setVideos([]); setActive(0); setExpired(false); setRetry(value => value + 1);
  }
  const renderItem = useCallback(({ item, index }: { item: Candidate; index: number }) => (
    <FeedVideo item={item} active={focused && index === active} enabled={focused && index >= active && index <= active + 1}
      client={client} height={height} onAuthError={authError} />
  ), [active, authError, client, focused, height]);

  return <View style={styles.container} onLayout={event => setHeight(event.nativeEvent.layout.height)}>
    {loading ? <ActivityIndicator color="#5DE5E0" /> : videos.length > 0 && height > 0 ? <FlatList
      key={height} data={videos} keyExtractor={item => item.video_id} renderItem={renderItem} pagingEnabled
      initialNumToRender={2} maxToRenderPerBatch={2} windowSize={3} showsVerticalScrollIndicator={false}
      getItemLayout={(_, index) => ({ length: height, offset: height * index, index })}
      onViewableItemsChanged={changed.current} viewabilityConfig={viewability.current}
    /> : !error && <View style={styles.message}>
      <Text style={styles.text}>No matching videos. Confirm your interests to try again.</Text>
      <Pressable onPress={() => router.push('/(onboarding)/interests')}><Text style={styles.action}>Choose interests</Text></Pressable>
    </View>}
    {!!error && <View style={styles.banner}>
      <Text style={styles.text}>{error}</Text>
      <Pressable onPress={() => expired ? refresh() : setRetry(value => value + 1)}><Text style={styles.action}>{expired ? 'Refresh feed' : 'Retry loading'}</Text></Pressable>
    </View>}
    {videos.length > 0 && <View pointerEvents="none" style={styles.counter}>
      <Text style={styles.text}>{active + 1} / {total} {videos.length < total ? '(loading more)' : ''}</Text>
    </View>}
  </View>;
}
const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#071E2A', justifyContent: 'center' },
  text: { color: 'white', textAlign: 'center' },
  action: { color: '#5DE5E0', padding: 12, textAlign: 'center' },
  message: { padding: 24 },
  banner: { position: 'absolute', left: 12, right: 12, top: 8, padding: 12, backgroundColor: '#103B49' },
  counter: { position: 'absolute', right: 18, bottom: 70 },
});
