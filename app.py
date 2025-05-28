import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, timezone
import praw
import plotly.express as px
import requests
from textblob import TextBlob
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import os
from dotenv import load_dotenv

load_dotenv()


# --- Streamlit UI Configuration ---
st.set_page_config(page_title="Mention Tracker", layout="wide")
st.title("\U0001F4C8 Company/Person Mention Tracker (Reddit + Hacker News)")

search_term = st.text_input("Enter a company or person's name")
granularity = st.selectbox("Granularity", ["Daily", "Hourly"])
run_search = st.button("Track Mentions (Last 7 Days)")

# --- Reddit API Setup ---
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET")
REDDIT_USER_AGENT = "mention_tracker_app"
REDDIT_PASSWORD = os.getenv("REDDIT_PASSWORD")
REDDIT_USERNAME = os.getenv("REDDIT_USERNAME")

@st.cache_data(show_spinner=False)
def get_reddit_mentions(query, days=7, min_upvotes = 0):
    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        password=REDDIT_PASSWORD,
        user_agent=REDDIT_USER_AGENT,
        username=REDDIT_USERNAME,
    )

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    posts = []

    try:
        related_subs = [sr.display_name for sr in reddit.subreddits.search_by_name(query)]
        for sub in related_subs:
            for submission in reddit.subreddit(sub).new():
                created = datetime.fromtimestamp(submission.created_utc, tz=timezone.utc)
                if start_date <= created <= end_date and submission.score >= min_upvotes:
                    text = (submission.title + " " + (submission.selftext or "")).lower()
                    if query.lower() in text:
                        posts.append({
                            "date": created,
                            "source": "Reddit",
                            "title": submission.title,
                            "content": submission.selftext or "",
                            "sentiment": TextBlob(submission.title + " " + (submission.selftext or "")).sentiment.polarity
                        })
    except Exception as e:
        st.error(f"Failed to fetch data from Reddit: {e}")
        return pd.DataFrame()

    return pd.DataFrame(posts)

@st.cache_data(show_spinner=False)
def get_hn_mentions(query, days=7):
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)
    posts = []

    try:
        url = f"https://hn.algolia.com/api/v1/search_by_date?query={query}&tags=story"
        response = requests.get(url)
        data = response.json()

        for item in data.get("hits", []):
            created = datetime.fromtimestamp(item["created_at_i"], tz=timezone.utc)
            if start_date <= created <= end_date:
                posts.append({
                    "date": created,
                    "source": "Hacker News",
                    "title": item.get("title", ""),
                    "content": item.get("story_text", "") or "",
                    "sentiment": TextBlob(item.get("title", "") + " " + (item.get("story_text", "") or "")).sentiment.polarity
                })
    except Exception as e:
        st.error(f"Failed to fetch data from Hacker News: {e}")
        return pd.DataFrame()

    return pd.DataFrame(posts)

if run_search and search_term:
    with st.spinner("\U0001F50E Fetching data from Reddit and Hacker News..."):
        df_reddit = get_reddit_mentions(search_term)
        df_hn = get_hn_mentions(search_term)
        df_all = pd.concat([df_reddit, df_hn], ignore_index=True)

    if df_all.empty:
        st.warning("No mentions found in the last 7 days.")
    else:
        # Apply time granularity
        df_all["time_bucket"] = df_all["date"].dt.floor("H" if granularity == "Hourly" else "D")

        # Count mentions by time and source
        mention_counts = df_all.groupby(['time_bucket', 'source']).size().reset_index(name='mentions')
        total_mentions = df_all.groupby('time_bucket').size().reset_index(name='total_mentions')

        # Sentiment label
        df_all['sentiment_label'] = pd.cut(df_all['sentiment'], bins=[-1, -0.05, 0.05, 1], labels=['Negative', 'Neutral', 'Positive'])

        # Sentiment trend over time
        sentiment_trend = df_all.groupby('time_bucket')['sentiment'].mean().reset_index()
        fig_sentiment_trend = px.line(sentiment_trend, x='time_bucket', y='sentiment', markers=True, title='Average Sentiment Over Time')

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("\U0001F4CA Mentions Over Time by Source")
            fig1 = px.bar(mention_counts, x="time_bucket", y="mentions", color="source",
                         title="Mentions by Source", barmode="group")
            st.plotly_chart(fig1, use_container_width=True)

        with col2:
            st.subheader("\U0001F4CA Total Mentions Over Time")
            fig2 = px.line(total_mentions, x="time_bucket", y="total_mentions", markers=True,
                          title="Total Mentions (All Sources)")
            st.plotly_chart(fig2, use_container_width=True)
        
                # Sentiment Trend
        st.subheader("\U0001F440 Sentiment Trend Over Time")
        st.plotly_chart(fig_sentiment_trend, use_container_width=True)

        # Word Cloud
        st.subheader("\U0001F5BC Top Keywords")
        all_text = " ".join((df_all["title"] + " " + df_all["content"]).fillna("").values)
        wordcloud = WordCloud(width=800, height=400, background_color='white').generate(all_text)
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.imshow(wordcloud, interpolation='bilinear')
        ax.axis('off')
        st.pyplot(fig)

        # Sentiment Overview
        st.subheader("\U0001F600 Sentiment Distribution")
        df_all['sentiment_label'] = pd.cut(df_all['sentiment'], bins=[-1, -0.05, 0.05, 1], labels=['Negative', 'Neutral', 'Positive'])
        sentiment_counts = df_all['sentiment_label'].value_counts().reset_index()
        sentiment_counts.columns = ['sentiment_label', 'count']  # rename columns
        fig_sentiment = px.pie(sentiment_counts, names='sentiment_label', values='count', title='Sentiment Breakdown')
        st.plotly_chart(fig_sentiment)

        # Data export
        st.download_button("Download CSV", df_all.to_csv(index=False), "mentions.csv")

        st.subheader("\U0001F4C4 Sample Posts")
        st.dataframe(df_all.head(10))