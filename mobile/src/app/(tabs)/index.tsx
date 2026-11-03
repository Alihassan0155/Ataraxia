import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Animated,
  FlatList,
  Pressable,
  Text,
  View,
  ViewToken,
} from 'react-native';
import { router, useFocusEffect } from 'expo-router';
import {
  authenticatedFetch,
  AuthenticationError,
  clearSession,
} from '@/services/auth';
import {
  Candidate,
  FeedClient,
  FeedError,
  mergeCandidates,
} from '@/services/feed';
import { FeedVideo } from '@/components/feed-video';
import { preferenceRevision } from '@/services/performance';

function FeedSkeleton() {
  const shimmer = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(shimmer, {
          toValue: 1,
          duration: 900,
          useNativeDriver: true,
        }),
        Animated.timing(shimmer, {
          toValue: 0,
          duration: 900,
          useNativeDriver: true,
        }),
      ])
    );

    animation.start();

    return () => {
      animation.stop();
    };
  }, [shimmer]);

  const shimmerOpacity = shimmer.interpolate({
    inputRange: [0, 1],
    outputRange: [0.3, 0.8],
  });

  return (
    <View
      accessibilityLabel="Loading your video feed"
      accessibilityRole="progressbar"
      style={{
        flex: 1,
        backgroundColor: '#071E2A',
        paddingHorizontal: 18,
        paddingTop: 82,
        paddingBottom: 28,
        justifyContent: 'flex-end',
      }}
    >
      <Animated.View
        style={{
          position: 'absolute',
          top: 70,
          left: 12,
          right: 12,
          bottom: 20,
          borderRadius: 18,
          backgroundColor: '#103B4A',
          opacity: shimmerOpacity,
        }}
      />

      <View
        style={{
          position: 'absolute',
          right: 22,
          bottom: 112,
          alignItems: 'center',
          gap: 22,
        }}
      >
        {[0, 1, 2, 3].map((item) => (
          <Animated.View
            key={item}
            style={{
              width: 38,
              height: 38,
              borderRadius: 20,
              backgroundColor: '#285566',
              opacity: shimmerOpacity,
            }}
          />
        ))}
      </View>

      <View style={{ gap: 12, marginBottom: 16, marginRight: 54 }}>
        <Animated.View
          style={{
            width: 145,
            height: 16,
            borderRadius: 8,
            backgroundColor: '#285566',
            opacity: shimmerOpacity,
          }}
        />
        <Animated.View
          style={{
            width: '92%',
            height: 12,
            borderRadius: 6,
            backgroundColor: '#285566',
            opacity: shimmerOpacity,
          }}
        />
        <Animated.View
          style={{
            width: '68%',
            height: 12,
            borderRadius: 6,
            backgroundColor: '#285566',
            opacity: shimmerOpacity,
          }}
        />
      </View>
    </View>
  );
}

export default function HomeScreen() {
  const client = useMemo(
    () => new FeedClient(authenticatedFetch),
    []
  );

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

  const authError = useCallback(() => {
    if (!redirectedRef.current) {
      redirectedRef.current = true;
      router.replace('/login');
    }
  }, []);

  const handleLogout = useCallback(async () => {
    if (loggingOut) {
      return;
    }

    setLoggingOut(true);

    try {
      await clearSession();
      setProfileMenuVisible(false);
      router.replace('/login');
    } catch (error) {
      console.error('Logout failed:', error);
      setError('Could not log out. Please try again.');
    } finally {
      setLoggingOut(false);
    }
  }, [loggingOut]);

  useFocusEffect(
    useCallback(() => {
      const currentRevision = preferenceRevision();

      if (revisionRef.current !== currentRevision) {
        revisionRef.current = currentRevision;

        videosRef.current = [];
        cursorRef.current = null;
        initializedRef.current = false;
        loadingMoreRef.current = false;
        seenCursorsRef.current.clear();

        setVideos([]);
        setActive(0);
        setTotal(0);
        setError('');
        setExpired(false);
        setLoading(true);
        setRetry(value => value + 1);
      }

      setFocused(true);

      return () => {
        setFocused(false);
      };
    }, [])
  );

  const viewabilityConfig = useRef({
    itemVisiblePercentThreshold: 80,
  });

  const onViewableItemsChanged = useRef(
    ({ viewableItems }: { viewableItems: ViewToken[] }) => {
      const visibleItem = viewableItems.find(
        item => item.isViewable && item.index !== null
      );

      if (
        visibleItem?.index !== null &&
        visibleItem?.index !== undefined
      ) {
        setActive(visibleItem.index);
      }
    }
  );

  useEffect(() => {
    if (!focused || initializedRef.current) {
      return;
    }

    const controller = new AbortController();
    let cancelled = false;

    async function loadInitialFeed() {
      setLoading(true);
      setError('');

      try {
        const page = await client.page(null, controller.signal);

        if (cancelled) {
          return;
        }

        if (page.videos.length === 0) {
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
      } catch (failure) {
        if (cancelled) {
          return;
        }

        if (failure instanceof AuthenticationError) {
          authError();
        } else {
          setExpired(
            failure instanceof FeedError && failure.status === 410
          );
          setError(
            failure instanceof Error
              ? failure.message
              : 'Could not load videos. Please retry.'
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadInitialFeed();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [client, focused, retry, authError]);

  const loadMoreVideos = useCallback(async () => {
    if (
      loadingMoreRef.current ||
      !cursorRef.current ||
      videosRef.current.length >= 50
    ) {
      return;
    }

    const requestedCursor = cursorRef.current;

    if (seenCursorsRef.current.has(requestedCursor)) {
      setError('The feed did not advance. Please refresh.');
      return;
    }

    loadingMoreRef.current = true;
    setLoadingMore(true);

    try {
      const page = await client.page(requestedCursor);

      if (
        page.next_cursor === requestedCursor ||
        (page.next_cursor !== null &&
          seenCursorsRef.current.has(page.next_cursor))
      ) {
        throw new Error('The feed did not advance. Please refresh.');
      }

      seenCursorsRef.current.add(requestedCursor);

      const merged = mergeCandidates(
        videosRef.current,
        page.videos
      );

      videosRef.current = merged;
      cursorRef.current = page.next_cursor;

      setVideos(merged);
      setTotal(page.total);
      setError('');
      setExpired(false);
    } catch (failure) {
      if (failure instanceof AuthenticationError) {
        authError();
      } else {
        setExpired(
          failure instanceof FeedError && failure.status === 410
        );
        setError(
          failure instanceof Error
            ? failure.message
            : 'Could not load more videos.'
        );
      }
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [client, authError]);

  useEffect(() => {
    if (
      focused &&
      videos.length > 0 &&
      active >= videos.length - 2
    ) {
      void loadMoreVideos();
    }
  }, [focused, active, videos.length, loadMoreVideos]);

  const refreshFeed = useCallback(() => {
    videosRef.current = [];
    cursorRef.current = null;
    initializedRef.current = false;
    loadingMoreRef.current = false;
    seenCursorsRef.current.clear();

    setVideos([]);
    setActive(0);
    setTotal(0);
    setExpired(false);
    setError('');
    setLoading(true);
    setRetry(value => value + 1);
  }, []);

  const renderItem = useCallback(
    ({ item, index }: { item: Candidate; index: number }) => (
      <FeedVideo
        item={item}
        active={focused && index === active}
        enabled={
          focused &&
          index >= active &&
          index <= active + 1
        }
        client={client}
        height={height}
        onAuthError={authError}
      />
    ),
    [active, authError, client, focused, height]
  );

  return (
    <View
      style={{
        flex: 1,
        backgroundColor: '#071E2A',
        justifyContent: 'center',
        overflow: 'hidden',
      }}
      onLayout={event => {
        setHeight(event.nativeEvent.layout.height);
      }}
    >
      {loading && videos.length === 0 ? (
        <FeedSkeleton />
      ) : videos.length > 0 && height > 0 ? (
        <FlatList
          key={height}
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
          onEndReached={() => {
            void loadMoreVideos();
          }}
          onEndReachedThreshold={0.5}
          extraData={{ active, focused, height }}
        />
      ) : (
        <View style={{ padding: 24, alignItems: 'center' }}>
          <Text style={{ color: '#FFFFFF', textAlign: 'center' }}>
            {error || 'No videos are available.'}
          </Text>

          <Pressable
            onPress={() => router.push('/(onboarding)/interests')}
          >
            <Text
              style={{
                color: '#5DE5E0',
                textAlign: 'center',
                padding: 12,
              }}
            >
              Choose interests
            </Text>
          </Pressable>

          {!!error && (
            <Pressable onPress={refreshFeed}>
              <Text
                style={{
                  color: '#5DE5E0',
                  textAlign: 'center',
                  padding: 8,
                }}
              >
                Retry loading
              </Text>
            </Pressable>
          )}
        </View>
      )}

      {videos.length > 0 && (
        <View
          pointerEvents="none"
          style={{
            position: 'absolute',
            right: 18,
            bottom: 30,
          }}
        >
          <Text style={{ color: '#FFFFFF', fontSize: 14 }}>
            {active + 1} / {total || videos.length}
          </Text>
        </View>
      )}

      {loadingMore && (
        <ActivityIndicator
          color="#5DE5E0"
          style={{
            position: 'absolute',
            bottom: 10,
            alignSelf: 'center',
          }}
        />
      )}

      {!!error && videos.length > 0 && (
        <View
          style={{
            position: 'absolute',
            top: 8,
            left: 12,
            right: 12,
            padding: 10,
            backgroundColor: '#103B49',
          }}
        >
          <Text style={{ color: '#FFFFFF', textAlign: 'center' }}>
            {error}
          </Text>

          <Text
            onPress={() => {
              if (expired) {
                refreshFeed();
              } else {
                void loadMoreVideos();
              }
            }}
            style={{
              color: '#5DE5E0',
              textAlign: 'center',
              padding: 8,
            }}
          >
            {expired ? 'Refresh feed' : 'Retry loading'}
          </Text>
        </View>
      )}

      <View
        pointerEvents="none"
        style={{
          position: 'absolute',
          top: 40,
          left: 20,
          zIndex: 20,
        }}
      >
        <Text
          style={{
            color: '#FFFFFF',
            fontSize: 23,
            fontWeight: 'bold',
          }}
        >
          Ataraxia
        </Text>
      </View>

      <View
        pointerEvents="box-none"
        style={{
          position: 'absolute',
          top: 42,
          right: 16,
          alignItems: 'flex-end',
          zIndex: 20,
        }}
      >
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Open profile menu"
          onPress={() =>
            setProfileMenuVisible(visible => !visible)
          }
          style={{
            width: 42,
            height: 42,
            borderRadius: 21,
            backgroundColor: 'rgba(7, 30, 42, 0.88)',
            borderWidth: 1,
            borderColor: '#67E8E4',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Text style={{ color: '#F4FBFC', fontSize: 22 }}>
            ♙
          </Text>
        </Pressable>

        {profileMenuVisible && (
          <View
            style={{
              width: 184,
              marginTop: 8,
              paddingVertical: 6,
              borderRadius: 12,
              backgroundColor: '#0D3B4C',
              borderWidth: 1,
              borderColor: '#285566',
            }}
          >
            <Pressable
              disabled={loggingOut}
              onPress={() => void handleLogout()}
              style={{
                paddingHorizontal: 16,
                paddingVertical: 13,
              }}
            >
              <Text style={{ color: '#67E8E4', fontSize: 15 }}>
                {loggingOut ? 'Logging out...' : 'Log out'}
              </Text>
            </Pressable>
          </View>
        )}
      </View>
    </View>
  );
}
