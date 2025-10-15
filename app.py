"""
NFL Terminal - News & Injury Tracker
A Bloomberg-style terminal for real-time NFL news and injury tracking
"""

import feedparser
import pandas as pd
import re
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit as st

# =============================================================================
# CONFIGURATION
# =============================================================================

@st.cache_resource
def load_config() -> Dict:
    """Load configuration from config.json with fallback to defaults"""
    config_path = Path(__file__).parent / 'config.json'
    
    if not config_path.exists():
        st.error("⚠️ config.json not found. Please add it to the repository.")
        st.info("See README.md for configuration instructions.")
        st.stop()
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        st.error(f"❌ Invalid JSON in config.json: {e}")
        st.stop()
    except Exception as e:
        st.error(f"❌ Error loading config.json: {e}")
        st.stop()

# Load configuration
CONFIG = load_config()

# Extract config sections
APP = CONFIG.get('app', {})
TEAMS = CONFIG.get('teams', [])
RSS_FEEDS = CONFIG.get('rss_feeds', {})
INJURY_DB = CONFIG.get('injury_database', {})
INJURY_KEYWORDS = CONFIG.get('injury_keywords', [])
UI = CONFIG.get('ui', {})

# =============================================================================
# PAGE CONFIGURATION
# =============================================================================

st.set_page_config(
    page_title=APP.get('title', 'NFL Terminal'),
    page_icon=APP.get('page_icon', '🏈'),
    layout=APP.get('layout', 'wide'),
    initial_sidebar_state='expanded'
)

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

class TextParser:
    """Text parsing utilities for extracting information from RSS content"""
    
    @staticmethod
    def extract_team(text: str, teams: List[str]) -> str:
        """Extract team name from text"""
        text_upper = text.upper()
        for team in teams:
            if team.upper() in text_upper:
                return team
        return 'General'
    
    @staticmethod
    def extract_player_name(text: str) -> Optional[str]:
        """Extract player name using regex patterns"""
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
    
    @staticmethod
    def identify_injury_type(text: str, injury_db: Dict) -> Optional[str]:
        """Identify specific injury type from text"""
        text_lower = text.lower()
        
        # Check priority injuries first
        priority = ['acl', 'mcl', 'concussion', 'hamstring', 'quadriceps', 'groin']
        for injury in priority:
            if injury in text_lower:
                return injury
        
        # Check remaining injuries
        for injury in injury_db.keys():
            if injury not in priority and injury in text_lower:
                return injury
        
        return None

class FeedFetcher:
    """RSS feed fetching and processing"""
    
    def __init__(self, days_lookback: int = 7, max_entries: int = 30):
        self.days_lookback = days_lookback
        self.max_entries = max_entries
        self.cutoff_date = datetime.now() - timedelta(days=days_lookback)
    
    def fetch_single_feed(self, url: str) -> List[Dict]:
        """Fetch and parse a single RSS feed"""
        try:
            feed = feedparser.parse(url)
            articles = []
            
            for entry in feed.entries[:self.max_entries]:
                title = entry.get('title', 'No Title')
                link = entry.get('link', '')
                
                # Parse publication date
                pub_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
                pub_date = self._parse_date(pub_parsed)
                
                # Only include recent articles
                if pub_date >= self.cutoff_date:
                    articles.append({
                        'title': title,
                        'link': link,
                        'published': pub_date
                    })
            
            return articles
        except Exception as e:
            # Silently fail individual feeds to not disrupt entire fetch
            return []
    
    @staticmethod
    def _parse_date(pub_parsed) -> datetime:
        """Parse publication date with fallback"""
        if pub_parsed:
            try:
                return datetime(*pub_parsed[:6])
            except (TypeError, ValueError):
                pass
        return datetime.now()
    
    def fetch_multiple_feeds(self, feeds: List[str], max_workers: int = 10) -> List[Dict]:
        """Fetch multiple feeds in parallel"""
        articles = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.fetch_single_feed, url): url for url in feeds}
            
            for future in as_completed(futures):
                articles.extend(future.result())
        
        return articles

class DataProcessor:
    """Data processing and cleaning utilities"""
    
    @staticmethod
    def create_hash(text: str) -> str:
        """Create MD5 hash for deduplication"""
        return hashlib.md5(text.encode()).hexdigest()
    
    @staticmethod
    def deduplicate_dataframe(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
        """Remove duplicates based on hash of specified columns"""
        if df.empty:
            return df
        
        hash_text = df[columns].astype(str).agg(''.join, axis=1)
        df['hash'] = hash_text.apply(DataProcessor.create_hash)
        df = df.drop_duplicates(subset=['hash']).drop(columns=['hash'])
        
        return df
    
    @staticmethod
    def filter_by_date(df: pd.DataFrame, hours: int) -> pd.DataFrame:
        """Filter dataframe by date range"""
        if df.empty:
            return df
        
        cutoff = datetime.now() - timedelta(hours=hours)
        return df[df['published'] >= cutoff].copy()
    
    @staticmethod
    def filter_by_team(df: pd.DataFrame, team: str) -> pd.DataFrame:
        """Filter dataframe by team"""
        if df.empty or team == 'ALL TEAMS':
            return df.copy()
        
        if team == 'GENERAL':
            return df[df['team'] == 'General'].copy()
        
        return df[df['team'] == team].copy()

# =============================================================================
# DATA FETCHING FUNCTIONS
# =============================================================================

@st.cache_data(ttl=APP.get('cache_ttl', 1800), show_spinner=False)
def fetch_news_data() -> pd.DataFrame:
    """Fetch and process all news feeds"""
    fetcher = FeedFetcher(
        days_lookback=APP.get('days_lookback', 7),
        max_entries=30
    )
    parser = TextParser()
    news_items = []
    
    # Fetch general news feeds
    general_feeds = [f['url'] for f in RSS_FEEDS.get('general_news', []) if f.get('enabled', True)]
    articles = fetcher.fetch_multiple_feeds(general_feeds, max_workers=APP.get('max_workers', 10))
    
    for article in articles:
        team = parser.extract_team(article['title'], TEAMS)
        news_items.append({
            'team': team,
            'headline': article['title'],
            'link': article['link'],
            'published': article['published']
        })
    
    # Fetch team-specific feeds
    team_feeds_dict = RSS_FEEDS.get('team_feeds', {})
    for team, feed_urls in team_feeds_dict.items():
        articles = fetcher.fetch_multiple_feeds(feed_urls, max_workers=APP.get('max_workers', 10))
        
        for article in articles:
            news_items.append({
                'team': team,
                'headline': article['title'],
                'link': article['link'],
                'published': article['published']
            })
    
    # Create and clean dataframe
    if not news_items:
        return pd.DataFrame()
    
    df = pd.DataFrame(news_items)
    df = DataProcessor.deduplicate_dataframe(df, ['headline', 'link'])
    df = df.sort_values('published', ascending=False)
    
    return df

@st.cache_data(ttl=APP.get('cache_ttl', 1800), show_spinner=False)
def fetch_injury_data() -> pd.DataFrame:
    """Fetch and process all injury feeds"""
    fetcher = FeedFetcher(
        days_lookback=APP.get('days_lookback', 7),
        max_entries=50
    )
    parser = TextParser()
    injuries = []
    
    # Fetch injury-specific feeds
    injury_feeds = {f['name']: f['url'] for f in RSS_FEEDS.get('injury_feeds', []) if f.get('enabled', True)}
    
    for source_name, url in injury_feeds.items():
        articles = fetcher.fetch_single_feed(url)
        
        for article in articles:
            title = article['title']
            content = title.lower()
            
            # Check if article contains injury keywords
            has_injury = any(kw in content for kw in INJURY_KEYWORDS)
            
            if has_injury:
                player = parser.extract_player_name(title)
                team = parser.extract_team(title, TEAMS)
                injury_type = parser.identify_injury_type(content, INJURY_DB)
                injury_info = INJURY_DB.get(injury_type, {})
                
                injuries.append({
                    'team': team,
                    'player': player or 'Unknown',
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
    
    # Create and clean dataframe
    if not injuries:
        return pd.DataFrame()
    
    df = pd.DataFrame(injuries)
    df = DataProcessor.deduplicate_dataframe(df, ['headline', 'link'])
    df = df.sort_values('published', ascending=False)
    
    return df

# =============================================================================
# UI COMPONENTS
# =============================================================================

def apply_custom_css():
    """Apply custom CSS styling"""
    theme = UI.get('theme', {})
    
    st.markdown(f"""
    <style>
        .main {{
            background-color: {theme.get('background', '#000000')};
        }}
        .news-item {{
            border-left: 3px solid {theme.get('primary_color', '#00FF00')};
            padding: 10px;
            margin-bottom: 15px;
            background-color: #1A1A1A;
            font-family: 'Courier New', monospace;
        }}
        .injury-item {{
            border-left: 3px solid {theme.get('secondary_color', '#FF0000')};
            padding: 10px;
            margin-bottom: 15px;
            background-color: #1A1A1A;
            font-family: 'Courier New', monospace;
        }}
        .news-headline {{
            color: {theme.get('primary_color', '#00FF00')};
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
        .news-meta, .injury-meta {{
            color: {theme.get('meta_color', '#888888')};
            font-size: 11px;
            margin-top: 5px;
        }}
        .injury-details {{
            background-color: #0D0D0D;
            padding: 8px;
            margin-top: 8px;
            border-left: 2px solid {theme.get('secondary_color', '#FF0000')};
            font-size: 11px;
            color: #CCCCCC;
        }}
        .severity-critical {{ color: #FF0000; font-weight: bold; }}
        .severity-serious {{ color: #FF6600; font-weight: bold; }}
        .severity-moderate {{ color: #FFAA00; font-weight: bold; }}
        .severity-mild {{ color: #FFFF00; font-weight: bold; }}
        .ticker {{
            color: {theme.get('primary_color', '#00FF00')};
            font-family: 'Courier New', monospace;
            font-size: 12px;
        }}
        .stRadio > label, .stSelectbox > label {{
            color: {theme.get('primary_color', '#00FF00')};
        }}
    </style>
    """, unsafe_allow_html=True)

def render_header():
    """Render page header"""
    st.markdown(f"## {APP.get('page_icon', '🏈')} {APP.get('title', 'NFL TERMINAL').upper()}")
    st.markdown(f"<p class='ticker'>SYSTEM TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>", 
                unsafe_allow_html=True)

def render_sidebar_filters() -> Tuple[str, str, str]:
    """Render sidebar filters and return selections"""
    st.sidebar.markdown("### TERMINAL MODE")
    mode = st.sidebar.radio("SELECT MODE", ["NEWS", "INJURIES"])
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### FILTERS")
    
    # Team filter
    team_options = ['ALL TEAMS'] + sorted(TEAMS) + ['GENERAL']
    selected_team = st.sidebar.selectbox('TEAM', team_options)
    
    # Date filter
    time_ranges = UI.get('time_ranges', ["24H", "3D", "7D"])
    default_range = UI.get('default_time_range', '7D')
    date_filter = st.sidebar.radio("TIME RANGE", time_ranges, 
                                   index=time_ranges.index(default_range) if default_range in time_ranges else 0)
    
    return mode, selected_team, date_filter

def render_stats_bar(df: pd.DataFrame, mode: str, team: str):
    """Render statistics bar"""
    if mode == "NEWS":
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"<p class='ticker'>ARTICLES: {len(df)}</p>", unsafe_allow_html=True)
        with col2:
            st.markdown(f"<p class='ticker'>TEAMS: {df['team'].nunique()}</p>", unsafe_allow_html=True)
        with col3:
            st.markdown(f"<p class='ticker'>FILTER: {team}</p>", unsafe_allow_html=True)
    else:
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f"<p class='ticker'>INJURIES: {len(df)}</p>", unsafe_allow_html=True)
        with col2:
            st.markdown(f"<p class='ticker'>PLAYERS: {df['player'].nunique()}</p>", unsafe_allow_html=True)
        with col3:
            critical = len(df[df['severity'] == 'CRITICAL'])
            st.markdown(f"<p class='ticker'>CRITICAL: {critical}</p>", unsafe_allow_html=True)
        with col4:
            st.markdown(f"<p class='ticker'>FILTER: {team}</p>", unsafe_allow_html=True)

def render_news_item(row: pd.Series):
    """Render a single news item"""
    timestamp = row['published'].strftime('%m/%d %H:%M')
    st.markdown(f"""
    <div class='news-item'>
        <a href='{row['link']}' target='_blank' class='news-headline'>{row['headline']}</a>
        <div class='news-meta'>{timestamp} | {row['team']}</div>
    </div>
    """, unsafe_allow_html=True)

def render_injury_item(row: pd.Series):
    """Render a single injury item"""
    timestamp = row['published'].strftime('%m/%d %H:%M')
    severity_class = f"severity-{row['severity'].lower()}"
    
    st.markdown(f"""
    <div class='injury-item'>
        <a href='{row['link']}' target='_blank' class='injury-headline'>{row['headline']}</a>
        <div class='injury-meta'>{timestamp} | {row['player']} | {row['team']} | 
            <span class='{severity_class}'>[{row['injury_code']}]</span>
        </div>
        <div class='injury-details'>
            <strong>INJURY:</strong> {row['injury_name']}<br>
            <strong>SEVERITY:</strong> <span class='{severity_class}'>{row['severity']}</span><br>
            <strong>RECOVERY:</strong> {row['recovery']}<br>
            <strong>DETAILS:</strong> {row['description']}
        </div>
    </div>
    """, unsafe_allow_html=True)

# =============================================================================
# MAIN APPLICATION
# =============================================================================

def main():
    """Main application logic"""
    apply_custom_css()
    render_header()
    
    # Get sidebar selections
    mode, selected_team, date_filter = render_sidebar_filters()
    
    # Additional filters for injury mode
    selected_injury_type = None
    selected_severity = None
    
    if mode == "INJURIES":
        injury_type_options = ['ALL INJURIES'] + sorted(list(set([v['name'] for v in INJURY_DB.values()])))
        selected_injury_type = st.sidebar.selectbox('INJURY TYPE', injury_type_options)
        
        severity_options = ['ALL', 'CRITICAL', 'SERIOUS', 'MODERATE', 'MILD']
        selected_severity = st.sidebar.selectbox('SEVERITY', severity_options)
    
    # Fetch data based on mode
    with st.spinner(f'LOADING {mode} FEED...'):
        if mode == "NEWS":
            df = fetch_news_data()
        else:
            df = fetch_injury_data()
    
    # Check if data was fetched
    if df.empty:
        st.error(f"{mode} FEED ERROR - RETRY")
        return
    
    # Apply filters
    df_filtered = DataProcessor.filter_by_team(df, selected_team)
    
    # Apply date filter
    date_hours = {'24H': 24, '3D': 72, '7D': 168}
    df_filtered = DataProcessor.filter_by_date(df_filtered, date_hours.get(date_filter, 168))
    
    # Apply injury-specific filters
    if mode == "INJURIES":
        if selected_injury_type != 'ALL INJURIES':
            df_filtered = df_filtered[df_filtered['injury_name'] == selected_injury_type]
        
        if selected_severity != 'ALL':
            df_filtered = df_filtered[df_filtered['severity'] == selected_severity]
    
    # Render stats and content
    render_stats_bar(df_filtered, mode, selected_team)
    st.markdown("---")
    
    # Display items
    if not df_filtered.empty:
        for _, row in df_filtered.iterrows():
            if mode == "NEWS":
                render_news_item(row)
            else:
                render_injury_item(row)
    else:
        st.markdown(f"<p class='ticker'>NO {mode} DATA FOR {selected_team} IN {date_filter}</p>", 
                   unsafe_allow_html=True)
    
    # Refresh button
    st.sidebar.markdown("---")
    if st.sidebar.button("↻ REFRESH FEED"):
        st.cache_data.clear()
        st.rerun()

if __name__ == "__main__":
    main()
