import { useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, Text, TextInput, View,} from 'react-native';
import { Link, router } from 'expo-router';

import { authStyles as styles } from '@/styles/auth.styles';
import { loginUser, saveSession } from '@/services/auth';
import { Colors } from '@/constants/colors';

export default function LoginScreen() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleLogin() 
  {
    setError('');

    if (!email.trim() || !password) 
    {
      setError('Please enter your email and password.');
      return;
    }

    setLoading(true);

    try 
    {
      const data = await loginUser(email.trim(), password);

      if (!data.access_token || !data.refresh_token) 
      {
        setError('Login succeeded, but no session was returned.');
        return;
      }

      await saveSession(data.access_token, data.refresh_token);

      router.replace('/(onboarding)/interests');
    } 
    catch (error) 
    {
      if (error instanceof Error) 
      {
        setError(error.message);
      } 
      else 
      {
        setError('Could not connect to Ataraxia. Check your network and backend server.');
      }
    } 
    finally 
    {
      setLoading(false);
    }
  }

  return (
    <KeyboardAvoidingView style={styles.screen} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <View style={styles.container}>
        <View style={styles.header}>
          <Text style={styles.brand}>Ataraxia</Text>

          <Text style={styles.heading}>Welcome back</Text>

          <Text style={styles.subtitle}>
            Your feed, shaped around what matters to you.
          </Text>
        </View>

        <View style={styles.form}>
          <Text style={styles.label}>Email address</Text>

          <TextInput style={styles.input} value={email} onChangeText={setEmail} placeholder="Enter your email"
            placeholderTextColor={Colors.placeholder} keyboardType="email-address" autoCapitalize="none"
            autoCorrect={false} autoComplete="email" editable={!loading}/>

          <Text style={styles.label}>Password</Text>

          <TextInput style={styles.input} value={password} onChangeText={setPassword} placeholder="Enter your password"
            placeholderTextColor={Colors.placeholder} secureTextEntry autoComplete="current-password" editable={!loading}
            onSubmitEditing={handleLogin} returnKeyType="done"/>

          {error ? (
            <Text style={styles.error}>{error}</Text>
          ) : null}

          <Link href="/forgot-password" style={styles.link}>
            Forgot password?
          </Link>

          <Pressable style={[styles.button, loading && styles.buttonDisabled]} onPress={handleLogin} disabled={loading}>
            {loading ? (
              <ActivityIndicator color={Colors.accentText} />
            ) : (
              <Text style={styles.buttonText}>Log in</Text>
            )}
          </Pressable>
        </View>

        <View style={styles.footer}>
          <Text style={styles.footerText}>
            Don't have an account?{' '}
          </Text>

          <Link href="/signup" style={styles.link}>
            Create account
          </Link>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}
