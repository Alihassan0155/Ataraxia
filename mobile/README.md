# Ataraxia Mobile

**Expo / React Native client for the Ataraxia short-video recommendation prototype.**

This application contains authentication screens, an onboarding interests flow, and a tabbed video-exploration interface. It is one component of the [Ataraxia system](../README.md), not a standalone production app.

## App modules

| Area | Location |
| --- | --- |
| Routing and screens | `src/app/` |
| Sign-in and sign-up | `src/app/(auth)/` |
| Preference onboarding | `src/app/(onboarding)/` |
| Home and Explore screens | `src/app/(tabs)/` |
| Video presentation | `src/components/feed-video.tsx` |
| API integration | `src/services/` |
| Theme and shared components | `src/constants/`, `src/components/`, `src/styles/` |
| Test scripts | `tests/` |

## Development

Requires Node.js and a compatible Expo environment.

```bash
cd mobile
npm install
npm run start
```

To open a specific platform, see `npm run android`, `npm run ios`, or `npm run web`. Platform behavior depends on installed tooling, OS support and package versions.

## Backend dependency

The client expects an appropriately configured Ataraxia API and external services. Review `src/services/request.ts`, `src/services/auth.ts`, and the [backend entrypoint](../backend/main.py) before connecting to any live service. Do not embed secrets in client code or commit local credentials.

## Validation

Some test files are included under `tests/`, but this README does not claim that the application was built, launched or tested as part of the documentation refresh.

This replaces the default Expo starter README with an accurate map of the tracked Ataraxia client code.
