import { apiFetch } from './request';
import { Platform } from 'react-native';
import * as SecureStore from 'expo-secure-store';

export class AuthenticationError extends Error { constructor(message: string) { super(message); this.name = 'AuthenticationError'; } }

const API_URL = process.env.EXPO_PUBLIC_API_URL;

export type SignupResponse = {
  message: string;
  user: {
    id: string;
    email: string;
  };
  requires_email_confirmation: boolean;
  access_token?: string;
  refresh_token?: string;
};

export type LoginResponse = {
  message: string;
  user: {
    id: string;
    email: string;
  };
  access_token: string;
  refresh_token: string;
  token_type?: string;
};

export type CurrentUser = {
  id: string;
  email: string;
};

export type RefreshResponse = {
  message: string;
  user: CurrentUser;
  access_token: string;
  refresh_token: string;
  token_type?: string;
};

const ACCESS_TOKEN_KEY = 'ataraxia_access_token';
const REFRESH_TOKEN_KEY = 'ataraxia_refresh_token';
let sessionGeneration = 0;
let refreshInFlight: Promise<string | null> | null = null;

export function refreshAccessToken(): Promise<string | null> {
  if (!refreshInFlight) refreshInFlight = performRefresh().finally(() => { refreshInFlight = null; });
  return refreshInFlight;
}

async function saveToken(key: string, value: string) 
{
  if (Platform.OS === 'web') 
  {
    sessionStorage.setItem(key, value);
  } 
  else 
  {
    await SecureStore.setItemAsync(key, value);
  }
}

async function getToken(key: string): Promise<string | null> 
{
  if (Platform.OS === 'web') 
  {
    return sessionStorage.getItem(key);
  }

  return await SecureStore.getItemAsync(key);
}

export async function saveSession( accessToken: string, refreshToken: string) 
{
  try 
  {
    const results = await Promise.allSettled([
      saveToken(ACCESS_TOKEN_KEY, accessToken), saveToken(REFRESH_TOKEN_KEY, refreshToken),
    ]);
    if (results.some(result => result.status === 'rejected')) throw new Error('Could not securely save your session.');
  } 
  catch (error) 
  {
    try 
    {
      await clearSession();
    } 
    catch 
    {
      
    }

    throw error;
  }
}

export async function getAccessToken(): Promise<string | null> 
{
  return await getToken(ACCESS_TOKEN_KEY);
}

async function getRefreshToken(): Promise<string | null> 
{
  return await getToken(REFRESH_TOKEN_KEY);
}

export async function clearSession() 
{
  sessionGeneration++;
  if (Platform.OS === 'web') 
  {
    sessionStorage.removeItem(ACCESS_TOKEN_KEY);
    sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  } 
  else 
  {
    await SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY);
    await SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY);
  }
}

async function performRefresh(): Promise<string | null>
{
  const generation = sessionGeneration;
  if (!API_URL) 
  {
    throw new Error('API address is not configured.');
  }

  const refreshToken = await getRefreshToken();

  if (!refreshToken) 
  {
    await clearSession();
    return null;
  }

  const response = await apiFetch(`${API_URL}/auth/refresh`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (response.status === 400 || response.status === 401) 
  {
    await clearSession();
    return null;
  }

  if (!response.ok) 
  {
    throw new Error('Could not refresh your session. Please try again.');
  }

  const data = (await response.json()) as RefreshResponse;

  if (!data.access_token || !data.refresh_token)
  {
    await clearSession();
    return null;
  }

  if (generation !== sessionGeneration) return null;
  await saveSession(data.access_token, data.refresh_token);

  return data.access_token;
}

let restoreInFlight: Promise<boolean> | null = null;
export function restoreSession(): Promise<boolean> {
  if (!restoreInFlight) restoreInFlight = performRestoreSession().finally(() => { restoreInFlight = null; });
  return restoreInFlight;
}

async function performRestoreSession(): Promise<boolean>
{
  if (!API_URL) 
  {
    throw new Error('API address is not configured.');
  }

  let accessToken = await getAccessToken();

  if (!accessToken) 
  {
    accessToken = await refreshAccessToken();
    if (!accessToken) return false;
  }

  const response = await apiFetch(`${API_URL}/auth/me`,
  {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: 'application/json',
    },
  });

  if (response.ok) 
  {
    return true;
  }

  if (response.status !== 401) 
  {
    throw new Error('Could not verify your session. Please try again.');
  }

  const newAccessToken = await refreshAccessToken();

  return newAccessToken !== null;
}

export async function authenticatedFetch( path: string, options: RequestInit = {} ): Promise<Response> {
  if (!API_URL) 
  {
    throw new Error('API address is not configured.');
  }

  let accessToken = await getAccessToken();

  if (!accessToken) 
  {
    accessToken = await refreshAccessToken();
  }

  if (!accessToken) 
  {
    throw new AuthenticationError('Your session has expired. Please log in again.');
  }

  const response = await apiFetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      ...(options.headers as Record<string, string> | undefined),
      Authorization: `Bearer ${accessToken}`,
    },
  });

  if (response.status !== 401) 
  {
    return response;
  }

  const latestToken = await getAccessToken();
  accessToken = latestToken && latestToken !== accessToken ? latestToken : await refreshAccessToken();

  if (!accessToken) 
  {
    throw new AuthenticationError('Your session has expired. Please log in again.');
  }

  const retried = await apiFetch(`${API_URL}${path}`,
  {
    ...options,
    headers: {
      ...(options.headers as Record<string, string> | undefined),
      Authorization: `Bearer ${accessToken}`,
    },
  });
  if (retried.status === 401) {
    await clearSession();
    throw new AuthenticationError('Your session has expired. Please log in again.');
  }
  return retried;
}

export async function signupUser( email: string, password: string ): Promise<SignupResponse> {
  if (!API_URL) 
  {
    throw new Error('API address is not configured.');
  }

  const response = await apiFetch(`${API_URL}/auth/signup`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ email, password }),
  });

  const data = await response.json();

  if (!response.ok) 
  {
    if (typeof data.detail === 'string') 
    {
      throw new Error(data.detail);
    }

    throw new Error('Signup failed. Please check your details.');
  }

  return data as SignupResponse;
}

export async function loginUser( email: string, password: string ): Promise<LoginResponse> {
  if (!API_URL) 
  {
    throw new Error('API address is not configured.');
  }

  const response = await apiFetch(`${API_URL}/auth/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    },
    body: JSON.stringify({ email, password }),
  });


  const data = await response.json();

  if (!response.ok) 
  {
    if (typeof data.detail === 'string') 
    {
      throw new Error(data.detail);
    }

    throw new Error('Login failed. Please check your credentials.');
  }

  return data as LoginResponse;
}

export async function getCurrentUser(): Promise<CurrentUser | null> 
{
  if (!API_URL) 
  {
    throw new Error('API address is not configured.');
  }

  let accessToken = await getAccessToken();

  if (!accessToken) 
  {
    accessToken = await refreshAccessToken();
  }

  if (!accessToken) 
  {
    return null;
  }

  let response = await apiFetch(`${API_URL}/auth/me`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
      Accept: 'application/json',
    },
  });

  if (response.status === 401) 
  {
    accessToken = await refreshAccessToken();

    if (!accessToken) 
    {
      return null;
    }

    response = await apiFetch(`${API_URL}/auth/me`, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        Accept: 'application/json',
      },
    });
  }

  if (response.status === 401) 
  {
    await clearSession();
    return null;
  }

  if (!response.ok) 
  {
    throw new Error('Could not retrieve your account information.');
  }

  return (await response.json()) as CurrentUser;
}
