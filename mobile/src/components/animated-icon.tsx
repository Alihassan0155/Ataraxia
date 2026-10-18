
import { useEffect, useRef, useState } from 'react';
import { Animated, StyleSheet, Text, View, } from 'react-native';
import * as SplashScreen from 'expo-splash-screen';

export function AnimatedSplashOverlay() {
  const [visible, setVisible] = useState(true);
  const opacity = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    let hideTimer: ReturnType<typeof setTimeout> | undefined;

    const startSplash = async () => {
      try 
      {
        await SplashScreen.hideAsync();
      } 
      catch 
      {
       
      }

      hideTimer = setTimeout(() => {
        Animated.timing(opacity, { toValue: 0, duration: 500,  useNativeDriver: true, }).start(({ finished }) => {
          if (finished) 
          {
            setVisible(false);
          }
        });
      }, 1200);
    };

    startSplash();

    return () => {
      if (hideTimer) 
      {
        clearTimeout(hideTimer);
      }
    };
  }, [opacity]);

  if (!visible) 
  {
    return null;
  }

  return (
    <Animated.View pointerEvents="none"  style={[styles.overlay, { opacity }]}>
      <View style={styles.logoMark}>
        <Text style={styles.logoLetter}>A</Text>
        <View style={styles.wave} />
      </View>

      <Text style={styles.title}>ATARAXIA</Text>

      <Text style={styles.tagline}>FIND YOUR FLOW.</Text>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  overlay: {
    ...StyleSheet.absoluteFill,
    backgroundColor: '#071E2A',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
    elevation: 1000,
  },
  logoMark: {
    width: 100,
    height: 100,
    borderRadius: 30,
    borderWidth: 1,
    borderColor: '#5DE5E0',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 28,
    backgroundColor: '#103B49',
  },
  logoLetter: {
    color: '#5DE5E0',
    fontSize: 58,
    fontWeight: '300',
  },
  wave: {
    width: 42,
    height: 3,
    borderRadius: 2,
    backgroundColor: '#5DE5E0',
    marginTop: -7,
  },
  title: {
    color: '#F2FAFC',
    fontSize: 29,
    fontWeight: '600',
    letterSpacing: 7,
  },
  tagline: {
    color: '#A9C1CB',
    fontSize: 12,
    letterSpacing: 3,
    marginTop: 14,
  },
});
