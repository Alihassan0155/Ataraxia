
import { StyleSheet } from 'react-native';

const styles = StyleSheet.create({
  container: {
    width: '100%',
    backgroundColor: '#071E2A',
    overflow: 'hidden',
  },
  video: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
  },
  caption: {
    position: 'absolute',
    bottom: 34,
    left: 20,
    right: 76,
  },
  category: {
    color: '#D3E4E8',
    fontSize: 12,
    marginTop: 2,
  },
  text: {
    color: '#FFFFFF',
    fontSize: 13,
    marginBottom: 6,
  },
  action: {
    color: '#5DE5E0',
    padding: 12,
  },
  loader: {
    position: 'absolute',
    alignSelf: 'center',
    top: '45%',
    alignItems: 'center',
  },
  feedback: {
    position: 'absolute',
    alignSelf: 'center',
    top: '45%',
    minWidth: 100,
    minHeight: 76,
    paddingHorizontal: 20,
    borderRadius: 40,
    backgroundColor: '#00000099',
    alignItems: 'center',
    justifyContent: 'center',
  },
  feedbackText: {
    color: '#FFFFFF',
    fontSize: 18,
    fontWeight: 'bold',
  },
  tapZones: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    flexDirection: 'row',
  },
  tapZone: {
    flex: 1,
  },
});

export default styles;
