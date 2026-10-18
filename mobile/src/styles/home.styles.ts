
import { StyleSheet } from 'react-native';

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#071E2A',
    overflow: 'hidden',
  },

  videoPage: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    backgroundColor: '#071E2A',
  },

  video: {
    width: '100%',
    height: '100%',
  },

  overlay: {
    position: 'absolute',
    top: 24,
    left: 20,
    right: 20,
  },

  title: {
    color: '#FFFFFF',
    fontSize: 24,
    fontWeight: 'bold',
  },

  subtitle: {
    color: '#FFFFFF',
    fontSize: 12,
    marginTop: 4,
  },

  hint: {
    color: '#FFFFFF',
    fontSize: 13,
    marginTop: 8,
  },

  feedbackContainer: {
    position: 'absolute',
    alignSelf: 'center',
    top: '45%',
    minWidth: 90,
    minHeight: 76,
    paddingHorizontal: 20,
    borderRadius: 40,
    backgroundColor: '#00000099',
    alignItems: 'center',
    justifyContent: 'center',
  },

  feedbackText: {
    color: '#FFFFFF',
    fontSize: 20,
    fontWeight: 'bold',
    textAlign: 'center',
  },

  counter: {
    position: 'absolute',
    right: 20,
    bottom: 30,
  },

  counterText: {
    color: '#FFFFFF',
    fontSize: 14,
  },

  message: {
    color: '#FFFFFF',
    fontSize: 16,
    textAlign: 'center',
    paddingHorizontal: 24,
  },
});

export default styles;
