
import { StyleSheet, Text, View, Pressable } from 'react-native';
import { router } from 'expo-router';

export default function InterestsScreen() {
  function skipOnboarding() {
    router.replace('/(tabs)');
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Choose Your Interests</Text>

      <Text style={styles.subtitle}>
        Personalize your Ataraxia video feed.
      </Text>

      <Pressable
        style={styles.skipButton}
        onPress={skipOnboarding}
      >
        <Text style={styles.skipButtonText}>Skip for now</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#071E2A',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 24,
  },
  title: {
    color: '#5DE5E0',
    fontSize: 28,
    fontWeight: 'bold',
    textAlign: 'center',
  },
  subtitle: {
    color: '#FFFFFF',
    fontSize: 15,
    textAlign: 'center',
    marginTop: 12,
  },
  skipButton: {
    marginTop: 32,
    paddingVertical: 14,
    paddingHorizontal: 36,
    borderRadius: 10,
    backgroundColor: '#5DE5E0',
  },
  skipButtonText: {
    color: '#071E2A',
    fontSize: 16,
    fontWeight: 'bold',
  },
});
