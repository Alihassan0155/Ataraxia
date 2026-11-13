
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Animated, FlatList, Pressable, Text, View, ViewToken } from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import { authenticatedFetch, AuthenticationError, clearSession, getCurrentUser } from '@/services/auth';
import { Candidate, FeedClient, FeedError, mergeCandidates } from '@/services/feed';
import { FeedVideo } from '@/components/feed-video';
import { preferenceRevision } from '@/services/performance';
import { createInteractionEvent, createInteractionId } from '@/services/interaction-tracking';
import type { InteractionEventDetails, InteractionEventType } from '@/services/interaction-tracking';
import { PersistentInteractionQueue } from '@/services/interaction-queue';
import {
  closeInteractionSession,
  flushPendingInteractions,
  registerInteractionSession,
} from '@/services/interaction-uploader';
import {
  getFeedbackStates,
} from '@/services/feedback';
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
  const [trackingRetry, setTrackingRetry] = useState(0);
  const [trackingReady, setTrackingReady] = useState(false);
  const [profileMenuVisible, setProfileMenuVisible] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [likedByVideo, setLikedByVideo] = useState<Record<string, boolean>>({});



  const videosRef = useRef<Candidate[]>([]);
  const cursorRef = useRef<string | null>(null);
  const initializedRef = useRef(false);
  const loadingMoreRef = useRef(false);
  const redirectedRef = useRef(false);
  const seenCursorsRef = useRef<Set<string>>(new Set());
  const revisionRef = useRef(preferenceRevision());

  const sessionIdRef = useRef<string | null>(null);
  const interactionQueueRef = useRef<PersistentInteractionQueue | null>(null);
  const flushingInteractionsRef = useRef<Promise<number> | null>(null);

  const impressedVideosRef = useRef<Set<string>>(new Set());
  const completedVideosRef = useRef<Set<string>>(new Set());
  const skippedVideosRef = useRef<Set<string>>(new Set());
  const previousActiveVideoIdRef = useRef<string | null>(null);
  const feedbackPendingRef = useRef<Set<string>>(new Set());
  const feedbackRevisionRef = useRef<Map<string, number>>(new Map());

  const playbackStatsRef = useRef<Map<string, {
    videoDurationMs: number | null;
    watchDurationMs: number;
  }>>(new Map());


  const authError = useCallback(() =>
  {
    if (!redirectedRef.current)
    {
      redirectedRef.current = true;
      router.replace('/login');
    }
  }, []);


  const flushInteractions = useCallback(async () =>
  {
    const queue = interactionQueueRef.current;

    if (!queue)
    {
      return 0;
    }

    // Reuse an upload that is already in progress.
    if (flushingInteractionsRef.current)
    {
      return flushingInteractionsRef.current;
    }

    const flushPromise = flushPendingInteractions(queue);

    flushingInteractionsRef.current = flushPromise;

    try
    {
      return await flushPromise;
    }
    catch (failure)
    {
      if (failure instanceof AuthenticationError)
      {
        authError();
      }

      throw failure;
    }

    finally
    {
      if (flushingInteractionsRef.current === flushPromise)
      {
        flushingInteractionsRef.current = null;
      }
    }
  }, [authError]);


  const resetInteractionDetection = useCallback(() =>
  {
    impressedVideosRef.current.clear();
    completedVideosRef.current.clear();
    skippedVideosRef.current.clear();
    previousActiveVideoIdRef.current = null;
    playbackStatsRef.current.clear();
  }, []);


  // Initialize the authenticated user's persistent interaction queue.
  useEffect(() =>
  {
    let cancelled = false;

    async function initializeTracking()
    {
      setTrackingReady(false);
      setLoading(true);
      setError('');

      try
      {
        const user = await getCurrentUser();

        if (!user)
        {
          if (!cancelled)
          {
            authError();
          }

          return;
        }

        const queue = new PersistentInteractionQueue(user.id);

        await queue.initialize();

        if (cancelled)
        {
          return;
        }

        interactionQueueRef.current = queue;
        sessionIdRef.current = createInteractionId();

        setTrackingReady(true);

        // Retry events left over from previous app sessions.
        void flushInteractions().catch(failure =>
        {
          console.warn('[Ataraxia Interaction] Startup flush failed:', failure);
        });
      }
      catch (failure)
      {
        if (!cancelled)
        {
          console.error('[Ataraxia Interaction] Initialization failed:', failure);
          setError('Could not initialize interaction tracking. Please retry.');
          setLoading(false);
        }
      }
    }

    void initializeTracking();

    return () =>
    {
      cancelled = true;
    };
  }, [authError, flushInteractions, trackingRetry]);


  const handleInteractionEvent = useCallback(async(
    videoId: string,
    eventType: InteractionEventType,
    details: InteractionEventDetails = {}
  ): Promise<boolean> =>
  {
    const sessionId = sessionIdRef.current;
    const queue = interactionQueueRef.current;

    if (!sessionId || !queue)
    {
      console.warn(
        '[Ataraxia Interaction] Queue is not ready:',
        eventType,
        videoId
      );

      return false;
    }

    const isFeedbackEvent =
      eventType === 'like' || eventType === 'unlike';

    // Like/Unlike actions must not affect playback-duration statistics.
    if (!isFeedbackEvent)
    {
      let playbackStats = playbackStatsRef.current.get(videoId);

      if (!playbackStats)
      {
        playbackStats = {
          videoDurationMs: null,
          watchDurationMs: 0,
        };

        playbackStatsRef.current.set(videoId, playbackStats);
      }

      if (typeof details.metadata?.video_duration_ms === 'number')
      {
        playbackStats.videoDurationMs = details.metadata.video_duration_ms;
      }

      if (eventType === 'watch' && details.watch_duration_ms !== undefined)
      {
        playbackStats.watchDurationMs += details.watch_duration_ms;
      }
    }

    const event = createInteractionEvent(sessionId, videoId, eventType, details);

    console.log(
      '[Ataraxia Interaction]',
      event.event_type,
      event.video_id,
      event.watch_duration_ms ?? '',
      event.metadata ?? {}
    );

    if (eventType === 'impression')
    {
      impressedVideosRef.current.add(videoId);
    }

    if (eventType === 'completion')
    {
      completedVideosRef.current.add(videoId);
    }

    // Local persistence is the boundary for optimistic UI success.
    try
    {
      await queue.add(event);

      console.log(
        '[Ataraxia Interaction] Event persisted:',
        event.event_type,
        event.event_id
      );
    }
    catch (failure)
    {
      console.error(
        '[Ataraxia Interaction] Could not persist event locally:',
        event.event_type,
        event.event_id,
        failure
      );

      return false;
    }

    // Upload is separate. Feedback must never wait for the network.
    try
    {
      const pendingCount = await queue.getSize();

      if (isFeedbackEvent)
      {
        void flushInteractions().catch(failure =>
        {
          console.warn(
            '[Ataraxia Interaction] Feedback upload deferred; event remains queued:',
            event.event_type,
            event.event_id,
            failure
          );
        });
      }
      else if (
        pendingCount >= 10 ||
        eventType === 'completion' ||
        eventType === 'rewatch'
      )
      {
        await flushInteractions();
      }
    }
    catch (failure)
    {
      console.warn(
        '[Ataraxia Interaction] Upload deferred; event remains queued:',
        event.event_type,
        event.event_id,
        failure
      );
    }

    return true;
  }, [flushInteractions]);


  const loadFeedbackForVideos = useCallback(async (
    videoIds: string[],
    signal?: AbortSignal
  ) =>
  {
    if (videoIds.length === 0 || signal?.aborted)
    {
      return;
    }

    // Remember the revision before fetching so an older response cannot
    // overwrite a Like/Unlike action performed while the request is running.
    const requestedRevisions = new Map<string, number>();

    for (const videoId of videoIds)
    {
      requestedRevisions.set(
        videoId,
        feedbackRevisionRef.current.get(videoId) ?? 0
      );
    }

    try
    {
      // Snapshot queued actions before the server request.
      // This also covers an acknowledgement during the server request.
      const queue = interactionQueueRef.current;

      const pendingFeedbackStates = queue
        ? await queue.getLatestPendingFeedbackStates(videoIds)
        : new Map<string, boolean>();

      const states = await getFeedbackStates(videoIds, signal);

      if (signal?.aborted)
      {
        return;
      }

      setLikedByVideo(current =>
      {
        const next = { ...current };

        for (const state of states)
        {
          const pendingIsLiked =
            pendingFeedbackStates.get(state.video_id);

          // Pending local actions take precedence over server state.
          if (pendingIsLiked !== undefined)
          {
            next[state.video_id] = pendingIsLiked;
            continue;
          }

          const currentRevision =
            feedbackRevisionRef.current.get(state.video_id) ?? 0;

          const requestedRevision =
            requestedRevisions.get(state.video_id) ?? 0;

          if (
            !feedbackPendingRef.current.has(state.video_id) &&
            currentRevision === requestedRevision
          )
          {
            next[state.video_id] = state.is_liked;
          }
        }

        return next;
      });
    }
    catch (failure)
    {
      if (
        signal?.aborted ||
        (failure instanceof Error && failure.name === 'AbortError')
      )
      {
        return;
      }

      if (failure instanceof AuthenticationError)
      {
        authError();
      }
      else
      {
        console.warn('[Ataraxia Feedback] Could not load saved feedback:', failure);
      }
    }
  }, [authError]);

  const handleToggleLike = useCallback(async (
    videoId: string,
    nextIsLiked: boolean
  ): Promise<void> =>
  {
    const previousIsLiked = likedByVideo[videoId] ?? false;

    const nextRevision =
      (feedbackRevisionRef.current.get(videoId) ?? 0) + 1;

    feedbackRevisionRef.current.set(videoId, nextRevision);

    // Keep the loading guard for server-state reconciliation only.
    // It no longer blocks another Like/Unlike tap.
    feedbackPendingRef.current.add(videoId);

    // Update the heart immediately.
    setLikedByVideo(current => ({
      ...current,
      [videoId]: nextIsLiked,
    }));

    try
    {
      const persisted = await handleInteractionEvent(
        videoId,
        nextIsLiked ? 'like' : 'unlike'
      );

      if (
        !persisted &&
        feedbackRevisionRef.current.get(videoId) === nextRevision
      )
      {
        // An older failed action must not undo a newer tap.
        setLikedByVideo(current => ({
          ...current,
          [videoId]: previousIsLiked,
        }));

        console.warn(
          '[Ataraxia Feedback] Like action could not be saved to the local queue:',
          videoId
        );
      }
    }
    catch (failure)
    {
      if (feedbackRevisionRef.current.get(videoId) === nextRevision)
      {
        setLikedByVideo(current => ({
          ...current,
          [videoId]: previousIsLiked,
        }));
      }

      console.error('[Ataraxia Feedback] Like action failed:', failure);
    }
    finally
    {
      // Only the latest operation may clear the pending reconciliation guard.
      if (feedbackRevisionRef.current.get(videoId) === nextRevision)
      {
        feedbackPendingRef.current.delete(videoId);
      }
    }
  }, [handleInteractionEvent, likedByVideo]);

  const handleLogout = useCallback(async () =>
  {
    if (loggingOut)
    {
      return;
    }

    setLoggingOut(true);

    try
    {
      const queue = interactionQueueRef.current;
      const sessionId = sessionIdRef.current;

      if (queue)
      {
        try
        {
          await flushInteractions();
        }
        catch (failure)
        {
          console.warn('[Ataraxia Interaction] Logout flush failed:', failure);
        }
      }

      // Close the session even if some events remain queued.
      // The backend permits delayed uploads for ended sessions.
      if (sessionId)
      {
        try
        {
          await registerInteractionSession(sessionId);
          await closeInteractionSession(sessionId);
        }
        catch (failure)
        {
          console.warn('[Ataraxia Interaction] Session close failed:', failure);
        }
      }

      await clearSession();

      setProfileMenuVisible(false);
      router.replace('/login');
    }
    catch (failure)
    {
      console.error('Logout failed:', failure);
      setError('Could not log out. Please try again.');
    }
    finally
    {
      setLoggingOut(false);
    }
  }, [loggingOut, flushInteractions]);


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


  const viewabilityConfig = useRef({ itemVisiblePercentThreshold: 80 });

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
    if (!focused || !trackingReady || videos.length === 0)
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

    if (
      previousVideoId !== null &&
      previousVideoId !== currentVideoId &&
      impressedVideosRef.current.has(previousVideoId) &&
      !completedVideosRef.current.has(previousVideoId) &&
      !skippedVideosRef.current.has(previousVideoId)
    )
    {
      const playbackStats = playbackStatsRef.current.get(previousVideoId);

      const videoDurationMs = playbackStats?.videoDurationMs ?? null;
      const watchDurationMs = playbackStats?.watchDurationMs ?? 0;

      let watchPercentage: number | null = null;
      let skipClassification = 'unknown';

      if (videoDurationMs !== null && videoDurationMs > 0)
      {
        watchPercentage = Math.min(
          100,
          (watchDurationMs / videoDurationMs) * 100
        );

        if (watchPercentage < 25)
        {
          skipClassification = 'early';
        }
        else if (watchPercentage <= 75)
        {
          skipClassification = 'mid';
        }
        else
        {
          skipClassification = 'late';
        }
      }

      skippedVideosRef.current.add(previousVideoId);

      handleInteractionEvent(previousVideoId, 'skip', {
        watch_duration_ms: watchDurationMs,
        metadata: {
          video_duration_ms: videoDurationMs,
          watch_percentage: watchPercentage,
          skip_classification: skipClassification,
        },
      });
    }

    previousActiveVideoIdRef.current = currentVideoId;
  }, [active, focused, trackingReady, videos, handleInteractionEvent]);


  // Load the initial feed only after persistent tracking is ready.
  useEffect(() =>
  {
    if (!focused || !trackingReady || initializedRef.current)
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

        void loadFeedbackForVideos(
          initialVideos.map(video => video.video_id),
          controller.signal
        );
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
  }, [client, focused, trackingReady, retry, authError, loadFeedbackForVideos]);


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

      if (
        page.next_cursor === requestedCursor ||
        (page.next_cursor !== null && seenCursorsRef.current.has(page.next_cursor))
      )
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

      void loadFeedbackForVideos(
        page.videos.map(video => video.video_id)
      );
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
  }, [client, authError, loadFeedbackForVideos]);


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


  const retryLoading = useCallback(() =>
  {
    if (!trackingReady)
    {
      setError('');
      setLoading(true);
      setTrackingRetry(value => value + 1);
      return;
    }

    refreshFeed();
  }, [trackingReady, refreshFeed]);


  const renderItem = useCallback(
    ({ item, index }: { item: Candidate; index: number }) => (
      <FeedVideo
        item={item}
        active={focused && index === active}
        enabled={focused && index >= active && index <= active + 1}
        client={client}
        height={height}
        onAuthError={authError}
        onInteractionEvent={(videoId, eventType, details) =>
        {
          void handleInteractionEvent(videoId, eventType, details);
        }}
        isLiked={likedByVideo[item.video_id] ?? false}

        onToggleLike={handleToggleLike}
      />
    ),
    [
      active,
      authError,
      client,
      focused,
      height,
      handleInteractionEvent,
      likedByVideo,

      handleToggleLike,
    ]
  );


  return (
    <View
      style={styles.container}
      onLayout={event =>
      {
        setHeight(event.nativeEvent.layout.height);
      }}
    >
      {loading && videos.length === 0 ? (
        <FeedSkeleton />
      ) : videos.length > 0 && height > 0 ? (
        <FlatList
          data={videos}
          keyExtractor={item => item.video_id}
          renderItem={renderItem}
          pagingEnabled
          snapToInterval={height}
          snapToAlignment="start"
          decelerationRate="fast"
          disableIntervalMomentum
          initialNumToRender={2}
          maxToRenderPerBatch={2}
          windowSize={3}
          showsVerticalScrollIndicator={false}
          getItemLayout={(_, index) => ({
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
          extraData={{ active, focused, height, likedByVideo }}
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
            <Pressable onPress={retryLoading}>
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


      {loadingMore && (
        <ActivityIndicator color="#5DE5E0" style={styles.loadingMoreIndicator} />
      )}

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
            style={styles.errorActionText}
          >
            {expired ? 'Refresh feed' : 'Retry loading'}
          </Text>
        </View>
      )}


      <View pointerEvents="none" style={styles.brand}>
        <Text style={styles.brandText}>
          Ataraxia
        </Text>
      </View>


      <View pointerEvents="box-none" style={styles.profileMenuContainer}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Open profile menu"
          onPress={() => setProfileMenuVisible(visible => !visible)}
          style={styles.profileButton}
        >
          <Text style={styles.profileButtonText}>
            ♙
          </Text>
        </Pressable>

        {profileMenuVisible && (
          <View style={styles.profileDropdown}>
            <Pressable
              disabled={loggingOut}
              onPress={() => void handleLogout()}
              style={styles.logoutButton}
            >
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
