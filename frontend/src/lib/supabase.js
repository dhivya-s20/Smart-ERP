
import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
export const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

const isValidSupabaseUrl = (() => {
  if (!supabaseUrl) return false;

  try {
    const url = new URL(supabaseUrl);
    const isLocalDevelopment =
      import.meta.env.DEV &&
      ["localhost", "127.0.0.1"].includes(url.hostname) &&
      url.protocol === "http:";

    return (
      (url.protocol === "https:" || isLocalDevelopment) &&
      url.pathname === "/" &&
      !url.search &&
      !url.hash
    );
  } catch {
    return false;
  }
})();

if (!supabaseUrl || !supabaseAnonKey) {
  console.error(
    "Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY. Set both in the frontend environment."
  );
} else if (!isValidSupabaseUrl) {
  console.error(
    "VITE_SUPABASE_URL must be the HTTPS Supabase project URL without an API path."
  );
}

export const supabase =
  isValidSupabaseUrl && supabaseAnonKey
    ? createClient(supabaseUrl, supabaseAnonKey)
    : null;
