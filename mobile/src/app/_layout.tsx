
import { useEffect, useState } from 'react';
import { DarkTheme, DefaultTheme, ThemeProvider, Stack, router } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import * as SplashScreen from 'expo-splash-screen';
import { useColorScheme, View, ActivityIndicator } from 'react-native';

import { AnimatedSplashOverlay } from '@/components/animated-icon';
import { restoreSession } from '@/services/auth';
import { Colors } from '@/constants/colors';

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const colorScheme = useColorScheme();
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    async function checkSession() 
    {
      try 
      {
        const isAuthenticated = await restoreSession();

        if (isAuthenticated) 
        {
          router.replace('/(onboarding)/interests');
        } 
        else 
        {
          router.replace('/login');
        }
      } 
      catch (error) 
      {
        console.error('Session restoration failed:', error);
        router.replace('/login');
      } 
      finally 
      {
        setCheckingSession(false);
      }
    }

    checkSession();
  }, []);

  return (
    <ThemeProvider value={colorScheme === 'dark' ? DarkTheme : DefaultTheme}>
      <StatusBar style="light" />
      <AnimatedSplashOverlay />

      {checkingSession ? (
        <View style={{
            flex: 1,
            backgroundColor: Colors.backgroundBottom,
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <ActivityIndicator size="large" color={Colors.accent} />
        </View>
      ) : (
        <Stack screenOptions={{ headerShown: false }}>
          <Stack.Screen name="index" />
          <Stack.Screen name="(auth)" />
          <Stack.Screen name="(onboarding)" />
          <Stack.Screen name="(tabs)" />
        </Stack>
      )}
    </ThemeProvider>
  );
}
