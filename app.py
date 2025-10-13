import feedparser
import pandas as pd
import re
from datetime import datetime, timedelta
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib

# Page config
st.set_page_config(page_title="NFL News", layout="wide", page_icon="🏈")

# NFL teams list
NFL_TEAMS = [
    'Arizona Cardinals', 'Atlanta Falcons', 'Baltimore Ravens', 'Buffalo Bills',
    'Carolina Panthers', 'Chicago Bears', 'Cincinnati Bengals', 'Cleveland Browns',
    'Dallas Cowboys', 'Denver Broncos', 'Detroit Lions', 'Green Bay Packers',
    'Houston Texans', 'Indianapolis Colts', 'Jacksonville Jaguars', 'Kansas City Chiefs',
    'Las Vegas Raiders', 'Los Angeles Chargers', 'Los Angeles Rams', 'Miami Dolphins',
    'Minnesota Vikings', 'New England Patriots', 'New Orleans Saints', 'New York Giants',
    'New York Jets', 'Philadelphia Eagles', 'Pittsburgh Steelers', 'San Francisco 49ers',
    'Seattle Seahawks', 'Tampa Bay Buccaneers', 'Tennessee Titans', 'Washington Commanders'
]

# General RSS feeds
GENERAL_RSS_FEEDS = [
    "https://www.nfl.com/feeds/rss/home",
    "https://www.espn.com/espn/rss/nfl/news",
    "https://www.cbssports.com/rss/headlines/nfl/"
]

# Team-specific feeds (condensed for performance)
TEAM_FEEDS = {
    'Arizona Cardinals': ['https://www.azcardinals.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=ARI'],
    'Atlanta Falcons': ['https://www.atlantafalcons.com/rss/article', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=ATL'],
    'Baltimore Ravens': ['https://www.baltimoreravens.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=BAL'],
    'Buffalo Bills': ['https://www.buffalobills.com/rss/article', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=BUF'],
    'Carolina Panthers': ['https://www.panthers.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=CAR'],
    'Chicago Bears': ['https://www.chicagobears.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=CHI'],
    'Cincinnati Bengals': ['https://www.bengals.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=CIN'],
    'Cleveland Browns': ['https://www.clevelandbrowns.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=CLE'],
    'Dallas Cowboys': ['https://www.dallascowboys.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=DAL'],
    'Denver Broncos': ['https://www.denverbroncos.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=DEN'],
    'Detroit Lions': ['https://www.detroitlions.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=DET'],
    'Green Bay Packers': ['https://www.packers.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=GB'],
    'Houston Texans': ['https://www.houstontexans.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=HOU'],
    'Indianapolis Colts': ['https://www.colts.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=IND'],
    'Jacksonville Jaguars': ['https://www.jaguars.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=JAX'],
    'Kansas City Chiefs': ['https://www.chiefs.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=KC'],
    'Las Vegas Raiders': ['https://www.raiders.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=LV'],
    'Los Angeles Chargers': ['https://www.chargers.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=LAC'],
    'Los Angeles Rams': ['https://www.therams.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=LAR'],
    'Miami Dolphins': ['https://www.miamidolphins.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=MIA'],
    'Minnesota Vikings': ['https://www.vikings.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=MIN'],
    'New England Patriots': ['https://www.patriots.com/rss/article', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=NE'],
    'New Orleans Saints': ['https://www.neworleanssaints.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=NO'],
    'New York Giants': ['https://www.giants.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=NYG'],
    'New York Jets': ['https://www.newyorkjets.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=NYJ'],
    'Philadelphia Eagles': ['https://www.philadelphiaeagles.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=PHI'],
    'Pittsburgh Steelers': ['https://www.steelers.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=PIT'],
    'San Francisco 49ers': ['https://www.49ers.com/rss/article', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=SF'],
    'Seattle Seahawks': ['https://www.seahawks.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=SEA'],
    'Tampa Bay Buccaneers': ['https://www.buccaneers.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=TB'],
    'Tennessee Titans': ['https://www.tennesseetitans.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=TEN'],
    'Washington Commanders': ['https://www.commanders.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=WAS']
}

@st.cache_data(ttl=1800)  # Cache for 30 minutes
def extract_team(text):
    """Extract team name from text"""
    text_upper = text.upper()
    for team in NFL_TEAMS:
        if team.upper() in text_upper:
            return team
    return 'General'

@st.cache_data(ttl=1800)
def fetch_feed(feed_url, max_entries=30):
    """Fetch a single RSS feed with error handling"""
    try:
        feed = feedparser.parse(feed_url)
        seven_days_ago = datetime.now() - timedelta(days=7)
        articles = []
        
        for entry in feed.entries[:max_entries]:
            title = entry.get('title', 'No Title')
            link = entry.get('link', '')
            
            # Parse publication date
            pub_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
            if pub_parsed:
                try:
                    pub_date = datetime(*pub_parsed[:6])
                except (TypeError, ValueError):
                    pub_date = datetime.now()
            else:
                pub_date = datetime.now()
            
            # Only include recent articles
            if pub_date >= seven_days_ago:
                articles.append({
                    'title': title,
                    'link': link,
                    'published': pub_date
                })
        
        return articles
    except Exception as e:
        return []

@st.cache_data(ttl=1800)
def fetch_all_feeds():
    """Fetch all feeds in parallel"""
    news_items = []
    
    # Fetch general feeds
    with ThreadPoolExecutor(max_workers=10) as executor:
        general_futures = {executor.submit(fetch_feed, url): 'General' for url in GENERAL_RSS_FEEDS}
        
        for future in as_completed(general_futures):
            team = general_futures[future]
            articles = future.result()
            for article in articles:
                # Try to extract team from title
                detected_team = extract_team(article['title'])
                news_items.append({
                    'team': detected_team,
                    'headline': article['title'],
                    'link': article['link'],
                    'published': article['published']
                })
    
    # Fetch team-specific feeds
    with ThreadPoolExecutor(max_workers=10) as executor:
        team_futures = {}
        for team, feeds in TEAM_FEEDS.items():
            for feed_url in feeds:
                team_futures[executor.submit(fetch_feed, feed_url)] = team
        
        for future in as_completed(team_futures):
            team = team_futures[future]
            articles = future.result()
            for article in articles:
                news_items.append({
                    'team': team,
                    'headline': article['title'],
                    'link': article['link'],
                    'published': article['published']
                })
    
    # Create DataFrame and remove duplicates
    df = pd.DataFrame(news_items)
    if not df.empty:
        # Create hash for deduplication
        df['hash'] = df.apply(lambda x: hashlib.md5(f"{x['headline']}{x['link']}".encode()).hexdigest(), axis=1)
        df = df.drop_duplicates(subset=['hash']).drop(columns=['hash'])
        df = df.sort_values('published', ascending=False)
    
    return df

# Main app
st.title("🏈 NFL News Dashboard")
st.markdown("*Latest news from the past 7 days*")

# Sidebar filters
st.sidebar.header("Filters")
team_options = ['All'] + sorted(NFL_TEAMS) + ['General']
selected_team = st.sidebar.selectbox('Select Team', team_options)

# Date filter
date_filter = st.sidebar.radio(
    "Time Range",
    ["Last 24 hours", "Last 3 days", "Last 7 days"],
    index=2
)

# Fetch data
with st.spinner('Loading NFL news...'):
    df_all = fetch_all_feeds()

# Apply filters
if not df_all.empty:
    # Team filter
    if selected_team != 'All':
        filtered = df_all[df_all['team'] == selected_team].copy()
    else:
        filtered = df_all.copy()
    
    # Date filter
    now = datetime.now()
    if date_filter == "Last 24 hours":
        cutoff = now - timedelta(days=1)
    elif date_filter == "Last 3 days":
        cutoff = now - timedelta(days=3)
    else:
        cutoff = now - timedelta(days=7)
    
    filtered = filtered[filtered['published'] >= cutoff]
    
    # Display results
    st.subheader(f"📰 News for {selected_team}")
    st.markdown(f"*{len(filtered)} articles found*")
    
    if not filtered.empty:
        # Display with formatting
        for idx, row in filtered.iterrows():
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"**[{row['headline']}]({row['link']})**")
                st.caption(f"{row['team']} • {row['published'].strftime('%b %d, %Y %I:%M %p')}")
            with col2:
                st.markdown(f"*{row['team']}*")
            st.divider()
    else:
        st.info(f"No news found for {selected_team} in the selected time range.")
else:
    st.error("Unable to fetch news. Please try again later.")

# Refresh button
if st.sidebar.button("🔄 Refresh News"):
    st.cache_data.clear()
    st.rerun()
