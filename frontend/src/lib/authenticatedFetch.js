import { supabase } from "./supabase";

export async function authenticatedFetch(input, init = {}) {
  if (!supabase) {
    throw new Error("Authentication is not configured. Please sign in again.");
  }

  const {
    data: { session },
    error,
  } = await supabase.auth.getSession();

  if (error || !session?.access_token) {
    throw new Error("Your session has expired. Please sign in again.");
  }

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${session.access_token}`);

  return fetch(input, {
    ...init,
    headers,
  });
}
