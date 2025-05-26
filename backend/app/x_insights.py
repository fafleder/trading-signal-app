import os
import httpx
from fastapi import APIRouter, Query
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()

TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

if not TWITTER_BEARER_TOKEN:
    raise RuntimeError("Missing required environment variable: TWITTER_BEARER_TOKEN")
if not HUGGINGFACE_API_KEY:
    raise RuntimeError("Missing required environment variable: HUGGINGFACE_API_KEY")

async def fetch_tweets(query: str, max_results: int = 5):
    url = "https://api.twitter.com/2/tweets/search/recent"
    headers = {
        "Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"
    }
    params = {
        "query": query,
        "tweet.fields": "author_id,text,created_at",
        "expansions": "author_id",
        "user.fields": "username",
        "max_results": str(max_results)
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        users = {u["id"]: u["username"] for u in data.get("includes", {}).get("users", [])}
        tweets = []
        for t in data.get("data", []):
            tweets.append({
                "text": t["text"],
                "user": users.get(t["author_id"], "unknown"),
                "created_at": t["created_at"]
            })
        return tweets

async def get_insight_from_huggingface(tweets):
    if not HUGGINGFACE_API_KEY or not tweets:
        return "No insight available."
    prompt = (
        "You are a trading assistant. Given the following tweets from X (Twitter) about trading, "
        "summarize the most important insight or sentiment for a trader in 2-3 sentences.\n\n"
    )
    for t in tweets:
        prompt += f"- @{t['user']}: {t['text']}\n"
    headers = {
        "Authorization": f"Bearer {HUGGINGFACE_API_KEY}",
        "Content-Type": "application/json"
    }
    # Using facebook/bart-large-cnn for summarization (can be changed to another summarization model)
    json_data = {
        "inputs": prompt,
        "parameters": {"max_length": 120, "min_length": 30, "do_sample": False}
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api-inference.huggingface.co/models/facebook/bart-large-cnn",
            headers=headers,
            json=json_data
        )
        resp.raise_for_status()
        data = resp.json()
        # Hugging Face returns a list of dicts with 'summary_text'
        if isinstance(data, list) and "summary_text" in data[0]:
            return data[0]["summary_text"].strip()
        # If error or unexpected format
        return "No insight available."

@router.get("/x-insights")
async def get_x_insights(
    query: str = Query("ICT OR smart money concepts OR #ICTtrading OR #smc", description="Search query for X (Twitter)"),
    max_results: int = Query(5, ge=1, le=20, description="Number of tweets to fetch")
):
    tweets = await fetch_tweets(query, max_results)
    insight = await get_insight_from_huggingface(tweets)
    return {"insight": insight, "tweets": tweets} 