"""
NFL Terminal - News & Injury Tracker (Enhanced with ESPN API)
Real-time news aggregation + Official ESPN injury data
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
        st.error("⚠️ config.json not found. Please add it to the repository.")
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
# ESPN API CLIENT
# =============================================================================

class ESPNInjuryClient:
    """Client for fetching official ESPN injury data"""
    
    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
    CORE_URL = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
    
    def __init__(self, days_lookback: int = 7):
        self.days_lookback = days_lookback
        self.cutoff_date = datetime.now() - timedelta(days=days_lookback)
        self.session = requests.Session()
    
    def fetch_all_teams(self) -> List[Dict]:
        """Fetch all NFL teams from ESPN API"""
        try:
            url = f"{self.BASE_URL}/teams"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            teams_data = response.json()['sports'][0]['leagues'][0]['teams']
            
            teams = []
            for team in teams_data:
                team_info = team.get('team', {})
                teams.append({
                    'id': team_info.get('id'),
                    'name': team_info.get('displayName'),
                    'abbreviation': team_info.get('abbreviation'),
                    'logo': team_info.get('logos', [{}])[0].get('href', '')
                })
            
            return teams
        except Exception as e:
            st.error(f"Error fetching teams: {e}")
            return []
    
    def fetch_team_injuries(self, team_id: str, team_name: str) -> List[Dict]:
        """Fetch injuries for a specific team"""
        try:
            url = f"{self.CORE_URL}/teams/{team_id}/injuries?limit=100"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            injuries_data = response.json().get('items', [])
            injuries = []
            
            for injury_ref in injuries_data:
                injury_url = injury_ref.get('$ref', '')
                if not injury_url:
                    continue
                
                try:
                    injury_response = self.session.get(injury_url, timeout=10)
                    injury_response.raise_for_status()
                    injury_data = injury_response.json()
                    
                    # Parse date
                    date_str = injury_data.get('date', '')
                    if date_str:
                        try:
                            injury_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                            if injury_date < self.cutoff_date:
                                continue
                        except ValueError:
                            pass
                    
                    # Extract athlete data
                    athlete = injury_data.get('athlete', {})
                    position = athlete.get('position', {}).get('abbreviation', 'N/A')
                    
                    # Extract status
                    status = injury_data.get('status', {})
                    status_name = status.get('name', 'Unknown') if isinstance(status, dict) else str(status)
                    
                    # Skip if Active (not actually injured)
                    if status_name.lower() == 'active':
                        continue
                    
                    # Extract description
                    description = injury_data.get('longComment', injury_data.get('shortComment', 'No details available'))
                    
                    # Get injury type from details
                    details = injury_data.get('details', {})
                    injury_type = details.get('type', 'General')
                    
                    injuries.append({
                        'team': team_name,
                        'player': athlete.get('displayName', 'Unknown'),
                        'position': position,
                        'status': status_name,
                        'injury_type': injury_type,
                        'description': description,
                        'date': injury_date if date_str else datetime.now(),
                        'source': 'ESPN Official'
                    })
                    
                except Exception as e:
                    continue
            
            return injuries
            
        except Exception as e:
            return []
    
    def fetch_all_injuries(self) -> pd.DataFrame:
        """Fetch all NFL injuries from ESPN API"""
        teams = self.fetch_all_teams()
        
        if not teams:
            return pd.DataFrame()
        
        all_injuries = []
        
        # Use ThreadPoolExecutor for parallel fetching
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(self.fetch_team_injuries, team['id'], team['name']): team 
                for team in teams
            }
            
            for future in as_completed(futures):
                team = futures[future]
                try:
                    injuries = future.result()
                    all_injuries.extend(injuries)
                except Exception as e:
                    continue
        
        if not all_injuries:
            return pd.DataFrame()
        
        df = pd.DataFrame(all_injuries)
        
        # Add injury severity classification
        df['severity'] = df['status'].apply(self._classify_severity)
        
        # Add injury info from database
        df['injury_info'] = df['injury_type'].str.lower().apply(
            lambda x: INJURY_DB.get(x, {})
        )
        
        df['injury_code'] = df['injury_info'].apply(lambda x: x.get('code', 'INJ'))
        df['recovery_time'] = df['injury_info'].apply(lambda x: x.get('recovery', 'Variable'))
        df['medical_desc'] = df['injury_info'].apply(lambda x: x.get('description', ''))
        
        # Sort by date (most recent first)
        df = df.sort_values('date', ascending=False)
        
        return df
    
    @staticmethod
    def _classify_severity(status: str) -> str:
        """Classify injury severity based on status"""
        status_lower = status.lower()
        
        if any(word in status_lower for word in ['out', 'ir', 'season', 'reserve']):
            return 'CRITICAL'
        elif 'doubtful' in status_lower:
            return 'SERIOUS'
        elif 'questionable' in status_lower:
            return 'MODERATE'
        elif 'probable' in status_lower or 'day-to-day' in status_lower:
            return 'MILD'
        else:
            return 'UNKNOWN'

# =============================================================================
# NEWS FEED UTILITIES (Unchanged)
# =============================================================================

class TextParser:
    """Text parsing utilities"""
    
    @staticmethod
    def extract_team(text: str, teams: List[str]) -> str:
        """Extract team name from text"""
        text_upper = text.upper()
        for team in teams:
            if team.upper() in text_upper:
                return team
        return 'General'

class FeedFetcher:
    """RSS feed fetching"""
    
    def __init__(self, days_lookback: int = 7, max_entries: int = 30):
        self.days_lookback = days_lookback
        self.max_entries = max_entries
        self.cutoff_date = datetime.now() - timedelta(days=days_lookback)
    
    def fetch_single_feed(self, url: str) -> List[Dict]:
        """Fetch single RSS feed"""
        try:
            feed = feedparser.parse(url)
            articles = []
            
            for entry in feed.entries[:self.max_entries]:
                title = entry.get('title', 'No Title')
                link = entry.get('link', '')
                
                pub_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
                pub_date = self._parse_date(pub_parsed)
                
                if pub_date >= self.cutoff_date:
                    articles.append({
                        'title': title,
                        'link': link,
                        'published': pub_date
                    })
            
            return articles
        except Exception:
            return []
    
    @staticmethod
    def _parse_date(pub_parsed) -> datetime:
        """Parse publication date"""
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
    """Data processing utilities"""
    
    @staticmethod
    def create_hash(text: str) -> str:
        """Create MD5 hash"""
        return hashlib.md5(text.encode()).hexdigest()
    
    @staticmethod
    def deduplicate_dataframe(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
        """Remove duplicates"""
        if df.empty:
            return df
        
        hash_text = df[columns].astype(str).agg(''.join, axis=1)
        df['hash'] = hash_text.apply(DataProcessor.create_hash)
        df = df.drop_duplicates(subset=['hash']).drop(columns=['hash'])
        
        return df
    
    @staticmethod
    def filter_by_date(df: pd.DataFrame, hours: int) -> pd.DataFrame:
        """Filter by date range"""
        if df.empty:
            return df
        
        cutoff = datetime.now() - timedelta(hours=hours)
        return df[df['date'] >= cutoff].copy()
    
    @staticmethod
    def filter_by_team(df: pd.DataFrame, team: str, team_col: str = 'team') -> pd.DataFrame:
        """Filter by team"""
        if df.empty or team == 'ALL TEAMS':
            return df.copy()
        
        if team == 'GENERAL':
            return df[df[team_col] == 'General'].copy()
        
        return df[df[team_col] == team].copy()

# =============================================================================
# DATA FETCHING FUNCTIONS
# =============================================================================

@st.cache_data(ttl=APP.get('cache_ttl', 1800), show_spinner=False)
def fetch_news_data() -> pd.DataFrame:
    """Fetch news from RSS feeds"""
    fetcher = FeedFetcher(days_lookback=APP.get('days_lookback', 7), max_entries=30)
    parser = TextParser()
    news_items = []
    
    # Fetch general news
    general_feeds = [f['url'] for f in RSS_FEEDS.get('general_news', []) if f.get('enabled', True)]
    articles = fetcher.fetch_multiple_feeds(general_feeds, max_workers=APP.get('max_workers', 10))
    
    for article in articles:
        team = parser.extract_team(article['title'], TEAMS)
        news_items.append({
            'team': team,
            'headline': article['title'],
            'link': article['link'],
            'date': article['published']
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
                'date': article['published']
            })
    
    if not news_items:
        return pd.DataFrame()
    
    df = pd.DataFrame(news_items)
    df = DataProcessor.deduplicate_dataframe(df, ['headline', 'link'])
    df = df.sort_values('date', ascending=False)
    
    return df

@st.cache_data(ttl=APP.get('cache_ttl', 1800), show_spinner=False)
def fetch_injury_data_espn() -> pd.DataFrame:
    """Fetch official injury data from ESPN API"""
    client = ESPNInjuryClient(days_lookback=APP.get('days_lookback', 7))
    return client.fetch_all_injuries()

# =============================================================================
# UI COMPONENTS
# =============================================================================

def apply_custom_css():
    """Apply custom CSS"""
    theme = UI.get('theme', {})
    
    st.markdown(f"""
    <style>
        .main {{background-color: {theme.get('background', '#000000')};}}
        .news-item {{border-left: 3px solid {theme.get('primary_color', '#00FF00')}; padding: 10px; margin-bottom: 15px; background-color: #1A1A1A; font-family: 'Courier New', monospace;}}
        .injury-item {{border-left: 3px solid {theme.get('secondary_color', '#FF0000')}; padding: 10px; margin-bottom: 15px; background-color: #1A1A1A; font-family: 'Courier New', monospace;}}
        .news-headline {{color: {theme.get('primary_color', '#00FF00')}; font-size: 14px; font-weight: bold; text-decoration: none;}}
        .injury-headline {{color: #FF6666; font-size: 14px; font-weight: bold; text-decoration: none;}}
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
    """Render header"""
    st.markdown(f"## {APP.get('page_icon', '🏈')} {APP.get('title', 'NFL TERMINAL').upper()}")
    st.markdown(f"<p class='ticker'>SYSTEM TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>", 
                unsafe_allow_html=True)

def render_sidebar_filters() -> Tuple[str, str, str]:
    """Render sidebar filters"""
    st.sidebar.markdown("### TERMINAL MODE")
    mode = st.sidebar.radio("SELECT MODE", ["NEWS", "INJURIES"])
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### FILTERS")
    
    team_options = ['ALL TEAMS'] + sorted(TEAMS) + ['GENERAL']
    selected_team = st.sidebar.selectbox('TEAM', team_options)
    
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
    """Render news item"""
    timestamp = row['date'].strftime('%m/%d %H:%M')
    st.markdown(f"""
    <div class='news-item'>
        <a href='{row['link']}' target='_blank' class='news-headline'>{row['headline']}</a>
        <div class='news-meta'>{timestamp} | {row['team']}</div>
    </div>
    """, unsafe_allow_html=True)

def render_injury_item(row: pd.Series):
    """Render injury item"""
    timestamp = row['date'].strftime('%m/%d %H:%M')
    severity_class = f"severity-{row['severity'].lower()}"
    
    medical_info = f"<strong>MEDICAL INFO:</strong> {row['medical_desc']}<br>" if row['medical_desc'] else ""
    
    st.markdown(f"""
    <div class='injury-item'>
        <div class='injury-headline'>{row['player']} - {row['injury_type'].upper()}</div>
        <div class='injury-meta'>{timestamp} | {row['team']} | {row['position']} | 
            <span class='{severity_class}'>[{row['injury_code']}]</span>
        </div>
        <div class='injury-details'>
            <strong>STATUS:</strong> <span class='{severity_class}'>{row['status']}</span><br>
            <strong>SEVERITY:</strong> <span class='{severity_class}'>{row['severity']}</span><br>
            <strong>RECOVERY:</strong> {row['recovery_time']}<br>
            {medical_info}
            <strong>DETAILS:</strong> {row['description']}<br>
            <strong>SOURCE:</strong> ESPN Official API
        </div>
    </div>
    """, unsafe_allow_html=True)

# =============================================================================
# MAIN APPLICATION
# =============================================================================

def main():
    """Main application"""
    apply_custom_css()
    render_header()
    
    mode, selected_team, date_filter = render_sidebar_filters()
    
    # Additional filters for injuries
    selected_status = None
    selected_severity = None
    
    if mode == "INJURIES":
        st.sidebar.markdown("### INJURY FILTERS")
        
        status_options = ['ALL STATUS', 'Out', 'Questionable', 'Doubtful', 'Day-To-Day', 'IR']
        selected_status = st.sidebar.selectbox('STATUS', status_options)
        
        severity_options = ['ALL', 'CRITICAL', 'SERIOUS', 'MODERATE', 'MILD']
        selected_severity = st.sidebar.selectbox('SEVERITY', severity_options)
    
    # Fetch data
    with st.spinner(f'LOADING {mode} DATA...'):
        if mode == "NEWS":
            df = fetch_news_data()
        else:
            df = fetch_injury_data_espn()
    
    if df.empty:
        st.warning(f"No {mode} data available")
        return
    
    # Apply filters
    df_filtered = DataProcessor.filter_by_team(df, selected_team)
    
    # Date filter
    date_hours = {'24H': 24, '3D': 72, '7D': 168}
    df_filtered = DataProcessor.filter_by_date(df_filtered, date_hours.get(date_filter, 168))
    
    # Injury-specific filters
    if mode == "INJURIES":
        if selected_status != 'ALL STATUS':
            df_filtered = df_filtered[df_filtered['status'].str.contains(selected_status, case=False, na=False)]
        
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
    if st.sidebar.button("↻ REFRESH DATA"):
        st.cache_data.clear()
        st.rerun()

if __name__ == "__main__":
    main()
