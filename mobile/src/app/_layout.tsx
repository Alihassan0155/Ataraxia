import { useEffect, useRef, useState } from 'react';
import { DarkTheme, DefaultTheme, ThemeProvider, Stack, router, useRootNavigationState } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import * as SplashScreen from 'expo-splash-screen';
import { useColorScheme, View, ActivityIndicator, Text, Pressable, StyleSheet } from 'react-native';
import { AnimatedSplashOverlay } from '@/components/animated-icon';
import { restoreSession } from '@/services/auth';
import { launchDestination } from '@/services/preference-flow';
import { prefetchCategories } from '@/services/onboarding-data';

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const colorScheme = useColorScheme();
  const navigation = useRootNavigationState();
  const redirected = useRef(false);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    prefetchCategories();
  }, []);

  useEffect(() => {
    if (!navigation?.key || redirected.current) return;

    let active = true;
    setChecking(true);
    setError(false);
    launchDestination(restoreSession).then(destination => {
      if (!active || redirected.current) return;
      redirected.current = true;

      router.replace(destination);
      setChecking(false);
    }).catch(() => {
      if (active) { setError(true); setChecking(false); }
    });
    return () => { active = false; };
  }, [navigation?.key, retry]);

  return (
    <ThemeProvider value={colorScheme === 'dark' ? DarkTheme : DefaultTheme}>
      <StatusBar style="light" />
      <Stack screenOptions={{ headerShown: false }}>
        <Stack.Screen name="index" />
        <Stack.Screen name="(auth)" />
        <Stack.Screen name="(onboarding)" />
        <Stack.Screen name="(tabs)" />
      </Stack>
      {(checking || error) && <View style={styles.overlay}>
        {checking ? <ActivityIndicator color="#5DE5E0" /> : <>
          <Text style={styles.text}>Could not verify your session. Check your connection.</Text>
          <Pressable onPress={() => setRetry(value => value + 1)}><Text style={styles.text}>Retry</Text></Pressable>
        </>}
      </View>}
      <AnimatedSplashOverlay />
    </ThemeProvider>
  );
}
const styles = StyleSheet.create({
  overlay: { ...StyleSheet.absoluteFill, backgroundColor: '#071E2A', alignItems: 'center', justifyContent: 'center' },
  text: { color: '#5DE5E0', padding: 16, textAlign: 'center' },
});
