
import { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Animated, FlatList, Pressable, Text, View, } from 'react-native';
import { router } from 'expo-router';
import { authenticatedFetch } from '../../services/auth';
import styles from '../../styles/onboarding.styles';

type Interest = {
  id: string;
  name: string;
  taxonomy_version: string;
};

type InterestsResponse = { interests: Interest[]; };

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

      <Animated.View style={[styles.skeletonSkipButton, { opacity: shimmerOpacity }, ]} />
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

  useEffect(() => {
    async function loadInterests() 
    {
      try 
      {
        setLoading(true);
        setError('');

        const categoriesResponse = await authenticatedFetch('/onboarding/interests' );

        if (!categoriesResponse.ok) 
        {
          throw new Error('Could not load interest categories.');
        }

        const categoriesData: InterestsResponse = await categoriesResponse.json();

        setInterests(categoriesData.interests);

        const preferencesResponse = await authenticatedFetch('/users/me/interests');

        if (!preferencesResponse.ok) 
        {
          throw new Error('Could not load your saved interests.');
        }

        const preferencesData: InterestsResponse = await preferencesResponse.json();

        const savedIds: string[] = [];

        for (const interest of preferencesData.interests) 
        {
          savedIds.push(interest.id);
        }

        setSelectedIds(savedIds);
      } 
      catch (err) 
      {
        if (err instanceof Error) 
        {
          setError(err.message);
        } 
        else 
        {
          setError('Something went wrong while loading interests.');
        }
      } 
      finally 
      {
        setLoading(false);
      }
    }

    loadInterests();
  }, []);

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

  function skipOnboarding() 
  {
    router.replace('/(tabs)');
  }

  async function saveInterests() 
  {
    if (selectedIds.length === 0) 
    {
      setError('Please select at least one interest, or skip for now.');
      return;
    }

    try 
    {
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

      router.replace('/(tabs)');
    } 
    catch (err) 
    {
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
      setSaving(false);
    }
  }

  if (loading) 
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
        {selectedIds.length} selected
      </Text>

      {error !== '' && (
        <View style={styles.errorContainer}>
          <Text style={styles.errorText}>{error}</Text>

          <Pressable onPress={() => router.replace('/(onboarding)/interests')}>
            <Text style={styles.retryText}>Reload screen</Text>
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
              onPress={() => toggleInterest(item.id)} accessibilityRole="checkbox" accessibilityState={{ checked: isSelected }}>
              <Text style={[ styles.categoryText, isSelected && styles.categoryTextSelected, ]}>
                {isSelected ? '✓  ' : ''}
                {item.name}
              </Text>
            </Pressable>
          );
        }}
      />

      <Pressable style={[ styles.saveButton, (saving || interests.length === 0) && styles.disabledButton, ]}
        onPress={saveInterests} disabled={saving || interests.length === 0}>
        {saving ? (
          <ActivityIndicator color="#071E2A" />
        ) : (
          <Text style={styles.saveButtonText}>Save Interests</Text>
        )}
      </Pressable>

      <Pressable style={styles.skipButton} onPress={skipOnboarding} disabled={saving}>
        <Text style={styles.skipButtonText}>Skip for now</Text>
      </Pressable>
    </View>
  );
}
