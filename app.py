import feedparser
import pandas as pd
import re
from datetime import datetime, timedelta
import streamlit as st  

st.set_page_config(page_title="NFL News", layout="wide")  
st.title("NFL News Dashboard")  


# List of NFL teams for matching (full names for accuracy)
nfl_teams = [
    'Arizona Cardinals', 'Atlanta Falcons', 'Baltimore Ravens', 'Buffalo Bills',
    'Carolina Panthers', 'Chicago Bears', 'Cincinnati Bengals', 'Cleveland Browns',
    'Dallas Cowboys', 'Denver Broncos', 'Detroit Lions', 'Green Bay Packers',
    'Houston Texans', 'Indianapolis Colts', 'Jacksonville Jaguars', 'Kansas City Chiefs',
    'Las Vegas Raiders', 'Los Angeles Chargers', 'Los Angeles Rams', 'Miami Dolphins',
    'Minnesota Vikings', 'New England Patriots', 'New Orleans Saints', 'New York Giants',
    'New York Jets', 'Philadelphia Eagles', 'Pittsburgh Steelers', 'San Francisco 49ers',
    'Seattle Seahawks', 'Tampa Bay Buccaneers', 'Tennessee Titans', 'Washington Commanders'
]

# RSS feeds for NFL news (free and public)
rss_feeds = [
    "https://www.nfl.com/feeds/rss/home",
    "https://www.espn.com/espn/rss/nfl/news",
    "https://www.foxsports.com/nfl/rss",
    "https://bleacherreport.com/articles/feed/tag/nfl",
    "https://www.rotowire.com/rss/news.htm?type=news&sport=nfl",  # Adjusted for RotoWire NFL
    "https://www.cbssports.com/rss/headlines/nfl/"
]

# Function to extract team from text (case-insensitive regex match)
def extract_team(text):
    for team in nfl_teams:
        if re.search(r'\b' + re.escape(team) + r'\b', text, re.IGNORECASE):
            return team
    return 'General'  # Default if no team match

# Fetch and aggregate news, filtering for last 7 days
news_items = []
seven_days_ago = datetime.now() - timedelta(days=7)  # Use datetime.now() for current time; adjust if testing specific date

for feed_url in rss_feeds:
    feed = feedparser.parse(feed_url)
    source = feed.feed.get('title', feed_url)  # Get source name or fallback to URL
    
    for entry in feed.entries[:50]:  # Increase limit to 50 per feed to capture more potential recent items
        title = entry.get('title', 'No Title')
        link = entry.get('link', '')
        summary = entry.get('summary', '')[:300]  # Truncate summary
        published = entry.get('published', '')
        
        # Try to parse published date
        try:
            published_parsed = datetime.fromtimestamp(feedparser._parse_date(published))
        except:
            published_parsed = datetime.now()  # Fallback
        
        # Filter: Only include if within last 7 days
        if published_parsed < seven_days_ago:
            continue  # Skip old entries
        
        # Combine title and summary for extractions
        full_text = title + ' ' + summary
        team = extract_team(full_text)
        
        news_items.append({
            'team': team,
            'link': link,
            'headline': title,
            '_published_parsed': published_parsed  # For sorting
        })

# Create master DataFrame
df_news = pd.DataFrame(news_items)

# Sort by published date (newest first) and drop temp column
df_news = df_news.sort_values(by='_published_parsed', ascending=False).drop(columns=['_published_parsed'])

st.dataframe(df_news).
