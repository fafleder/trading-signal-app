import React from "react";
import ChartComponent from "./ChartComponent";
import SignalModal from "./SignalModal";

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"];

function toCSV(data) {
  if (!data || !data.length) return "";
  const keys = Object.keys(data[0]);
  const rows = data.map(row => keys.map(k => JSON.stringify(row[k] ?? "")).join(","));
  return keys.join(",") + "\n" + rows.join("\n");
}

function download(filename, content, type = "text/csv") {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

const Dashboard = ({
  marketData,
  signals,
  metrics,
  balance,
  setBalance,
  risk,
  setRisk,
  timeframe,
  setTimeframe,
  fetchData,
  selectedSignal,
  setSelectedSignal,
  chartData,
  chartOptions,
  loading,
  error,
  movingAverages = {}
}) => (
  <>
    <h1 className="text-3xl font-bold mb-4">Trading Dashboard</h1>
    {loading && <div className="mb-4 text-blue-500">Loading data...</div>}
    {error && <div className="mb-4 text-red-500">{error}</div>}
    <div className="flex gap-2 mb-4 flex-wrap">
      <input
        type="number"
        value={balance}
        onChange={(e) => setBalance(e.target.value)}
        className="border p-2"
        placeholder="Enter Balance ($)"
      />
      <input
        type="number"
        value={risk}
        onChange={(e) => setRisk(e.target.value)}
        className="border p-2"
        placeholder="Enter Risk % (e.g., 1.5)"
      />
      <select
        value={timeframe}
        onChange={(e) => setTimeframe(e.target.value)}
        className="border p-2"
      >
        {TIMEFRAMES.map((tf) => (
          <option key={tf} value={tf}>
            {tf}
          </option>
        ))}
      </select>
      <button onClick={fetchData} className="bg-blue-500 text-white p-2 rounded">
        Refresh Data
      </button>
      <button
        onClick={() => download("signals.csv", toCSV(signals))}
        className="bg-green-500 text-white p-2 rounded"
      >
        Export Signals (CSV)
      </button>
      <button
        onClick={() => download("signals.json", JSON.stringify(signals, null, 2), "application/json")}
        className="bg-green-500 text-white p-2 rounded"
      >
        Export Signals (JSON)
      </button>
      <button
        onClick={() => download("metrics.csv", toCSV([metrics]))}
        className="bg-purple-500 text-white p-2 rounded"
      >
        Export Metrics (CSV)
      </button>
      <button
        onClick={() => download("metrics.json", JSON.stringify(metrics, null, 2), "application/json")}
        className="bg-purple-500 text-white p-2 rounded"
      >
        Export Metrics (JSON)
      </button>
    </div>
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4" style={{ minHeight: 400 }}>
      <div>
        <h2 className="text-xl">XAUUSD Chart</h2>
        <ChartComponent data={chartData("XAUUSD")} options={chartOptions("XAUUSD")} movingAverage={movingAverages.XAUUSD || []} />
      </div>
      <div>
        <h2 className="text-xl">NASDAQ Chart</h2>
        <ChartComponent data={chartData("NASDAQ")} options={chartOptions("NASDAQ")} movingAverage={movingAverages.NASDAQ || []} />
      </div>
      <div>
        <h2 className="text-xl">Signals</h2>
        <ul>
          {signals.map((s, i) => (
            <li key={i} className="mb-2">
              {s.asset} ({s.system}): {s.entry_price} (SL: {s.stop_loss}, TP: {s.take_profit}, Invalidation: {s.invalidation_point})
              <button onClick={() => setSelectedSignal(s)} className="ml-2 text-blue-500">
                Details
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h2 className="text-xl">Metrics</h2>
        <p>Risk-Reward: {metrics.risk_reward_ratio || "N/A"}</p>
        <p>Win Rate: {metrics.win_rate || "N/A"}%</p>
        <p>Drawdown: {metrics.drawdown || "N/A"}%</p>
      </div>
    </div>
    {selectedSignal && (
      <SignalModal signal={selectedSignal} onClose={() => setSelectedSignal(null)} />
    )}
  </>
);

export default Dashboard; 