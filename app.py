"""
NFL Terminal - News & Injury Tracker (Hybrid ESPN + RSS)
Real-time news + Hybrid injury tracking (ESPN API + RSS fallback)
"""

import feedparser
import pandas as pd
import re
import json
import hashlib
import requests
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
    """Load configuration from config.json"""
    config_path = Path(__file__).parent / 'config.json'
    
    if not config_path.exists():
        st.error("⚠️ config.json not found")
        st.stop()
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"❌ Error loading config: {e}")
        st.stop()

CONFIG = load_config()
APP = CONFIG.get('app', {})
TEAMS = CONFIG.get('teams', [])
RSS_FEEDS = CONFIG.get('rss_feeds', {})
INJURY_DB = CONFIG.get('injury_database', {})
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
# INJURY RSS FEEDS (Fallback)
# =============================================================================

INJURY_RSS_FEEDS = {
    'DraftSharks': 'https://www.draftsharks.com/rss/injury-news',
    'RotoWire': 'https://www.rotowire.com/rss/news.php?sport=NFL',
    'ESPN': 'https://www.espn.com/espn/rss/nfl/news',
    'CBS Sports': 'https://www.cbssports.com/rss/headlines/nfl'
}

INJURY_KEYWORDS = [
    'injury', 'injured', 'hurt', 'out', 'questionable', 'doubtful', 'IR',
    'concussion', 'ankle', 'knee', 'shoulder', 'hamstring', 'foot', 'back',
    'inactive', 'limited', 'ruled out', 'week-to-week', 'day-to-day'
]

# =============================================================================
# ESPN API CLIENT (Primary Source)
# =============================================================================

class ESPNInjuryClient:
    """ESPN API client with robust error handling"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
    
    def fetch_injuries_simple(self) -> pd.DataFrame:
        """Simplified ESPN injury fetch"""
        try:
            url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
            response = self.session.get(url, timeout=10)
            
            if response.status_code != 200:
                return pd.DataFrame()
            
            data = response.json()
            injuries = []
            
            # Parse the injuries endpoint
            for team_data in data.get('items', []):
                team_name = team_data.get('team', {}).get('displayName', 'Unknown')
                
                for player_data in team_data.get('players', []):
                    athlete = player_data.get('athlete', {})
                    injury_status = player_data.get('status', {})
                    
                    injuries.append({
                        'team': team_name,
                        'player': athlete.get('displayName', 'Unknown'),
                        'position': athlete.get('position', {}).get('abbreviation', 'N/A'),
                        'status': injury_status.get('name', 'Unknown'),
                        'injury_type': player_data.get('details', {}).get('type', 'General'),
                        'description': player_data.get('longComment', player_data.get('shortComment', 'No details')),
                        'date': datetime.now(),
                        'source': 'ESPN API'
                    })
            
            return pd.DataFrame(injuries) if injuries else pd.DataFrame()
            
        except Exception as e:
            return pd.DataFrame()

# =============================================================================
# RSS INJURY TRACKER (Fallback)
# =============================================================================

class RSSInjuryTracker:
    """RSS-based injury tracker as fallback"""
    
    def __init__(self, days_lookback: int = 7):
        self.cutoff_date = datetime.now() - timedelta(days=days_lookback)
    
    def extract_player_name(self, text: str) -> Optional[str]:
        """Extract player name from text"""
        patterns = [
            r'^([A-Z][a-z]+\s+[A-Z][a-z]+)',
            r'([A-Z][a-z]+\s+[A-Z][a-z]+)\s*[\(\,]',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return None
    
    def extract_team(self, text: str) -> str:
        """Extract team from text"""
        text_upper = text.upper()
        for team in TEAMS:
            if team.upper() in text_upper:
                return team
        return 'General'
    
    def identify_injury_type(self, text: str) -> str:
        """Identify injury type from text"""
        text_lower = text.lower()
        priority = ['concussion', 'acl', 'mcl', 'hamstring', 'ankle', 'knee']
        
        for injury in priority:
            if injury in text_lower:
                return injury
        
        for injury in INJURY_DB.keys():
            if injury in text_lower:
                return injury
        
        return 'general'
    
    def extract_status(self, text: str) -> str:
        """Extract injury status from text"""
        text_lower = text.lower()
        
        if 'out' in text_lower or 'ruled out' in text_lower:
            return 'Out'
        elif 'doubtful' in text_lower:
            return 'Doubtful'
        elif 'questionable' in text_lower:
            return 'Questionable'
        elif 'ir' in text_lower or 'injured reserve' in text_lower:
            return 'IR'
        else:
            return 'Injured'
    
    def fetch_rss_injuries(self) -> pd.DataFrame:
        """Fetch injuries from RSS feeds"""
        injuries = []
        
        for source, url in INJURY_RSS_FEEDS.items():
            try:
                feed = feedparser.parse(url)
                
                for entry in feed.entries[:50]:
                    title = entry.get('title', '')
                    content = f"{title} {entry.get('summary', '')}".lower()
                    
                    # Check if contains injury keywords
                    if not any(kw in content for kw in INJURY_KEYWORDS):
                        continue
                    
                    # Parse date
                    pub_parsed = entry.get('published_parsed')
                    if pub_parsed:
                        pub_date = datetime(*pub_parsed[:6])
                    else:
                        pub_date = datetime.now()
                    
                    # Only recent
                    if pub_date < self.cutoff_date:
                        continue
                    
                    player = self.extract_player_name(title)
                    team = self.extract_team(title)
                    injury_type = self.identify_injury_type(content)
                    status = self.extract_status(content)
                    
                    injuries.append({
                        'team': team,
                        'player': player or 'Unknown',
                        'position': 'N/A',
                        'status': status,
                        'injury_type': injury_type,
                        'description': entry.get('summary', title)[:300],
                        'date': pub_date,
                        'source': f'{source} RSS'
                    })
                    
            except Exception:
                continue
        
        return pd.DataFrame(injuries) if injuries else pd.DataFrame()

# =============================================================================
# HYBRID INJURY FETCHER
# =============================================================================

def fetch_injuries_hybrid() -> pd.DataFrame:
    """Hybrid approach: Try ESPN first, fallback to RSS"""
    
    # Try ESPN API first
    st.info("🔄 Attempting ESPN API...")
    espn_client = ESPNInjuryClient()
    df_espn = espn_client.fetch_injuries_simple()
    
    if not df_espn.empty:
        st.success(f"✅ ESPN API: Found {len(df_espn)} injuries")
        df = df_espn
    else:
        st.warning("⚠️ ESPN API unavailable, using RSS feeds...")
        rss_tracker = RSSInjuryTracker(days_lookback=APP.get('days_lookback', 7))
        df = rss_tracker.fetch_rss_injuries()
        
        if not df.empty:
            st.success(f"✅ RSS Feeds: Found {len(df)} injuries")
        else:
            st.error("❌ No injuries found from any source")
            return pd.DataFrame()
    
    # Add severity classification
    df['severity'] = df['status'].apply(classify_severity)
    
    # Add injury database info
    df['injury_info'] = df['injury_type'].str.lower().apply(
        lambda x: INJURY_DB.get(x, INJURY_DB.get('general', {}))
    )
    
    df['injury_code'] = df['injury_info'].apply(lambda x: x.get('code', 'INJ'))
    df['recovery_time'] = df['injury_info'].apply(lambda x: x.get('recovery', 'Variable'))
    df['medical_desc'] = df['injury_info'].apply(lambda x: x.get('description', ''))
    
    # Remove duplicates
    if not df.empty:
        df = df.drop_duplicates(subset=['player', 'team', 'injury_type'])
        df = df.sort_values('date', ascending=False)
    
    return df

def classify_severity(status: str) -> str:
    """Classify injury severity"""
    status_lower = status.lower()
    
    if any(word in status_lower for word in ['out', 'ir', 'season', 'reserve']):
        return 'CRITICAL'
    elif 'doubtful' in status_lower:
        return 'SERIOUS'
    elif 'questionable' in status_lower:
        return 'MODERATE'
    else:
        return 'MILD'

# =============================================================================
# NEWS UTILITIES
# =============================================================================

class TextParser:
    @staticmethod
    def extract_team(text: str, teams: List[str]) -> str:
        text_upper = text.upper()
        for team in teams:
            if team.upper() in text_upper:
                return team
        return 'General'

class FeedFetcher:
    def __init__(self, days_lookback: int = 7, max_entries: int = 30):
        self.days_lookback = days_lookback
        self.max_entries = max_entries
        self.cutoff_date = datetime.now() - timedelta(days=days_lookback)
    
    def fetch_single_feed(self, url: str) -> List[Dict]:
        try:
            feed = feedparser.parse(url)
            articles = []
            
            for entry in feed.entries[:self.max_entries]:
                pub_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
                pub_date = datetime(*pub_parsed[:6]) if pub_parsed else datetime.now()
                
                if pub_date >= self.cutoff_date:
                    articles.append({
                        'title': entry.get('title', ''),
                        'link': entry.get('link', ''),
                        'published': pub_date
                    })
            return articles
        except:
            return []
    
    def fetch_multiple_feeds(self, feeds: List[str], max_workers: int = 10) -> List[Dict]:
        articles = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.fetch_single_feed, url): url for url in feeds}
            for future in as_completed(futures):
                articles.extend(future.result())
        return articles

class DataProcessor:
    @staticmethod
    def create_hash(text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()
    
    @staticmethod
    def deduplicate_dataframe(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
        if df.empty:
            return df
        hash_text = df[columns].astype(str).agg(''.join, axis=1)
        df['hash'] = hash_text.apply(DataProcessor.create_hash)
        df = df.drop_duplicates(subset=['hash']).drop(columns=['hash'])
        return df
    
    @staticmethod
    def filter_by_date(df: pd.DataFrame, hours: int) -> pd.DataFrame:
        if df.empty:
            return df
        cutoff = datetime.now() - timedelta(hours=hours)
        return df[df['date'] >= cutoff].copy()
    
    @staticmethod
    def filter_by_team(df: pd.DataFrame, team: str, team_col: str = 'team') -> pd.DataFrame:
        if df.empty or team == 'ALL TEAMS':
            return df.copy()
        if team == 'GENERAL':
            return df[df[team_col] == 'General'].copy()
        return df[df[team_col] == team].copy()

# =============================================================================
# DATA FETCHING
# =============================================================================

@st.cache_data(ttl=APP.get('cache_ttl', 1800), show_spinner=False)
def fetch_news_data() -> pd.DataFrame:
    fetcher = FeedFetcher(days_lookback=APP.get('days_lookback', 7))
    parser = TextParser()
    news_items = []
    
    general_feeds = [f['url'] for f in RSS_FEEDS.get('general_news', []) if f.get('enabled', True)]
    articles = fetcher.fetch_multiple_feeds(general_feeds)
    
    for article in articles:
        team = parser.extract_team(article['title'], TEAMS)
        news_items.append({
            'team': team,
            'headline': article['title'],
            'link': article['link'],
            'date': article['published']
        })
    
    team_feeds_dict = RSS_FEEDS.get('team_feeds', {})
    for team, feed_urls in team_feeds_dict.items():
        articles = fetcher.fetch_multiple_feeds(feed_urls)
        for article in articles:
            news_items.append({
                'team': team,
                'headline': article['title'],
                'link': article['link'],
                'date': article['published']
            })
    
    if not news_items:
        return pd.DataFrame()
    
    df = pd.DataFrame(news_items)
    df = DataProcessor.deduplicate_dataframe(df, ['headline', 'link'])
    df = df.sort_values('date', ascending=False)
    return df

@st.cache_data(ttl=APP.get('cache_ttl', 1800), show_spinner=False)
def fetch_injury_data() -> pd.DataFrame:
    return fetch_injuries_hybrid()

# =============================================================================
# UI COMPONENTS
# =============================================================================

def apply_custom_css():
    theme = UI.get('theme', {})
    st.markdown(f"""
    <style>
        .main {{background-color: {theme.get('background', '#000000')};}}
        .news-item {{border-left: 3px solid {theme.get('primary_color', '#00FF00')}; padding: 10px; margin-bottom: 15px; background-color: #1A1A1A; font-family: 'Courier New', monospace;}}
        .injury-item {{border-left: 3px solid {theme.get('secondary_color', '#FF0000')}; padding: 10px; margin-bottom: 15px; background-color: #1A1A1A; font-family: 'Courier New', monospace;}}
        .news-headline {{color: {theme.get('primary_color', '#00FF00')}; font-size: 14px; font-weight: bold;}}
        .injury-headline {{color: #FF6666; font-size: 14px; font-weight: bold;}}
        .news-meta, .injury-meta {{color: {theme.get('meta_color', '#888888')}; font-size: 11px; margin-top: 5px;}}
        .injury-details {{background-color: #0D0D0D; padding: 8px; margin-top: 8px; border-left: 2px solid {theme.get('secondary_color', '#FF0000')}; font-size: 11px; color: #CCCCCC;}}
        .severity-critical {{color: #FF0000; font-weight: bold;}}
        .severity-serious {{color: #FF6600; font-weight: bold;}}
        .severity-moderate {{color: #FFAA00; font-weight: bold;}}
        .severity-mild {{color: #FFFF00; font-weight: bold;}}
        .ticker {{color: {theme.get('primary_color', '#00FF00')}; font-family: 'Courier New', monospace; font-size: 12px;}}
        .stRadio > label, .stSelectbox > label {{color: {theme.get('primary_color', '#00FF00')};}}
    </style>
    """, unsafe_allow_html=True)

def render_header():
    st.markdown(f"## {APP.get('page_icon', '🏈')} {APP.get('title', 'NFL TERMINAL').upper()}")
    st.markdown(f"<p class='ticker'>SYSTEM TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>", unsafe_allow_html=True)

def render_sidebar_filters() -> Tuple[str, str, str]:
    st.sidebar.markdown("### TERMINAL MODE")
    mode = st.sidebar.radio("SELECT MODE", ["NEWS", "INJURIES"])
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### FILTERS")
    
    team_options = ['ALL TEAMS'] + sorted(TEAMS) + ['GENERAL']
    selected_team = st.sidebar.selectbox('TEAM', team_options)
    
    time_ranges = UI.get('time_ranges', ["24H", "3D", "7D"])
    date_filter = st.sidebar.radio("TIME RANGE", time_ranges, index=2)
    
    return mode, selected_team, date_filter

def render_stats_bar(df: pd.DataFrame, mode: str, team: str):
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
    timestamp = row['date'].strftime('%m/%d %H:%M')
    st.markdown(f"""
    <div class='news-item'>
        <a href='{row['link']}' target='_blank' class='news-headline'>{row['headline']}</a>
        <div class='news-meta'>{timestamp} | {row['team']}</div>
    </div>
    """, unsafe_allow_html=True)

def render_injury_item(row: pd.Series):
    timestamp = row['date'].strftime('%m/%d %H:%M')
    severity_class = f"severity-{row['severity'].lower()}"
    medical_info = f"<strong>MEDICAL:</strong> {row['medical_desc']}<br>" if row['medical_desc'] else ""
    
    st.markdown(f"""
    <div class='injury-item'>
        <div class='injury-headline'>{row['player']} - {row['injury_type'].upper()}</div>
        <div class='injury-meta'>{timestamp} | {row['team']} | {row['position']} | <span class='{severity_class}'>[{row['injury_code']}]</span></div>
        <div class='injury-details'>
            <strong>STATUS:</strong> <span class='{severity_class}'>{row['status']}</span><br>
            <strong>SEVERITY:</strong> <span class='{severity_class}'>{row['severity']}</span><br>
            <strong>RECOVERY:</strong> {row['recovery_time']}<br>
            {medical_info}
            <strong>DETAILS:</strong> {row['description']}<br>
            <strong>SOURCE:</strong> {row['source']}
        </div>
    </div>
    """, unsafe_allow_html=True)

# =============================================================================
# MAIN APPLICATION
# =============================================================================

def main():
    apply_custom_css()
    render_header()
    
    mode, selected_team, date_filter = render_sidebar_filters()
    
    selected_status = None
    selected_severity = None
    
    if mode == "INJURIES":
        st.sidebar.markdown("### INJURY FILTERS")
        status_options = ['ALL STATUS', 'Out', 'Questionable', 'Doubtful', 'IR']
        selected_status = st.sidebar.selectbox('STATUS', status_options)
        severity_options = ['ALL', 'CRITICAL', 'SERIOUS', 'MODERATE', 'MILD']
        selected_severity = st.sidebar.selectbox('SEVERITY', severity_options)
    
    with st.spinner(f'LOADING {mode} DATA...'):
        if mode == "NEWS":
            df = fetch_news_data()
        else:
            df = fetch_injury_data()
    
    if df.empty:
        st.warning(f"No {mode} data available")
        return
    
    df_filtered = DataProcessor.filter_by_team(df, selected_team)
    
    date_hours = {'24H': 24, '3D': 72, '7D': 168}
    df_filtered = DataProcessor.filter_by_date(df_filtered, date_hours.get(date_filter, 168))
    
    if mode == "INJURIES":
        if selected_status != 'ALL STATUS':
            df_filtered = df_filtered[df_filtered['status'].str.contains(selected_status, case=False, na=False)]
        if selected_severity != 'ALL':
            df_filtered = df_filtered[df_filtered['severity'] == selected_severity]
    
    render_stats_bar(df_filtered, mode, selected_team)
    st.markdown("---")
    
    if not df_filtered.empty:
        for _, row in df_filtered.iterrows():
            if mode == "NEWS":
                render_news_item(row)
            else:
                render_injury_item(row)
    else:
        st.markdown(f"<p class='ticker'>NO {mode} DATA FOR {selected_team} IN {date_filter}</p>", unsafe_allow_html=True)
    
    st.sidebar.markdown("---")
    if st.sidebar.button("↻ REFRESH DATA"):
        st.cache_data.clear()
        st.rerun()

if __name__ == "__main__":
    main()
