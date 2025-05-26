import React, { useState, useEffect } from "react";
import { createClient } from "@supabase/supabase-js";
import { io } from "socket.io-client";
import Dashboard from "./components/Dashboard";
import XScrapingPage from "./components/XScrapingPage";
import { SUPABASE_URL, SUPABASE_ANON_KEY, SOCKET_URL } from "./config";
import { AuthProvider, useAuth } from "./AuthContext";
import toast, { Toaster } from "react-hot-toast";
import PortfolioTracker from "./components/PortfolioTracker";

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
const socket = io(SOCKET_URL);

function AuthUI() {
  const { user, loading, login, signup, logout } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [mode, setMode] = useState("login");
  const [submitting, setSubmitting] = useState(false);

  if (loading) return <div>Loading...</div>;
  if (user) {
    return (
      <div className="mb-4 p-4 bg-green-100 rounded flex flex-col gap-2">
        <div>Signed in as: <b>{user.email}</b></div>
        <button aria-label="Logout" onClick={() => { logout(); toast.success("Logged out"); }} className="bg-red-500 text-white p-2 rounded w-32">Logout</button>
      </div>
    );
  }
  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      if (mode === "login") {
        const { error } = await login(email, password);
        if (error) {
          setError(error.message);
          toast.error(error.message);
        } else {
          toast.success("Logged in!");
        }
      } else {
        const { error } = await signup(email, password);
        if (error) {
          setError(error.message);
          toast.error(error.message);
        } else {
          toast.success("Signup successful! Check your email for confirmation.");
        }
      }
    } catch (err) {
      setError(err.message);
      toast.error(err.message);
    } finally {
      setSubmitting(false);
    }
  };
  return (
    <form onSubmit={handleSubmit} className="mb-4 p-4 bg-gray-100 rounded flex flex-col gap-2 max-w-sm mx-auto" aria-label="Authentication form">
      <h2 className="text-xl font-bold mb-2">{mode === "login" ? "Login" : "Sign Up"}</h2>
      <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="Email" className="border p-2" required aria-label="Email" />
      <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Password" className="border p-2" required aria-label="Password" />
      <button type="submit" className="bg-blue-500 text-white p-2 rounded" disabled={submitting} aria-busy={submitting} aria-label={mode === "login" ? "Login" : "Sign Up"}>{submitting ? "Please wait..." : (mode === "login" ? "Login" : "Sign Up")}</button>
      <button type="button" onClick={() => setMode(mode === "login" ? "signup" : "login")}
        className="text-blue-500 underline mt-2" aria-label="Switch auth mode">
        {mode === "login" ? "Need an account? Sign Up" : "Already have an account? Login"}
      </button>
      {error && <div className="text-red-500">{error}</div>}
    </form>
  );
}

function AppContent() {
  const [marketData, setMarketData] = useState({ XAUUSD: [], NASDAQ: [] });
  const [signals, setSignals] = useState([]);
  const [metrics, setMetrics] = useState({});
  const [balance, setBalance] = useState("");
  const [risk, setRisk] = useState("");
  const [timeframe, setTimeframe] = useState("1h");
  const [selectedSignal, setSelectedSignal] = useState(null);
  const [activeTab, setActiveTab] = useState("dashboard");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const { user } = useAuth();
  const [showMA, setShowMA] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    setError("");
    try {
      const { data: market, error: marketError } = await supabase
        .from("market_data")
        .select("*")
        .in("asset", ["XAUUSD", "NASDAQ"])
        .eq("timeframe", timeframe)
        .order("timestamp", { ascending: false })
        .limit(100);
      if (marketError) throw marketError;

      const { data: signals, error: signalsError } = await supabase
        .from("trade_signals")
        .select("*")
        .order("timestamp", { ascending: false })
        .limit(10);
      if (signalsError) throw signalsError;

      const { data: metrics, error: metricsError } = await supabase
        .from("portfolio_metrics")
        .select("*")
        .single();
      if (metricsError) throw metricsError;

      setMarketData({
        XAUUSD: (market || []).filter((d) => d.asset === "XAUUSD"),
        NASDAQ: (market || []).filter((d) => d.asset === "NASDAQ"),
      });
      setSignals(signals || []);
      setMetrics(metrics || {});
    } catch (err) {
      setError(err.message || "Failed to fetch data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    socket.on("marketData", (data) => setMarketData(data));
    socket.on("newSignal", (signal) => setSignals((prev) => [signal, ...prev]));
    return () => {
      socket.off("marketData");
      socket.off("newSignal");
    };
  }, []);

  useEffect(() => {
    // Load user settings from localStorage
    const savedTimeframe = localStorage.getItem("preferred_timeframe");
    const savedRisk = localStorage.getItem("preferred_risk");
    if (savedTimeframe) setTimeframe(savedTimeframe);
    if (savedRisk) setRisk(savedRisk);
  }, []);

  const saveSettings = () => {
    localStorage.setItem("preferred_timeframe", timeframe);
    localStorage.setItem("preferred_risk", risk);
    setError("");
    toast.success("Settings saved!");
  };

  // Chart data and options
  const chartData = (asset) => {
    const data = marketData[asset] || [];
    return {
      datasets: [
        {
          label: asset,
          data: data.map((d) => ({
            x: new Date(d.timestamp),
            o: d.open,
            h: d.high,
            l: d.low,
            c: d.close,
          })),
          type: "candlestick",
          borderColor: "#333",
          borderWidth: 1,
        },
      ],
    };
  };

  const chartOptions = (asset) => {
    const data = marketData[asset] || [];
    const annotations = {};
    data.forEach((d, i) => {
      if (d.liquidity_zones) {
        const [yMin, yMax] = d.liquidity_zones.split("-").map(Number);
        annotations[`liq${i}`] = {
          type: "box",
          xMin: i - 0.5,
          xMax: i + 0.5,
          yMin,
          yMax,
          backgroundColor: "rgba(255, 99, 132, 0.2)",
          borderColor: "rgba(255, 99, 132, 1)",
        };
      }
    });
    return {
      plugins: {
        annotation: { annotations },
        legend: { display: false },
      },
      scales: {
        x: { type: "time", time: { unit: "minute" } },
        y: { beginAtZero: false },
      },
      responsive: true,
      maintainAspectRatio: false,
    };
  };

  // Compute 20-period SMA for each asset
  function computeSMA(data, period = 20) {
    if (!data || data.length < period) return [];
    const sma = [];
    for (let i = 0; i < data.length; i++) {
      if (i < period - 1) {
        sma.push(null);
      } else {
        const sum = data.slice(i - period + 1, i + 1).reduce((acc, d) => acc + d.close, 0);
        sma.push({ x: new Date(data[i].timestamp), y: sum / period });
      }
    }
    return sma;
  }

  const handleBalanceChange = (val) => {
    if (val === "" || (Number(val) >= 0 && Number(val) <= 10000000)) {
      setBalance(val);
    } else {
      setError("Balance must be a positive number");
    }
  };
  const handleRiskChange = (val) => {
    if (val === "" || (Number(val) > 0 && Number(val) <= 100)) {
      setRisk(val);
    } else {
      setError("Risk must be between 0 and 100");
    }
  };

  return (
    <div className="container mx-auto p-4 max-w-5xl w-full">
      <AuthUI />
      <div className="flex flex-wrap gap-2 mb-4">
        <button
          onClick={() => setActiveTab("dashboard")}
          className={`p-2 rounded w-full sm:w-auto ${activeTab === "dashboard" ? "bg-blue-500 text-white" : "bg-gray-200"}`}
        >
          Dashboard
        </button>
        <button
          onClick={() => setActiveTab("x-insights")}
          className={`p-2 rounded w-full sm:w-auto ${activeTab === "x-insights" ? "bg-blue-500 text-white" : "bg-gray-200"}`}
        >
          X Insights
        </button>
        <button
          onClick={fetchData}
          className="bg-blue-500 text-white p-2 rounded"
          aria-label="Refresh Data"
          disabled={loading}
        >
          {loading ? "Refreshing..." : "Refresh Data"}
        </button>
        <button
          onClick={() => setShowMA((v) => !v)}
          className="p-2 rounded bg-orange-500 text-white w-full sm:w-auto"
        >
          {showMA ? "Hide MA(20)" : "Show MA(20)"}
        </button>
        <button
          onClick={saveSettings}
          className="p-2 rounded bg-green-500 text-white w-full sm:w-auto"
          aria-label="Save Settings"
          disabled={loading}
        >
          Save Settings
        </button>
      </div>
      {activeTab === "dashboard" ? (
        <>
          <Dashboard
            marketData={marketData}
            signals={signals}
            metrics={metrics}
            balance={balance}
            setBalance={handleBalanceChange}
            risk={risk}
            setRisk={handleRiskChange}
            timeframe={timeframe}
            setTimeframe={setTimeframe}
            fetchData={fetchData}
            selectedSignal={selectedSignal}
            setSelectedSignal={setSelectedSignal}
            chartData={chartData}
            chartOptions={chartOptions}
            loading={loading}
            error={error}
            movingAverages={showMA ? {
              XAUUSD: computeSMA(marketData.XAUUSD),
              NASDAQ: computeSMA(marketData.NASDAQ),
            } : {}}
          />
          <PortfolioTracker balance={balance} risk={risk} signals={signals} />
        </>
      ) : (
        <XScrapingPage />
      )}
    </div>
  );
}

function App() {
  return (
    <AuthProvider>
      <Toaster position="top-right" />
      <AppContent />
    </AuthProvider>
  );
}

export default App; 