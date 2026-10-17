import { createClient } from "@supabase/supabase-js";
import type { SupabaseClient } from "@supabase/supabase-js";

const rawSupabaseUrl = import.meta.env["VITE_SUPABASE_URL"];
const supabaseAnonKey = import.meta.env["VITE_SUPABASE_ANON_KEY"];

function normalizeProjectUrl(value: string): string | null {
  try {
    const url = new URL(value.trim());
    if (
      (url.protocol !== "https:" && url.hostname !== "localhost" && url.hostname !== "127.0.0.1") ||
      (url.protocol !== "https:" && url.protocol !== "http:")
    ) {
      throw new Error("Supabase URL must use HTTPS outside localhost.");
    }
    url.pathname = url.pathname.replace(/\/rest\/v1\/?$/i, "").replace(/\/+$/, "");
    url.search = "";
    url.hash = "";
    return url.toString().replace(/\/$/, "");
  } catch (cause) {
    if (cause instanceof TypeError) return null;
    throw cause;
  }
}

const supabaseUrl =
  typeof rawSupabaseUrl === "string" && rawSupabaseUrl.trim()
    ? normalizeProjectUrl(rawSupabaseUrl)
    : null;
export const supabase: SupabaseClient | null =
  supabaseUrl &&
  typeof supabaseAnonKey === "string" &&
  supabaseAnonKey.trim().length > 0 &&
  !supabaseAnonKey.includes("SET_YOUR_")
    ? createClient(supabaseUrl, supabaseAnonKey)
    : null;
