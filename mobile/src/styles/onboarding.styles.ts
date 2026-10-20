
import { StyleSheet } from 'react-native';

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#071E2A',
    paddingTop: 54,
    paddingHorizontal: 20,
    paddingBottom: 20,
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
    lineHeight: 22,
    textAlign: 'center',
    marginTop: 12,
  },

  selectionCount: {
    color: '#5DE5E0',
    fontSize: 14,
    textAlign: 'center',
    marginTop: 18,
    marginBottom: 12,
  },

  listContent: {
    paddingBottom: 12,
    flexGrow: 1,
  },

  categoryRow: {
    justifyContent: 'space-between',
    marginBottom: 12,
  },

  categoryButton: {
    width: '48%',
    minHeight: 58,
    paddingHorizontal: 10,
    paddingVertical: 12,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#285566',
    backgroundColor: '#0D3B4C',
    justifyContent: 'center',
  },

  categoryButtonSelected: {
    backgroundColor: '#5DE5E0',
    borderColor: '#5DE5E0',
  },

  categoryText: {
    color: '#FFFFFF',
    fontSize: 14,
    textAlign: 'center',
    fontWeight: '500',
  },

  categoryTextSelected: {
    color: '#071E2A',
    fontWeight: 'bold',
  },

  emptyText: {
    color: '#FFFFFF',
    textAlign: 'center',
    marginTop: 24,
  },

  errorContainer: {
    backgroundColor: '#3A2028',
    borderRadius: 8,
    padding: 12,
    marginBottom: 12,
  },

  errorText: {
    color: '#FFB4B4',
    textAlign: 'center',
  },

  retryText: {
    color: '#5DE5E0',
    textAlign: 'center',
    marginTop: 8,
    fontWeight: 'bold',
  },

  saveButton: {
    backgroundColor: '#5DE5E0',
    borderRadius: 10,
    paddingVertical: 15,
    alignItems: 'center',
    marginTop: 8,
  },

  disabledButton: {
    opacity: 0.6,
  },

  saveButtonText: {
    color: '#071E2A',
    fontSize: 16,
    fontWeight: 'bold',
  },

  skipButton: {
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 4,
  },

  skipButtonText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '600',
  },


  skeletonHeadingContainer: {
    alignItems: 'center',
  },

  skeletonTitle: {
    width: '78%',
    height: 30,
    borderRadius: 8,
    backgroundColor: '#285566',
  },

  skeletonSubtitle: {
    width: '100%',
    height: 14,
    borderRadius: 6,
    backgroundColor: '#285566',
    marginTop: 18,
  },

  skeletonSubtitleShort: {
    width: '72%',
    height: 14,
    borderRadius: 6,
    backgroundColor: '#285566',
    marginTop: 8,
  },

  skeletonCounterContainer: {
    alignItems: 'center',
    marginTop: 24,
    marginBottom: 12,
  },

  skeletonCounter: {
    width: 90,
    height: 14,
    borderRadius: 6,
    backgroundColor: '#285566',
  },

  skeletonList: {
    flex: 1,
  },

  skeletonRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },

  skeletonCategory: {
    width: '48%',
    height: 58,
    borderRadius: 10,
    backgroundColor: '#0D3B4C',
    borderWidth: 1,
    borderColor: '#285566',
  },

  skeletonSaveButton: {
    height: 50,
    borderRadius: 10,
    backgroundColor: '#5DE5E0',
    marginTop: 8,
  },

  skeletonSkipButton: {
    height: 44,
    borderRadius: 10,
    backgroundColor: '#0D3B4C',
    marginTop: 4,
  },
});

export default styles;
