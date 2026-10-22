import { supabase } from "./supabase";

export async function authenticatedFetch(input, init = {}) {
  if (!supabase) {
    throw new Error("Authentication is not configured. Please sign in again.");
  }

  const {
    data: { session: storedSession },
    error,
  } = await supabase.auth.getSession();

  if (error) {
    throw new Error(
      "Unable to read your sign-in session. Please sign in again and retry."
    );
  }

  let session = storedSession;

  if (!session?.access_token) {
    throw new Error("Your session has expired. Please sign in again.");
  }

  // Refresh a token that is expired or about to expire. This covers tabs that
  // were suspended while Supabase's background refresh timer was paused.
  const expiresAtMs = Number(session.expires_at || 0) * 1000;
  if (expiresAtMs && expiresAtMs <= Date.now() + 30_000) {
    const { data, error: refreshError } = await supabase.auth.refreshSession();
    if (refreshError || !data.session?.access_token) {
      throw new Error("Your session has expired. Please sign in again.");
    }
    session = data.session;
  }

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${session.access_token}`);

  return fetch(input, {
    ...init,
    headers,
  });
}
