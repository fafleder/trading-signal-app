export const SUPABASE_URL = process.env.REACT_APP_SUPABASE_URL;
export const SUPABASE_ANON_KEY = process.env.REACT_APP_SUPABASE_ANON_KEY;
export const SOCKET_URL = process.env.REACT_APP_SOCKET_URL;
export const X_INSIGHTS_URL = process.env.REACT_APP_X_INSIGHTS_URL;

if (!SUPABASE_URL || !SUPABASE_ANON_KEY || !SOCKET_URL || !X_INSIGHTS_URL) {
  throw new Error("Missing required environment variables for frontend config. Please check your .env file.");
}

export const SUPABASE_CONFIG = {
  url: SUPABASE_URL,
  anonKey: SUPABASE_ANON_KEY,
}; 