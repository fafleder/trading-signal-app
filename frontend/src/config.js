export const SUPABASE_URL = process.env.REACT_APP_SUPABASE_URL || "https://rzrbxahpanvmtuyfxfpy.supabase.co";
export const SUPABASE_ANON_KEY = process.env.REACT_APP_SUPABASE_ANON_KEY || "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJ6cmJ4YWhwYW52bXR1eWZ4ZnB5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDgyNzM2NzIsImV4cCI6MjA2Mzg0OTY3Mn0.qGnuUmqU_Zlyu4eiIoMGQGVK6MAVufkt1zRk57ZeiB0";
export const SOCKET_URL = process.env.REACT_APP_SOCKET_URL || "http://localhost:5000";
export const X_INSIGHTS_URL = process.env.REACT_APP_X_INSIGHTS_URL;

if (!SUPABASE_URL || !SUPABASE_ANON_KEY || !SOCKET_URL || !X_INSIGHTS_URL) {
  throw new Error("Missing required environment variables for frontend config. Please check your .env file.");
}

export const SUPABASE_CONFIG = {
  url: SUPABASE_URL,
  anonKey: SUPABASE_ANON_KEY,
}; 