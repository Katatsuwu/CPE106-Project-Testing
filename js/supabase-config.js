// Public values only. Never put a service-role key or email-provider secret here.
export const supabaseUrl = "https://nxfjuteqdpdbhewixeyb.supabase.co";
// Public legacy anon JWT keeps Edge Function gateway JWT verification enabled.
export const supabaseAnonKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im54Zmp1dGVxZHBkYmhld2l4ZXliIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE1NjYyMzcsImV4cCI6MjEwNzE0MjIzN30.aYi_q-8qoRn4G1GtymuZVOC6I4mNgF1bIR5-uSvkBMg";
export const isSupabaseConfigured = supabaseUrl.startsWith("https://") && !!supabaseAnonKey && !supabaseAnonKey.startsWith("REPLACE_");
