import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { supabaseUrl, supabaseAnonKey, isSupabaseConfigured } from "./supabase-config.js";

export { isSupabaseConfigured };
export const supabase = isSupabaseConfigured ? createClient(supabaseUrl, supabaseAnonKey) : null;
export const signInWithEmailAndPassword = (email, password) => supabase.auth.signInWithPassword({ email, password });
export const signOut = () => supabase.auth.signOut();
export const onAuthStateChanged = callback => supabase.auth.onAuthStateChange((_event, session) => callback(session?.user || null));
export async function call(name, data = {}) {
  const { data: result, error } = await supabase.functions.invoke("api", { body: { action: name, ...data } });
  if (error) {
    let detail = "";
    try { detail = (await error.context.clone().json())?.error || ""; } catch {}
    throw new Error(detail || error.message || "The server request failed.");
  }
  if (result?.error) throw new Error(result.error);
  return { data: result };
}
const manilaDate = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Manila", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
export async function listenPublicQueue(next, error) {
  const refresh = async () => {
    const { data, error: queryError } = await supabase.from("queue_public").select("id,queue_number,service,service_window,status,created_at,date_key").eq("date_key", manilaDate()).order("created_at", { ascending: false }).limit(60);
    if (queryError) return error(queryError);
    next((data || []).map(row => ({ id: row.id, queueNumber: row.queue_number, service: row.service, window: row.service_window, status: row.status, createdAt: row.created_at, dateKey: row.date_key })));
  };
  await refresh();
  return supabase.channel("public-queue-today").on("postgres_changes", { event: "*", schema: "public", table: "queue_public", filter: `date_key=eq.${manilaDate()}` }, refresh).subscribe(status => { if (status === "CHANNEL_ERROR" || status === "TIMED_OUT") error(new Error(status)); });
}
