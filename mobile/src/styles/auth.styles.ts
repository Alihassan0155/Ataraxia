import { StyleSheet } from 'react-native';
import { Colors } from '@/constants/colors';

export const authStyles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: Colors.backgroundBottom,
  },
  container: {
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: 26,
    paddingVertical: 32,
    width: '100%',
    maxWidth: 520,
    alignSelf: 'center',
  },
  header: {
    marginBottom: 32,
  },
  brand: {
    color: Colors.accent,
    fontSize: 18,
    fontWeight: '700',
    marginBottom: 24,
    letterSpacing: 1,
  },
  heading: {
    color: Colors.text,
    fontSize: 30,
    fontWeight: '700',
    marginBottom: 10,
  },
  subtitle: {
    color: Colors.subtitle,
    fontSize: 15,
    lineHeight: 23,
  },
  form: {
    gap: 10,
  },
  label: {
    color: Colors.fieldLabel,
    fontSize: 14,
    fontWeight: '600',
    marginTop: 8,
  },
  input: {
    backgroundColor: Colors.inputBackground,
    borderWidth: 1,
    borderColor: Colors.inputBorder,
    borderRadius: 12,
    color: Colors.text,
    fontSize: 16,
    paddingHorizontal: 15,
    paddingVertical: 14,
  },
  error: {
    color: Colors.error,
    fontSize: 14,
    lineHeight: 20,
    marginTop: 8,
  },
  button: {
    backgroundColor: Colors.accent,
    borderRadius: 12,
    minHeight: 52,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 18,
    paddingHorizontal: 16,
  },
  buttonDisabled: {
    opacity: 0.65,
  },
  buttonText: {
    color: Colors.accentText,
    fontSize: 16,
    fontWeight: '700',
  },
  footer: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    flexWrap: 'wrap',
    marginTop: 28,
  },
  footerText: {
    color: Colors.footerNote,
    fontSize: 14,
  },
  link: {
    color: Colors.accent,
    fontSize: 14,
    fontWeight: '700',
  },
});
