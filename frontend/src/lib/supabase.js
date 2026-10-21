
import { createClient } from "@supabase/supabase-js";

const supabaseUrl = (import.meta.env.VITE_SUPABASE_URL || "").trim();
export const supabaseAnonKey = (
  import.meta.env.VITE_SUPABASE_ANON_KEY || ""
).trim();

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

export const supabaseConfigError =
  !supabaseUrl || !supabaseAnonKey
    ? "missing"
    : !isValidSupabaseUrl
      ? "invalid-url"
      : null;

if (supabaseConfigError === "missing") {
  console.error(
    "Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY. Set both in the frontend environment."
  );
} else if (supabaseConfigError === "invalid-url") {
  console.error(
    "VITE_SUPABASE_URL must be the HTTPS Supabase project URL without an API path."
  );
}

export const supabase =
  !supabaseConfigError
    ? createClient(supabaseUrl, supabaseAnonKey)
    : null;
