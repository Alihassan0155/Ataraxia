
import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { router } from 'expo-router';
import { authenticatedFetch } from '../../services/auth';

type Interest = {
  id: string;
  name: string;
  taxonomy_version: string;
};

type InterestsResponse = {
  interests: Interest[];
};

function getErrorMessage(data: any, fallback: string): string {
  if (typeof data?.detail === 'string') {
    return data.detail;
  }

  return fallback;
}

export default function InterestsScreen() {
  const [interests, setInterests] = useState<Interest[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    async function loadInterests() {
      try {
        setLoading(true);
        setError('');

        const categoriesResponse = await authenticatedFetch(
          '/onboarding/interests'
        );

        if (!categoriesResponse.ok) {
          throw new Error('Could not load interest categories.');
        }

        const categoriesData: InterestsResponse =
          await categoriesResponse.json();

        setInterests(categoriesData.interests);

        const preferencesResponse = await authenticatedFetch(
          '/users/me/interests'
        );

        if (!preferencesResponse.ok) {
          throw new Error('Could not load your saved interests.');
        }

        const preferencesData: InterestsResponse =
          await preferencesResponse.json();

        const savedIds: string[] = [];

        for (const interest of preferencesData.interests) {
          savedIds.push(interest.id);
        }

        setSelectedIds(savedIds);
      } catch (err) {
        if (err instanceof Error) {
          setError(err.message);
        } else {
          setError('Something went wrong while loading interests.');
        }
      } finally {
        setLoading(false);
      }
    }

    loadInterests();
  }, []);

  function toggleInterest(id: string) {
    setSelectedIds((currentIds) => {
      const updatedIds: string[] = [];

      for (const currentId of currentIds) {
        if (currentId !== id) {
          updatedIds.push(currentId);
        }
      }

      if (updatedIds.length === currentIds.length) {
        updatedIds.push(id);
      }

      return updatedIds;
    });
  }

  function skipOnboarding() {
    router.replace('/(tabs)');
  }

  async function saveInterests() {
    if (selectedIds.length === 0) {
      setError('Please select at least one interest, or skip for now.');
      return;
    }

    try {
      setSaving(true);
      setError('');

      const response = await authenticatedFetch(
        '/users/me/interests',
        {
          method: 'PUT',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            category_ids: selectedIds,
          }),
        }
      );

      if (!response.ok) {
        let message = 'Could not save your interests.';

        try {
          const data = await response.json();
          message = getErrorMessage(data, message);
        } catch {
          // Keep the default error message.
        }

        throw new Error(message);
      }

      router.replace('/(tabs)');
    } catch (err) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Something went wrong while saving your interests.');
      }
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <View style={styles.container}>
        <ActivityIndicator size="large" color="#5DE5E0" />
        <Text style={styles.loadingText}>Loading your interests...</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Choose Your Interests</Text>

      <Text style={styles.subtitle}>
        Personalize your Ataraxia video feed by selecting the topics you enjoy.
      </Text>

      <Text style={styles.selectionCount}>
        {selectedIds.length} selected
      </Text>

      {error !== '' && (
        <View style={styles.errorContainer}>
          <Text style={styles.errorText}>{error}</Text>

          <Pressable
            onPress={() => router.replace('/(onboarding)/interests')}
          >
            <Text style={styles.retryText}>Reload screen</Text>
          </Pressable>
        </View>
      )}

      <FlatList
        data={interests}
        keyExtractor={(item) => item.id}
        numColumns={2}
        columnWrapperStyle={styles.categoryRow}
        contentContainerStyle={styles.listContent}
        showsVerticalScrollIndicator={false}
        ListEmptyComponent={
          <Text style={styles.emptyText}>
            No interest categories are available right now.
          </Text>
        }
        renderItem={({ item }) => {
          const isSelected = selectedIds.includes(item.id);

          return (
            <Pressable
              style={[
                styles.categoryButton,
                isSelected && styles.categoryButtonSelected,
              ]}
              onPress={() => toggleInterest(item.id)}
              accessibilityRole="checkbox"
              accessibilityState={{ checked: isSelected }}
            >
              <Text
                style={[
                  styles.categoryText,
                  isSelected && styles.categoryTextSelected,
                ]}
              >
                {isSelected ? '✓  ' : ''}
                {item.name}
              </Text>
            </Pressable>
          );
        }}
      />

      <Pressable
        style={[
          styles.saveButton,
          (saving || interests.length === 0) && styles.disabledButton,
        ]}
        onPress={saveInterests}
        disabled={saving || interests.length === 0}
      >
        {saving ? (
          <ActivityIndicator color="#071E2A" />
        ) : (
          <Text style={styles.saveButtonText}>Save Interests</Text>
        )}
      </Pressable>

      <Pressable
        style={styles.skipButton}
        onPress={skipOnboarding}
        disabled={saving}
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
  loadingText: {
    color: '#FFFFFF',
    textAlign: 'center',
    marginTop: 16,
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
});
