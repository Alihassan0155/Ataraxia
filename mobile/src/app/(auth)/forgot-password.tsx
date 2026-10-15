
import { StyleSheet, Text, View } from 'react-native';

export default function ForgotPasswordScreen() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>Reset Password</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#071E2A',
    justifyContent: 'center',
    alignItems: 'center',
  },
  title: {
    color: '#5DE5E0',
    fontSize: 28,
    fontWeight: 'bold',
  },
});
