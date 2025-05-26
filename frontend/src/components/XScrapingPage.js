import React, { useState, useEffect } from "react";
import { X_INSIGHTS_URL } from "../config";

const DEFAULT_QUERY = "ICT OR smart money concepts OR #ICTtrading OR #smc";

const XScrapingPage = () => {
  const [tweets, setTweets] = useState([]);
  const [insight, setInsight] = useState("");
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [maxResults, setMaxResults] = useState(5);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const fetchTweets = async (customQuery = query, customMaxResults = maxResults) => {
    setLoading(true);
    setError("");
    try {
      const url = `${X_INSIGHTS_URL}?query=${encodeURIComponent(customQuery)}&max_results=${customMaxResults}`;
      const response = await fetch(url);
      if (!response.ok) throw new Error("Failed to fetch insights");
      const data = await response.json();
      setInsight(data.insight);
      setTweets(data.tweets);
    } catch (err) {
      setError("Could not fetch X insights. Please try again later.");
      setInsight("");
      setTweets([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTweets();
    // Optionally, refresh every 5 minutes
    const interval = setInterval(() => fetchTweets(), 300000);
    return () => clearInterval(interval);
    // eslint-disable-next-line
  }, []);

  const handleSubmit = (e) => {
    e.preventDefault();
    fetchTweets(query, maxResults);
  };

  return (
    <div className="p-4 max-w-2xl mx-auto">
      <h2 className="text-xl font-bold mb-4">ICT Trader Insights from X</h2>
      <form onSubmit={handleSubmit} className="flex flex-col md:flex-row gap-2 mb-4">
        <input
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          className="border p-2 flex-1"
          placeholder="Enter search query (e.g. ICT, SMC, #trading)"
        />
        <input
          type="number"
          min={1}
          max={20}
          value={maxResults}
          onChange={e => setMaxResults(Number(e.target.value))}
          className="border p-2 w-24"
          placeholder="Max Results"
        />
        <button type="submit" className="bg-blue-500 text-white p-2 rounded min-w-[100px]">Search</button>
      </form>
      {loading && <div className="mb-4 text-blue-500">Loading insights...</div>}
      {error && <div className="mb-4 text-red-500">{error}</div>}
      {insight && (
        <div className="mb-6 p-4 bg-yellow-100 border-l-4 border-yellow-500 text-yellow-900 rounded">
          <strong>AI Insight:</strong> {insight}
        </div>
      )}
      <ul>
        {tweets.map((tweet, i) => (
          <li key={i} className="mb-4 p-3 border rounded bg-gray-50">
            <div className="mb-1 text-gray-700">{tweet.text}</div>
            <div className="text-xs text-gray-500">@{tweet.user} &middot; {new Date(tweet.created_at).toLocaleString()}</div>
          </li>
        ))}
      </ul>
      {!loading && tweets.length === 0 && !error && (
        <div className="text-gray-500">No tweets found for this query.</div>
      )}
    </div>
  );
};

export default XScrapingPage; 