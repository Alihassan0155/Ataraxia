
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Animated, FlatList, Pressable, Text, View, ViewToken } from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { authenticatedFetch, AuthenticationError, clearSession } from '@/services/auth';
import { Candidate, FeedClient, FeedError, mergeCandidates } from '@/services/feed';
import { FeedVideo } from '@/components/feed-video';
import { preferenceRevision } from '@/services/performance';
import { createInteractionEvent, createInteractionId, InteractionEventBuffer } from '@/services/interaction-tracking';
import type { InteractionEventDetails, InteractionEventType } from '@/services/interaction-tracking';
import styles from '@/styles/home.styles';


function FeedSkeleton()
{
  const shimmer = useRef(new Animated.Value(0)).current;

  useEffect(() =>
  {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(shimmer, { toValue: 1, duration: 900, useNativeDriver: true }),
        Animated.timing(shimmer, { toValue: 0, duration: 900, useNativeDriver: true }),
      ])
    );

    animation.start();

    return () =>
    {
      animation.stop();
    };
  }, [shimmer]);

  const shimmerOpacity = shimmer.interpolate({
    inputRange: [0, 1],
    outputRange: [0.3, 0.8],
  });

  return (
    <View accessibilityLabel="Loading your video feed" accessibilityRole="progressbar" style={styles.skeletonContainer}>
      <Animated.View style={[styles.skeletonShimmer, { opacity: shimmerOpacity }]} />

      <View style={styles.skeletonActions}>
        {[0, 1, 2, 3].map(item => (
          <Animated.View key={item} style={[styles.skeletonAction, { opacity: shimmerOpacity }]} />
        ))}
      </View>

      <View style={styles.skeletonTextContainer}>
        <Animated.View style={[styles.skeletonTitle, { opacity: shimmerOpacity }]} />
        <Animated.View style={[styles.skeletonLineWide, { opacity: shimmerOpacity }]} />
        <Animated.View style={[styles.skeletonLineShort, { opacity: shimmerOpacity }]} />
      </View>
    </View>
  );
}


export default function HomeScreen()
{
  const client = useMemo(() => new FeedClient(authenticatedFetch), []);

  const [videos, setVideos] = useState<Candidate[]>([]);
  const [total, setTotal] = useState(0);
  const [active, setActive] = useState(0);
  const [height, setHeight] = useState(0);
  const [focused, setFocused] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [expired, setExpired] = useState(false);
  const [retry, setRetry] = useState(0);
  const [profileMenuVisible, setProfileMenuVisible] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);


  const videosRef = useRef<Candidate[]>([]);
  const cursorRef = useRef<string | null>(null);
  const initializedRef = useRef(false);
  const loadingMoreRef = useRef(false);
  const redirectedRef = useRef(false);
  const seenCursorsRef = useRef<Set<string>>(new Set());
  const revisionRef = useRef(preferenceRevision());

  const sessionIdRef = useRef<string | null>(null);

  if (sessionIdRef.current === null)
  {
    sessionIdRef.current = createInteractionId();
  }

  const eventBufferRef = useRef<InteractionEventBuffer | null>(null);

  if (eventBufferRef.current === null)
  {
    eventBufferRef.current = new InteractionEventBuffer();
  }

  const impressedVideosRef = useRef<Set<string>>(new Set());
  const completedVideosRef = useRef<Set<string>>(new Set());
  const previousActiveVideoIdRef = useRef<string | null>(null);


  const resetInteractionDetection = useCallback(() =>
  {
    impressedVideosRef.current.clear();
    completedVideosRef.current.clear();
    previousActiveVideoIdRef.current = null;
  }, []);


  const handleInteractionEvent = useCallback((
    videoId: string,
    eventType: InteractionEventType,
    details: InteractionEventDetails = {}
  ) =>
  {
    const sessionId = sessionIdRef.current;
    const eventBuffer = eventBufferRef.current;

    if (!sessionId || !eventBuffer)
    {
      return;
    }

    const event = createInteractionEvent(sessionId, videoId, eventType, details);
    eventBuffer.add(event);

    console.log('[Ataraxia Interaction]', event.event_type, event.video_id, event.watch_duration_ms ?? '');

    if (eventType === 'impression')
    {
      impressedVideosRef.current.add(videoId);
    }

    if (eventType === 'completion')
    {
      completedVideosRef.current.add(videoId);
    }
  }, []);


  const authError = useCallback(() =>
  {
    if (!redirectedRef.current)
    {
      redirectedRef.current = true;
      router.replace('/login');
    }
  }, []);


  const handleLogout = useCallback(async () =>
  {
    if (loggingOut)
    {
      return;
    }

    setLoggingOut(true);

    try
    {
      await clearSession();
      setProfileMenuVisible(false);
      router.replace('/login');
    }
    catch (error)
    {
      console.error('Logout failed:', error);
      setError('Could not log out. Please try again.');
    }
    finally
    {
      setLoggingOut(false);
    }
  }, [loggingOut]);


  useFocusEffect(
    useCallback(() =>
    {
      const currentRevision = preferenceRevision();

      if (revisionRef.current !== currentRevision)
      {
        revisionRef.current = currentRevision;

        videosRef.current = [];
        cursorRef.current = null;
        initializedRef.current = false;
        loadingMoreRef.current = false;
        seenCursorsRef.current.clear();

        resetInteractionDetection();

        setVideos([]);
        setActive(0);
        setTotal(0);
        setError('');
        setExpired(false);
        setLoading(true);
        setRetry(value => value + 1);
      }

      setFocused(true);

      return () =>
      {
        setFocused(false);

        // Do not count leaving the feed screen as a skip.
        previousActiveVideoIdRef.current = null;
      };
    }, [resetInteractionDetection])
  );


  const viewabilityConfig = useRef({itemVisiblePercentThreshold: 80,});

  const onViewableItemsChanged = useRef(
    ({ viewableItems }: { viewableItems: ViewToken[] }) =>
    {
      const visibleItem = viewableItems.find(item => item.isViewable && item.index !== null);

      if (visibleItem?.index !== null && visibleItem?.index !== undefined)
      {
        setActive(visibleItem.index);
      }
    }
  );

  useEffect(() =>
  {
    if (!focused || videos.length === 0)
    {
      previousActiveVideoIdRef.current = null;
      return;
    }

    const currentVideo = videos[active];

    if (!currentVideo)
    {
      return;
    }

    const currentVideoId = currentVideo.video_id;
    const previousVideoId = previousActiveVideoIdRef.current;

    if ( previousVideoId !== null && previousVideoId !== currentVideoId && impressedVideosRef.current.has(previousVideoId) &&
      !completedVideosRef.current.has(previousVideoId))
    {
      handleInteractionEvent(previousVideoId, 'skip');
    }

    previousActiveVideoIdRef.current = currentVideoId;
  }, [active, focused, videos, handleInteractionEvent]);


  useEffect(() =>
  {
    if (!focused || initializedRef.current)
    {
      return;
    }

    const controller = new AbortController();
    let cancelled = false;

    async function loadInitialFeed()
    {
      setLoading(true);
      setError('');

      try
      {
        const page = await client.page(null, controller.signal);

        if (cancelled)
        {
          return;
        }

        if (page.videos.length === 0)
        {
          throw new Error('No videos are available for your feed.');
        }

        const initialVideos = mergeCandidates([], page.videos);

        videosRef.current = initialVideos;
        cursorRef.current = page.next_cursor;
        initializedRef.current = true;
        seenCursorsRef.current.clear();

        setVideos(initialVideos);
        setTotal(page.total);
        setActive(0);
        setExpired(false);
      }
      catch (failure)
      {
        if (cancelled)
        {
          return;
        }

        if (failure instanceof AuthenticationError)
        {
          authError();
        }
        else
        {
          setExpired(failure instanceof FeedError && failure.status === 410);
          setError(failure instanceof Error ? failure.message : 'Could not load videos. Please retry.');
        }
      }
      finally
      {
        if (!cancelled)
        {
          setLoading(false);
        }
      }
    }

    void loadInitialFeed();

    return () =>
    {
      cancelled = true;
      controller.abort();
    };
  }, [client, focused, retry, authError]);


  const loadMoreVideos = useCallback(async () =>
  {
    if (loadingMoreRef.current || !cursorRef.current || videosRef.current.length >= 50)
    {
      return;
    }

    const requestedCursor = cursorRef.current;

    if (seenCursorsRef.current.has(requestedCursor))
    {
      setError('The feed did not advance. Please refresh.');
      return;
    }

    loadingMoreRef.current = true;
    setLoadingMore(true);

    try
    {
      const page = await client.page(requestedCursor);

      if ( page.next_cursor === requestedCursor || (page.next_cursor !== null && seenCursorsRef.current.has(page.next_cursor)))
      {
        throw new Error('The feed did not advance. Please refresh.');
      }

      seenCursorsRef.current.add(requestedCursor);

      const merged = mergeCandidates(videosRef.current, page.videos);

      videosRef.current = merged;
      cursorRef.current = page.next_cursor;

      setVideos(merged);
      setTotal(page.total);
      setError('');
      setExpired(false);
    }
    catch (failure)
    {
      if (failure instanceof AuthenticationError)
      {
        authError();
      }
      else
      {
        setExpired(failure instanceof FeedError && failure.status === 410);
        setError(failure instanceof Error ? failure.message : 'Could not load more videos.');
      }
    }
    finally
    {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [client, authError]);


  useEffect(() =>
  {
    if (focused && videos.length > 0 && active >= videos.length - 2)
    {
      void loadMoreVideos();
    }
  }, [focused, active, videos.length, loadMoreVideos]);


  const refreshFeed = useCallback(() =>
  {
    videosRef.current = [];
    cursorRef.current = null;
    initializedRef.current = false;
    loadingMoreRef.current = false;
    seenCursorsRef.current.clear();

    resetInteractionDetection();

    setVideos([]);
    setActive(0);
    setTotal(0);
    setExpired(false);
    setError('');
    setLoading(true);
    setRetry(value => value + 1);
  }, [resetInteractionDetection]);


  const renderItem = useCallback(
    ({ item, index }: { item: Candidate; index: number }) => (
      <FeedVideo item={item} active={focused && index === active} enabled={focused && index >= active && index <= active + 1}
        client={client} height={height} onAuthError={authError} onInteractionEvent={handleInteractionEvent}/>
    ),
    [active, authError, client, focused, height, handleInteractionEvent]
  );


  return (
    <View style={styles.container} onLayout={event =>
      {
        setHeight(event.nativeEvent.layout.height);
      }}
    >
      {loading && videos.length === 0 ? (
        <FeedSkeleton />
      ) : videos.length > 0 && height > 0 ? (
        <FlatList key={height} data={videos} keyExtractor={item => item.video_id} renderItem={renderItem}
          pagingEnabled snapToInterval={height} snapToAlignment="start" decelerationRate="fast"
          disableIntervalMomentum initialNumToRender={2}  maxToRenderPerBatch={2} windowSize={3}
          showsVerticalScrollIndicator={false} getItemLayout={(_, index) => ({
            length: height,
            offset: height * index,
            index,
          })}
          onViewableItemsChanged={onViewableItemsChanged.current}
          viewabilityConfig={viewabilityConfig.current}
          onEndReached={() =>
          {
            void loadMoreVideos();
          }}
          onEndReachedThreshold={0.5}
          extraData={{ active, focused, height }}
        />
      ) : (
        <View style={styles.emptyContainer}>
          <Text style={styles.emptyText}>
            {error || 'No videos are available.'}
          </Text>

          <Pressable onPress={() => router.push('/(onboarding)/interests')}>
            <Text style={styles.chooseInterestsText}>
              Choose interests
            </Text>
          </Pressable>

          {!!error && (
            <Pressable onPress={refreshFeed}>
              <Text style={styles.retryText}>
                Retry loading
              </Text>
            </Pressable>
          )}
        </View>
      )}


      {videos.length > 0 && (
        <View pointerEvents="none" style={styles.feedCounter}>
          <Text style={styles.feedCounterText}>
            {active + 1} / {total || videos.length}
          </Text>
        </View>
      )}


      {loadingMore && (<ActivityIndicator color="#5DE5E0" style={styles.loadingMoreIndicator} />)}

      {!!error && videos.length > 0 && (
        <View style={styles.errorBanner}>
          <Text style={styles.errorText}>
            {error}
          </Text>

          <Text
            onPress={() =>
            {
              if (expired)
              {
                refreshFeed();
              }
              else
              {
                void loadMoreVideos();
              }
            }}
            style={styles.errorActionText}> {expired ? 'Refresh feed' : 'Retry loading'}
          </Text>
        </View>
      )}


      <View pointerEvents="none" style={styles.brand}>
        <Text style={styles.brandText}>
          Ataraxia
        </Text>
      </View>


      <View pointerEvents="box-none" style={styles.profileMenuContainer}>
        <Pressable accessibilityRole="button" accessibilityLabel="Open profile menu"
          onPress={() => setProfileMenuVisible(visible => !visible)} style={styles.profileButton}>
          <Text style={styles.profileButtonText}>
            ♙
          </Text>
        </Pressable>

        {profileMenuVisible && (
          <View style={styles.profileDropdown}>
            <Pressable disabled={loggingOut} onPress={() => void handleLogout()} style={styles.logoutButton}>
              <Text style={styles.logoutText}>
                {loggingOut ? 'Logging out...' : 'Log out'}
              </Text>
            </Pressable>
          </View>
        )}
      </View>
    </View>
  );
}
