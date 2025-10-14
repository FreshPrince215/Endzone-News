import feedparser
import pandas as pd
import re
import json
from datetime import datetime, timedelta
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
from pathlib import Path

# =============================================================================
# LOAD CONFIGURATION
# =============================================================================

@st.cache_resource
def load_config():
    """Load configuration from config.json"""
    config_path = Path(__file__).parent / 'config.json'
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        st.error("config.json not found! Please create it in the same directory as app.py")
        st.stop()
    except json.JSONDecodeError as e:
        st.error(f"Error parsing config.json: {e}")
        st.stop()

# Load config
CONFIG = load_config()

# Extract config values
APP_CONFIG = CONFIG['app']
NFL_TEAMS = CONFIG['teams']
GENERAL_RSS_FEEDS = [feed['url'] for feed in CONFIG['rss_feeds']['general_news'] if feed['enabled']]
INJURY_RSS_FEEDS = {feed['name']: feed['url'] for feed in CONFIG['rss_feeds']['injury_feeds'] if feed['enabled']}
TEAM_FEEDS = CONFIG['rss_feeds']['team_feeds']
INJURY_DATABASE = CONFIG['injury_database']
INJURY_KEYWORDS = CONFIG['injury_keywords']
UI_CONFIG = CONFIG['ui']

# =============================================================================
# PAGE CONFIG
# =============================================================================

st.set_page_config(
    page_title=APP_CONFIG['title'],
    layout=APP_CONFIG['layout'],
    page_icon=APP_CONFIG['page_icon']
)

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def extract_team(text):
    """Extract team name from text"""
    text_upper = text.upper()
    for team in NFL_TEAMS:
        if team.upper() in text_upper:
            return team
    return 'General'

def extract_player_name(text):
    """Extract player name from title"""
    patterns = [
        r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s*[\(\,]',
        r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+(?:injury|injured|out|questionable)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            name = match.group(1).strip()
            if len(name.split()) >= 2:
                return name
    return None

def identify_injury_type(text):
    """Identify specific injury type from text"""
    text_lower = text.lower()
    priority = ['acl', 'mcl', 'concussion', 'hamstring', 'quadriceps', 'groin']
    
    for injury in priority:
        if injury in text_lower:
            return injury
    
    for injury in INJURY_DATABASE.keys():
        if injury not in priority and injury in text_lower:
            return injury
    
    return None

def fetch_feed(feed_url, max_entries=30):
    """Fetch a single RSS feed with error handling"""
    try:
        feed = feedparser.parse(feed_url)
        days_ago = datetime.now() - timedelta(days=APP_CONFIG['days_lookback'])
        articles = []
        
        for entry in feed.entries[:max_entries]:
            title = entry.get('title', 'No Title')
            link = entry.get('link', '')
            
            pub_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
            if pub_parsed:
                try:
                    pub_date = datetime(*pub_parsed[:6])
                except (TypeError, ValueError):
                    pub_date = datetime.now()
            else:
                pub_date = datetime.now()
            
            if pub_date >= days_ago:
                articles.append({
                    'title': title,
                    'link': link,
                    'published': pub_date
                })
        
        return articles
    except Exception:
        return []

# =============================================================================
# DATA FETCHING
# =============================================================================

@st.cache_data(ttl=APP_CONFIG['cache_ttl'])
def fetch_all_news():
    """Fetch all news feeds in parallel"""
    news_items = []
    
    with ThreadPoolExecutor(max_workers=APP_CONFIG['max_workers']) as executor:
        general_futures = {executor.submit(fetch_feed, url): 'General' for url in GENERAL_RSS_FEEDS}
        
        for future in as_completed(general_futures):
            articles = future.result()
            for article in articles:
                detected_team = extract_team(article['title'])
                news_items.append({
                    'team': detected_team,
                    'headline': article['title'],
                    'link': article['link'],
                    'published': article['published']
                })
    
    with ThreadPoolExecutor(max_workers=APP_CONFIG['max_workers']) as executor:
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
    
    df = pd.DataFrame(news_items)
    if not df.empty:
        df['hash'] = df.apply(lambda x: hashlib.md5(f"{x['headline']}{x['link']}".encode()).hexdigest(), axis=1)
        df = df.drop_duplicates(subset=['hash']).drop(columns=['hash'])
        df = df.sort_values('published', ascending=False)
    
    return df

@st.cache_data(ttl=APP_CONFIG['cache_ttl'])
def fetch_all_injuries():
    """Fetch injury-specific feeds"""
    injuries = []
    
    for source_name, url in INJURY_RSS_FEEDS.items():
        try:
            articles = fetch_feed(url, max_entries=50)
            
            for article in articles:
                title = article['title']
                content = title.lower()
                
                has_injury = any(kw in content for kw in INJURY_KEYWORDS)
                
                if has_injury:
                    player = extract_player_name(title)
                    team = extract_team(title)
                    injury_type = identify_injury_type(content)
                    injury_info = INJURY_DATABASE.get(injury_type, {})
                    
                    injuries.append({
                        'team': team,
                        'player': player if player else 'Unknown',
                        'headline': title,
                        'link': article['link'],
                        'published': article['published'],
                        'source': source_name,
                        'injury_type': injury_type,
                        'injury_code': injury_info.get('code', 'INJ'),
                        'injury_name': injury_info.get('name', 'INJURY'),
                        'description': injury_info.get('description', 'Injury details not available'),
                        'recovery': injury_info.get('recovery', 'Variable'),
                        'severity': injury_info.get('severity', 'UNKNOWN')
                    })
        except Exception:
            pass
    
    df = pd.DataFrame(injuries)
    if not df.empty:
        df['hash'] = df.apply(lambda x: hashlib.md5(f"{x['headline']}{x['link']}".encode()).hexdigest(), axis=1)
        df = df.drop_duplicates(subset=['hash']).drop(columns=['hash'])
        df = df.sort_values('published', ascending=False)
    
    return df

# =============================================================================
# STYLING
# =============================================================================

theme = UI_CONFIG['theme']
st.markdown(f"""
<style>
    .main {{
        background-color: {theme['background']};
    }}
    .news-item {{
        border-left: 3px solid {theme['primary_color']};
        padding: 10px;
        margin-bottom: 15px;
        background-color: #1A1A1A;
        font-family: 'Courier New', monospace;
    }}
    .injury-item {{
        border-left: 3px solid {theme['secondary_color']};
        padding: 10px;
        margin-bottom: 15px;
        background-color: #1A1A1A;
        font-family: 'Courier New', monospace;
    }}
    .news-headline {{
        color: {theme['primary_color']};
        font-size: 14px;
        font-weight: bold;
        text-decoration: none;
    }}
    .injury-headline {{
        color: #FF6666;
        font-size: 14px;
        font-weight: bold;
        text-decoration: none;
    }}
    .news-meta {{
        color: {theme['meta_color']};
        font-size: 11px;
        margin-top: 5px;
    }}
    .injury-meta {{
        color: {theme['meta_color']};
        font-size: 11px;
        margin-top: 5px;
    }}
    .injury-details {{
        background-color: #0D0D0D;
        padding: 8px;
        margin-top: 8px;
        border-left: 2px solid {theme['secondary_color']};
        font-size: 11px;
        color: #CCCCCC;
    }}
    .severity-critical {{
        color: #FF0000;
        font-weight: bold;
    }}
    .severity-serious {{
        color: #FF6600;
        font-weight: bold;
    }}
    .severity-moderate {{
        color: #FFAA00;
        font-weight: bold;
    }}
    .severity-mild {{
        color: #FFFF00;
        font-weight: bold;
    }}
    .ticker {{
        color: {theme['primary_color']};
        font-family: 'Courier New', monospace;
        font-size: 12px;
    }}
    .stRadio > label {{
        color: {theme['primary_color']};
    }}
    .stSelectbox > label {{
        color: {theme['primary_color']};
    }}
</style>
""", unsafe_allow_html=True)

# =============================================================================
# MAIN APP
# =============================================================================

# Header
st.markdown(f"## {APP_CONFIG['page_icon']} {APP_CONFIG['title'].upper()}")
st.markdown(f"<p class='ticker'>SYSTEM TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>", unsafe_allow_html=True)

# Sidebar Navigation
st.sidebar.markdown("### TERMINAL MODE")
mode = st.sidebar.radio("SELECT MODE", ["NEWS", "INJURIES"])

st.sidebar.markdown("---")
st.sidebar.markdown("### FILTERS")

# Common filters
team_options = ['ALL TEAMS'] + sorted(NFL_TEAMS) + ['GENERAL']
selected_team = st.sidebar.selectbox('TEAM', team_options)

date_filter = st.sidebar.radio(
    "TIME RANGE",
    UI_CONFIG['time_ranges'],
    index=UI_CONFIG['time_ranges'].index(UI_CONFIG['default_time_range'])
)

# =============================================================================
# NEWS MODE
# =============================================================================

if mode == "NEWS":
    with st.spinner('LOADING NEWS FEED...'):
        df_all = fetch_all_news()
    
    if not df_all.empty:
        if selected_team == 'ALL TEAMS':
            filtered = df_all.copy()
        elif selected_team == 'GENERAL':
            filtered = df_all[df_all['team'] == 'General'].copy()
        else:
            filtered = df_all[df_all['team'] == selected_team].copy()
        
        now = datetime.now()
        if date_filter == "24H":
            cutoff = now - timedelta(days=1)
        elif date_filter == "3D":
            cutoff = now - timedelta(days=3)
        else:
            cutoff = now - timedelta(days=7)
        
        filtered = filtered[filtered['published'] >= cutoff]
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"<p class='ticker'>ARTICLES: {len(filtered)}</p>", unsafe_allow_html=True)
        with col2:
            st.markdown(f"<p class='ticker'>TEAMS: {filtered['team'].nunique()}</p>", unsafe_allow_html=True)
        with col3:
            st.markdown(f"<p class='ticker'>FILTER: {selected_team}</p>", unsafe_allow_html=True)
        
        st.markdown("---")
        
        if not filtered.empty:
            for idx, row in filtered.iterrows():
                timestamp = row['published'].strftime('%m/%d %H:%M')
                st.markdown(f"""
                <div class='news-item'>
                    <a href='{row['link']}' target='_blank' class='news-headline'>{row['headline']}</a>
                    <div class='news-meta'>{timestamp} |
