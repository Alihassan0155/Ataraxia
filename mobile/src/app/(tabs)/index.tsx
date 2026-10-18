
import { useEffect, useRef, useState } from 'react';
import {ActivityIndicator, Animated, Text, View, } from 'react-native';
import { useVideoPlayer, VideoView } from 'expo-video';
import { authenticatedFetch } from '@/services/auth';
import styles from '@/styles/home.styles';

type VideoItem = { video_key: string; playback_url: string;};

export default function HomeScreen() 
{
  const [videos, setVideos] = useState<VideoItem[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [screenHeight, setScreenHeight] = useState(0);
  const [screenWidth, setScreenWidth] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);
  const [playbackFeedback, setPlaybackFeedback] = useState('');

  const activeIndexRef = useRef(0);
  const videosRef = useRef<VideoItem[]>([]);
  const switchingRef = useRef(false);

  const touchStartY = useRef(0);
  const touchStartX = useRef(0);
  const touchMovedRef = useRef(false);

  const lastTapRef = useRef<{
    time: number;
    side: string;
  } | null>(null);

  const tapTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const feedbackTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const translateY = useRef(new Animated.Value(0)).current;
  const feedbackOpacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    let cancelled = false;

    async function loadVideos() 
    {
      try 
      {
        const response = await authenticatedFetch('/videos/feed');

        if (!response.ok) 
        {
          throw new Error('Could not load the video feed.');
        }

        const data = await response.json();

        if (!Array.isArray(data.videos) || data.videos.length === 0) 
        {
          throw new Error('No videos are available.');
        }

        if (!cancelled) 
        {
          videosRef.current = data.videos;
          setVideos(data.videos);
          activeIndexRef.current = 0;
          setActiveIndex(0);
        }
      } 
      catch (error) 
      {
        if (!cancelled) 
        {
          setErrorMessage(error instanceof Error ? error.message : 'Something went wrong while loading the video feed.');
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

    loadVideos();

    return () => {
      cancelled = true;

      if (tapTimeoutRef.current) 
      {
        clearTimeout(tapTimeoutRef.current);
      }

      if (feedbackTimeoutRef.current) 
      {
        clearTimeout(feedbackTimeoutRef.current);
      }
    };
  }, []);

  const player = useVideoPlayer( videos.length > 0 ? videos[activeIndex]?.playback_url ?? null : null,
    (videoPlayer) => {
      videoPlayer.loop = true;
      videoPlayer.play();
    }
  );

  function showFeedback(message: string) 
  {
    setPlaybackFeedback(message);
    feedbackOpacity.setValue(1);

    if (feedbackTimeoutRef.current) 
    {
      clearTimeout(feedbackTimeoutRef.current);
    }

    feedbackTimeoutRef.current = setTimeout(() => {
      Animated.timing(feedbackOpacity, {
        toValue: 0,
        duration: 200,
        useNativeDriver: true,
      }).start(() => {
        setPlaybackFeedback('');
      });
    }, 500);
  }

  function togglePlayback() 
  {
    if (isPlaying) 
    {
      player.pause();
      setIsPlaying(false);
      showFeedback('Ⅱ');
    } 
    else 
    {
      player.play();
      setIsPlaying(true);
      showFeedback('▶');
    }
  }

  function seekVideo(seconds: number) 
  {
    if (switchingRef.current) 
    {
      return;
    }

    player.seekBy(seconds);

    if (seconds < 0) 
    {
      showFeedback('↶ 5 seconds');
    } 
    else 
    {
      showFeedback('5 seconds ↷');
    }
  }

  function handleTap(side: string) 
  {
    const now = Date.now();
    const lastTap = lastTapRef.current;

    if (lastTap && now - lastTap.time < 280 && lastTap.side === side) 
    {
      if (tapTimeoutRef.current) 
      {
        clearTimeout(tapTimeoutRef.current);
        tapTimeoutRef.current = null;
      }

      lastTapRef.current = null;

      if (side === 'left') 
      {
        seekVideo(-5);
      } 
      else 
      {
        seekVideo(5);
      }

      return;
    }

    if (lastTap && tapTimeoutRef.current) 
    {
      clearTimeout(tapTimeoutRef.current);
      tapTimeoutRef.current = null;
      togglePlayback();
    }

    lastTapRef.current = {time: now, side,};

    tapTimeoutRef.current = setTimeout(() => {
      togglePlayback();
      lastTapRef.current = null;
      tapTimeoutRef.current = null;
    }, 280);
  }

  function changeVideo(direction: number) 
  {
    const currentVideos = videosRef.current;

    if (currentVideos.length === 0 || switchingRef.current || screenHeight <= 0) 
    {
      return;
    }

    const nextIndex = activeIndexRef.current + direction;

    if (nextIndex < 0 || nextIndex >= currentVideos.length) 
    {
      Animated.spring(translateY, {
        toValue: 0,
        useNativeDriver: false,
        speed: 20,
        bounciness: 0,
      }).start();

      return;
    }

    switchingRef.current = true;

    if (tapTimeoutRef.current) 
    {
      clearTimeout(tapTimeoutRef.current);
      tapTimeoutRef.current = null;
    }

    lastTapRef.current = null;

    if (feedbackTimeoutRef.current) 
    {
      clearTimeout(feedbackTimeoutRef.current);
    }

    setPlaybackFeedback('');
    feedbackOpacity.setValue(0);

    // Finish moving the current video off-screen.
    Animated.timing(translateY, {
      toValue: direction > 0 ? -screenHeight : screenHeight,
      duration: 130,
      useNativeDriver: false,
    }).start(({ finished }) => {
      if (!finished) 
      {
        switchingRef.current = false;
        return;
      }

      activeIndexRef.current = nextIndex;
      setActiveIndex(nextIndex);
      setIsPlaying(true);

      translateY.setValue(direction > 0 ? screenHeight : -screenHeight);

      // new video into view.
      Animated.timing(translateY, {
        toValue: 0,
        duration: 170,
        useNativeDriver: false,
      }).start(() => {
        switchingRef.current = false;
      });
    });
  }

  function returnVideoToPosition() 
  {
    Animated.spring(translateY, {
      toValue: 0,
      useNativeDriver: false,
      speed: 20,
      bounciness: 0,
    }).start();
  }

  function handleTouchStart(event: any) 
  {
    if (switchingRef.current) 
    {
      return;
    }

    touchStartY.current = event.nativeEvent.pageY;
    touchStartX.current = event.nativeEvent.pageX;
    touchMovedRef.current = false;
  }

  function handleTouchMove(event: any) 
  {
    if (switchingRef.current || screenHeight <= 0) {
      return;
    }

    const currentY = event.nativeEvent.pageY;
    const currentX = event.nativeEvent.pageX;

    const differenceY = currentY - touchStartY.current;
    const differenceX = currentX - touchStartX.current;

    // a vertical drag.
    if (!touchMovedRef.current && Math.abs(differenceY) < 8) 
    {
      return;
    }

    if ( Math.abs(differenceX) > Math.abs(differenceY) * 1.2 && !touchMovedRef.current) 
    {
      return;
    }

    touchMovedRef.current = true;

    const atFirstVideo = activeIndexRef.current === 0;
    const atLastVideo = activeIndexRef.current === videosRef.current.length - 1;

    let dragDistance = differenceY;

    if ((atFirstVideo && differenceY > 0) || (atLastVideo && differenceY < 0)) 
    {
      dragDistance = differenceY * 0.25;
    }

    translateY.setValue(dragDistance);
  }

  function handleTouchEnd(event: any) 
  {
    if (switchingRef.current) 
    {
      return;
    }

    const endY = event.nativeEvent.pageY;
    const endX = event.nativeEvent.pageX;

    const differenceY = endY - touchStartY.current;
    const differenceX = endX - touchStartX.current;

    if (touchMovedRef.current) 
    {
      const threshold = Math.max(50, screenHeight * 0.12);

      if (Math.abs(differenceY) >= threshold && Math.abs(differenceY) > Math.abs(differenceX)) 
      {
        if (differenceY < 0) 
        {
          changeVideo(1);
        } 
        else 
        {
          changeVideo(-1);
        }
      } 
      else 
      {
        returnVideoToPosition();
      }

      touchMovedRef.current = false;
      return;
    }

    if (Math.abs(differenceX) > 20 || Math.abs(differenceY) > 20) 
    {
      return;
    }

    if (screenWidth <= 0) 
    {
      return;
    }

    const side = endX < screenWidth / 2 ? 'left' : 'right';

    handleTap(side);
  }

  return (
    <View style={styles.container} onLayout={(event) => {
        setScreenHeight(event.nativeEvent.layout.height);
        setScreenWidth(event.nativeEvent.layout.width);
      }}
      onTouchStart={handleTouchStart} onTouchMove={handleTouchMove} onTouchEnd={handleTouchEnd} onTouchCancel={() => {
        touchMovedRef.current = false;

        if (!switchingRef.current) 
        {
          returnVideoToPosition();
        }
      }}
    >
      {loading ? (
        <ActivityIndicator size="large" color="#5DE5E0" />
      ) : errorMessage ? (
        <Text style={styles.message}>{errorMessage}</Text>
      ) : videos.length > 0 ? (
        <Animated.View style={[styles.videoPage,{transform: [{ translateY }],},]}>
          <VideoView key={videos[activeIndex]?.video_key} player={player} style={styles.video} contentFit="contain" nativeControls={false}/>

          <View style={styles.overlay} pointerEvents="none">
            <Text style={styles.title}>Ataraxia</Text>

            <Text style={styles.subtitle}>
              {videos[activeIndex]?.video_key}
            </Text>

            <Text style={styles.hint}>
              Tap to pause · Double-tap to seek 5 seconds
            </Text>

            <Text style={styles.hint}>
              Swipe up for next video
            </Text>
          </View>

          {playbackFeedback !== '' && (
            <Animated.View pointerEvents="none" style={[styles.feedbackContainer, { opacity: feedbackOpacity },]}>
              <Text style={styles.feedbackText}>
                {playbackFeedback}
              </Text>
            </Animated.View>
          )}

          <View style={styles.counter} pointerEvents="none">
            <Text style={styles.counterText}>
              {activeIndex + 1} / {videos.length}
            </Text>
          </View>
        </Animated.View>
      ) : (
        <Text style={styles.message}>No video available.</Text>
      )}
    </View>
  );
}
