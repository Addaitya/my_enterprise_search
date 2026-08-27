export const config = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL ?? '/api',
  keycloakUrl: import.meta.env.VITE_KEYCLOAK_URL ?? 'http://localhost:8080',
  keycloakRealm: import.meta.env.VITE_KEYCLOAK_REALM ?? 'enterprise-search-realm',
  keycloakClientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? 'web-client',
} as const
