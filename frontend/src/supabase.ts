import { createClient } from "@supabase/supabase-js";

const rawSupabaseUrl = import.meta.env["VITE_SUPABASE_URL"];
const supabaseAnonKey = import.meta.env["VITE_SUPABASE_ANON_KEY"];

if (typeof rawSupabaseUrl !== "string" || typeof supabaseAnonKey !== "string") {
  throw new Error("Supabase URL and anonymous key must be configured.");
}

const supabaseUrl = rawSupabaseUrl.replace(/\/rest\/v1\/?$/i, "").replace(/\/$/, "");

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
