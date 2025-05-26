import React, { useState } from "react";

function calcPnL(entry, exit, size, direction) {
  if (!entry || !exit || !size) return 0;
  return direction === "long"
    ? (exit - entry) * size
    : (entry - exit) * size;
}

export default function PortfolioTracker({ balance, risk, signals }) {
  const [simEntry, setSimEntry] = useState("");
  const [simExit, setSimExit] = useState("");
  const [simSize, setSimSize] = useState(1);
  const [simDirection, setSimDirection] = useState("long");
  const [simResult, setSimResult] = useState(null);

  // Calculate running P&L and equity curve
  let equity = Number(balance) || 0;
  const equityCurve = [equity];
  (signals || []).forEach((s) => {
    if (s.entry_price && s.take_profit && s.stop_loss) {
      // Simulate a win/loss (for demo, assume TP hit if bias is bullish, SL if bearish)
      const win = s.bias === "bullish";
      const result = win
        ? calcPnL(s.entry_price, s.take_profit, 1, "long")
        : calcPnL(s.entry_price, s.stop_loss, 1, "long");
      equity += result;
      equityCurve.push(equity);
    }
  });

  const handleSimulate = (e) => {
    e.preventDefault();
    const pnl = calcPnL(Number(simEntry), Number(simExit), Number(simSize), simDirection);
    setSimResult(pnl);
  };

  return (
    <div className="my-8 p-4 bg-gray-50 rounded shadow">
      <h2 className="text-2xl font-bold mb-4">Portfolio Tracker</h2>
      <div className="mb-4 flex flex-wrap gap-4">
        <div>Current Balance: <b>${Number(balance).toLocaleString()}</b></div>
        <div>Risk: <b>{risk}%</b></div>
        <div>Trades: <b>{signals.length}</b></div>
        <div>P&L: <b>{(equity - (Number(balance) || 0)).toFixed(2)}</b></div>
      </div>
      <form onSubmit={handleSimulate} className="flex flex-wrap gap-2 mb-4 items-end">
        <div>
          <label className="block text-xs">Entry</label>
          <input type="number" value={simEntry} onChange={e => setSimEntry(e.target.value)} className="border p-1 w-24" />
        </div>
        <div>
          <label className="block text-xs">Exit</label>
          <input type="number" value={simExit} onChange={e => setSimExit(e.target.value)} className="border p-1 w-24" />
        </div>
        <div>
          <label className="block text-xs">Size</label>
          <input type="number" value={simSize} min={0.01} step={0.01} onChange={e => setSimSize(e.target.value)} className="border p-1 w-20" />
        </div>
        <div>
          <label className="block text-xs">Direction</label>
          <select value={simDirection} onChange={e => setSimDirection(e.target.value)} className="border p-1">
            <option value="long">Long</option>
            <option value="short">Short</option>
          </select>
        </div>
        <button type="submit" className="bg-blue-500 text-white p-2 rounded">Simulate Trade</button>
        {simResult !== null && (
          <div className="ml-4">Simulated P&L: <b>{simResult.toFixed(2)}</b></div>
        )}
      </form>
      <div className="overflow-x-auto mb-4">
        <table className="min-w-full text-xs border">
          <thead>
            <tr className="bg-gray-200">
              <th className="p-2 border">Asset</th>
              <th className="p-2 border">System</th>
              <th className="p-2 border">Entry</th>
              <th className="p-2 border">SL</th>
              <th className="p-2 border">TP</th>
              <th className="p-2 border">Bias</th>
              <th className="p-2 border">Time</th>
            </tr>
          </thead>
          <tbody>
            {(signals || []).map((s, i) => (
              <tr key={i} className="odd:bg-white even:bg-gray-100">
                <td className="p-2 border">{s.asset}</td>
                <td className="p-2 border">{s.system}</td>
                <td className="p-2 border">{s.entry_price}</td>
                <td className="p-2 border">{s.stop_loss}</td>
                <td className="p-2 border">{s.take_profit}</td>
                <td className="p-2 border">{s.bias}</td>
                <td className="p-2 border">{s.timestamp ? new Date(s.timestamp).toLocaleString() : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="my-4">
        <h3 className="font-bold mb-2">Equity Curve</h3>
        <svg width="100%" height="120" viewBox="0 0 400 120">
          <polyline
            fill="none"
            stroke="#3b82f6"
            strokeWidth="2"
            points={equityCurve.map((v, i) => `${(i / (equityCurve.length - 1 || 1)) * 400},${120 - (v - Math.min(...equityCurve)) / ((Math.max(...equityCurve) - Math.min(...equityCurve) || 1) / 100)}`).join(" ")}
          />
        </svg>
      </div>
    </div>
  );
} 