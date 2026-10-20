
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Animated, FlatList, Pressable, Text, View, } from 'react-native';
import { router } from 'expo-router';
import { authenticatedFetch, AuthenticationError } from '../../services/auth';
import styles from '../../styles/onboarding.styles';
import { confirmPreferences } from '../../services/performance';
import { canContinue, saveSelection, loadPreferenceSelection } from '../../services/preference-flow';
import { publicCategories } from '../../services/onboarding-data';

type Interest = {
  id: string;
  name: string;
  taxonomy_version: string;
};


function getErrorMessage(data: any, fallback: string): string 
{
  if (typeof data?.detail === 'string') 
  {
    return data.detail;
  }

  return fallback;
}

function InterestsSkeleton() 
{
  const shimmer = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(shimmer, {
          toValue: 1,
          duration: 900,
          useNativeDriver: true,
        }),
        Animated.timing(shimmer, {
          toValue: 0,
          duration: 900,
          useNativeDriver: true,
        }),
      ])
    );

    animation.start();

    return () => {
      animation.stop();
    };
  }, [shimmer]);

  const shimmerOpacity = shimmer.interpolate({
    inputRange: [0, 1],
    outputRange: [0.35, 0.85],
  });

  const categoryRows = [];

  for (let i = 0; i < 5; i++) 
  {
    categoryRows.push(
      <View key={i} style={styles.skeletonRow}>
        <Animated.View style={[styles.skeletonCategory, { opacity: shimmerOpacity },]}/>

        <Animated.View style={[styles.skeletonCategory, { opacity: shimmerOpacity },]}/>
      </View>
    );
  }

  return (
    <View style={styles.container} accessibilityLabel="Loading your interests" accessibilityRole="progressbar">
      <View style={styles.skeletonHeadingContainer}>
        <Animated.View style={[ styles.skeletonTitle, { opacity: shimmerOpacity },]}/>

        <Animated.View style={[ styles.skeletonSubtitle,  { opacity: shimmerOpacity },]}/>

        <Animated.View style={[ styles.skeletonSubtitleShort, { opacity: shimmerOpacity }, ]}/>
      </View>

      <View style={styles.skeletonCounterContainer}>
        <Animated.View style={[ styles.skeletonCounter, { opacity: shimmerOpacity }, ]}/>
      </View>

      <View style={styles.skeletonList}>
        {categoryRows}
      </View>

      <Animated.View style={[ styles.skeletonSaveButton, { opacity: shimmerOpacity },]}/>

    </View>
  );
}

export default function InterestsScreen() 
{
  const [interests, setInterests] = useState<Interest[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [preferencesLoaded, setPreferencesLoaded] = useState(false);
  const [reload, setReload] = useState(0);
  const submitting = useRef(false);
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setLoading(true);
    setPreferencesLoaded(false);
    setError('');
    loadPreferenceSelection(path => path === '/onboarding/interests' ? publicCategories() :
      (async () => {
        const response = await authenticatedFetch(path, { signal: controller.signal });

        return response;
      })(), items => { if (active) setInterests(items); }).then(data => {
      if (!active) return;
      setInterests(data.interests);
      setSelectedIds(data.selectedIds);
      setPreferencesLoaded(true);

    }).catch(err => {
      if (!active) return;
      if (err instanceof AuthenticationError) { router.replace('/login'); return; }
      setError(err instanceof Error ? err.message : 'Could not load preferences. Please retry.');
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [reload]);

  function toggleInterest(id: string) 
  {
    setSelectedIds((currentIds) => {
      const updatedIds: string[] = [];

      for (const currentId of currentIds) 
      {
        if (currentId !== id) 
        {
          updatedIds.push(currentId);
        }
      }

      if (updatedIds.length === currentIds.length) 
      {
        updatedIds.push(id);
      }

      return updatedIds;
    });
  }

  async function saveInterests() 
  {
    if (submitting.current || !canContinue(selectedIds, preferencesLoaded, loading, saving))
    {
      setError('Load your preferences and select at least one interest.');
      return;
    }

    submitting.current = true;
    try 
    {
      setSaving(true);
      setError('');

      await saveSelection(selectedIds, async () => {
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

      if (!response.ok) 
      {
        let message = 'Could not save your interests.';

        try 
        {
          const data = await response.json();
          message = getErrorMessage(data, message);
        } 
        catch 
        {
        }

        throw new Error(message);
      }

      confirmPreferences();
      }, () => { if (mounted.current) router.replace('/(tabs)'); });
    } 
    catch (err) 
    {
      if (!mounted.current) return;
      if (err instanceof AuthenticationError) { router.replace('/login'); return; }
      if (err instanceof Error) 
      {
        setError(err.message);
      } 
      else 
      {
        setError('Something went wrong while saving your interests.');
      }
    } 
    finally 
    {
      submitting.current = false;
      if (mounted.current) setSaving(false);
    }
  }

  if (loading && interests.length === 0)
  {
    return <InterestsSkeleton />;
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Choose Your Interests</Text>

      <Text style={styles.subtitle}>
        Personalize your Ataraxia video feed by selecting the topics you enjoy.
      </Text>

      <Text style={styles.selectionCount}>
        {loading ? 'Loading your saved interests…' : `${selectedIds.length} selected`}
      </Text>

      {error !== '' && (
        <View style={styles.errorContainer}>
          <Text style={styles.errorText}>{error}</Text>

          <Pressable disabled={saving} onPress={() => preferencesLoaded ? saveInterests() : setReload(value => value + 1)}>
            <Text style={styles.retryText}>Retry</Text>
          </Pressable>
        </View>
      )}

      <FlatList data={interests} keyExtractor={(item) => item.id} numColumns={2} columnWrapperStyle={styles.categoryRow}
        contentContainerStyle={styles.listContent} showsVerticalScrollIndicator={false} ListEmptyComponent={
          <Text style={styles.emptyText}>
            No interest categories are available right now.
          </Text>
        }
        renderItem={({ item }) => {
          const isSelected = selectedIds.includes(item.id);

          return (
            <Pressable style={[ styles.categoryButton, isSelected && styles.categoryButtonSelected, ]}
              disabled={saving || !preferencesLoaded} onPress={() => toggleInterest(item.id)} accessibilityRole="checkbox" accessibilityState={{ checked: isSelected, disabled: saving || !preferencesLoaded }}>
              <Text style={[ styles.categoryText, isSelected && styles.categoryTextSelected, ]}>
                {isSelected ? 'âœ“  ' : ''}
                {item.name}
              </Text>
            </Pressable>
          );
        }}
      />

      <Pressable style={[ styles.saveButton, !canContinue(selectedIds, preferencesLoaded, loading, saving) && styles.disabledButton, ]}
        onPress={saveInterests} disabled={!canContinue(selectedIds, preferencesLoaded, loading, saving)}>
        {saving ? (
          <ActivityIndicator color="#071E2A" />
        ) : (
          <Text style={styles.saveButtonText}>Continue</Text>
        )}
      </Pressable>

    </View>
  );
}
