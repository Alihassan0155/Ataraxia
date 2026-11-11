
import { StyleSheet } from 'react-native';

const styles = StyleSheet.create({
  // Main feed screen
  container: {
    flex: 1,
    backgroundColor: '#071E2A',
    justifyContent: 'center',
    overflow: 'hidden',
  },

  // Feed skeleton
  skeletonContainer: {
    flex: 1,
    backgroundColor: '#071E2A',
    paddingHorizontal: 18,
    paddingTop: 82,
    paddingBottom: 28,
    justifyContent: 'flex-end',
  },

  skeletonShimmer: {
    position: 'absolute',
    top: 70,
    left: 12,
    right: 12,
    bottom: 20,
    borderRadius: 18,
    backgroundColor: '#103B4A',
  },

  skeletonActions: {
    position: 'absolute',
    right: 22,
    bottom: 112,
    alignItems: 'center',
    gap: 22,
  },

  skeletonAction: {
    width: 38,
    height: 38,
    borderRadius: 20,
    backgroundColor: '#285566',
  },

  skeletonTextContainer: {
    gap: 12,
    marginBottom: 16,
    marginRight: 54,
  },

  skeletonTitle: {
    width: 145,
    height: 16,
    borderRadius: 8,
    backgroundColor: '#285566',
  },

  skeletonLineWide: {
    width: '92%',
    height: 12,
    borderRadius: 6,
    backgroundColor: '#285566',
  },

  skeletonLineShort: {
    width: '68%',
    height: 12,
    borderRadius: 6,
    backgroundColor: '#285566',
  },

  // Empty feed state
  emptyContainer: {
    padding: 24,
    alignItems: 'center',
  },

  emptyText: {
    color: '#FFFFFF',
    textAlign: 'center',
  },

  chooseInterestsText: {
    color: '#5DE5E0',
    textAlign: 'center',
    padding: 12,
  },

  retryText: {
    color: '#5DE5E0',
    textAlign: 'center',
    padding: 8,
  },

  // Feed counter
  feedCounter: {
    position: 'absolute',
    right: 18,
    bottom: 30,
  },

  feedCounterText: {
    color: '#FFFFFF',
    fontSize: 14,
  },

  // Loading indicator
  loadingMoreIndicator: {
    position: 'absolute',
    bottom: 10,
    alignSelf: 'center',
  },

  // Error message
  errorBanner: {
    position: 'absolute',
    top: 8,
    left: 12,
    right: 12,
    padding: 10,
    backgroundColor: '#103B49',
  },

  errorText: {
    color: '#FFFFFF',
    textAlign: 'center',
  },

  errorActionText: {
    color: '#5DE5E0',
    textAlign: 'center',
    padding: 8,
  },

  // Ataraxia branding
  brand: {
    position: 'absolute',
    top: 40,
    left: 20,
    zIndex: 20,
  },

  brandText: {
    color: '#FFFFFF',
    fontSize: 23,
    fontWeight: 'bold',
  },

  // Profile menu
  profileMenuContainer: {
    position: 'absolute',
    top: 42,
    right: 16,
    alignItems: 'flex-end',
    zIndex: 20,
  },

  profileButton: {
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: 'rgba(7, 30, 42, 0.88)',
    borderWidth: 1,
    borderColor: '#67E8E4',
    alignItems: 'center',
    justifyContent: 'center',
  },

  profileButtonText: {
    color: '#F4FBFC',
    fontSize: 22,
  },

  profileDropdown: {
    width: 184,
    marginTop: 8,
    paddingVertical: 6,
    borderRadius: 12,
    backgroundColor: '#0D3B4C',
    borderWidth: 1,
    borderColor: '#285566',
  },

  logoutButton: {
    paddingHorizontal: 16,
    paddingVertical: 13,
  },

  logoutText: {
    color: '#67E8E4',
    fontSize: 15,
  },

  // Existing video component styles
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

  message: {
    color: '#FFFFFF',
    fontSize: 16,
    textAlign: 'center',
    paddingHorizontal: 24,
  },
});

export default styles;
