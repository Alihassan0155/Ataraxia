import { useState } from 'react';
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, Text, TextInput, View, } from 'react-native';
import { Link, router } from 'expo-router';

import { authStyles as styles } from '@/styles/auth.styles';
import { saveSession, signupUser } from '@/services/auth';
import { Colors } from '@/constants/colors';

export default function SignupScreen() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function handleSignup() 
  {
    setError('');

    if (!email.trim() || !password || !confirmPassword) 
    {
      setError('Please fill in all fields.');
      return;
    }

    if (password.length < 8) 
    {
      setError('Password must contain at least 8 characters.');
      return;
    }

    if (password !== confirmPassword) 
    {
      setError('Passwords do not match.');
      return;
    }

    setLoading(true);

    try 
    {
      const data = await signupUser(email.trim(), password);

      if (data.access_token && data.refresh_token) 
      {
        await saveSession(data.access_token, data.refresh_token);
        router.replace('/(onboarding)/interests');
      } 
      else 
      {
        setError('Account created, but no session was returned. Please log in.');
      }
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
          <Text style={styles.heading}>Create your account</Text>
          <Text style={styles.subtitle}>
            Your feed, shaped around what matters to you.
          </Text>
        </View>

        <View style={styles.form}>
          <Text style={styles.label}>Email address</Text>
          <TextInput style={styles.input} value={email} onChangeText={setEmail} placeholder="Enter your email" placeholderTextColor={Colors.placeholder}
            keyboardType="email-address" autoCapitalize="none" autoCorrect={false} autoComplete="email" editable={!loading}/>

          <Text style={styles.label}>Password</Text>
          <TextInput style={styles.input} value={password} onChangeText={setPassword} placeholder="At least 8 characters" placeholderTextColor={Colors.placeholder}
            secureTextEntry autoComplete="new-password" editable={!loading}/>

          <Text style={styles.label}>Confirm password</Text>
          <TextInput style={styles.input} value={confirmPassword} onChangeText={setConfirmPassword} placeholder="Enter your password again"
            placeholderTextColor={Colors.placeholder} secureTextEntry autoComplete="new-password" editable={!loading}
            onSubmitEditing={handleSignup} returnKeyType="done"/>

          {error ? <Text style={styles.error}>{error}</Text> : null}

          <Pressable style={[styles.button, loading && styles.buttonDisabled]} onPress={handleSignup} disabled={loading}>
            {loading ? (
              <ActivityIndicator color={Colors.accentText} />
            ) : (
              <Text style={styles.buttonText}>Create account</Text>
            )}
          </Pressable>
        </View>

        <View style={styles.footer}>
          <Text style={styles.footerText}>
            Already have an account?{' '}
          </Text>
          <Link href="/login" style={styles.link}>
            Log in
          </Link>
        </View>
      </View>
    </KeyboardAvoidingView>
  );
}