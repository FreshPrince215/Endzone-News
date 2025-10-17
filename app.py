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
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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
            config = json.load(f)
        logging.info("Config loaded successfully")
        return config
    except Exception as e:
        logging.error(f"Error loading config: {e}")
        st.error(f"❌ Error loading config.json: {e}")
        st.stop()

CONFIG = load_config()
APP = CONFIG.get('app', {})
TEAMS = CONFIG.get('teams', [])
RSS_FEEDS = CONFIG.get('rss_feeds', {})
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
# ESPN INJURY CLIENT
# =============================================================================

class ESPNInjuryClient:
    """Fetch real injury data from ESPN API"""
    
    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
    
    def fetch_all_injuries(self) -> pd.DataFrame:
        """Fetch all current NFL injuries"""
        try:
            url = f"{self.BASE_URL}/injuries"
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            injuries = []
            
            for team_data in data.get('items', []):
                team_name = team_data.get('team', {}).get('displayName', 'Unknown')
                
                for player_data in team_data.get('injuries', []):
                    athlete = player_data.get('athlete', {})
                    
                    status = player_data.get('status', '')
                    if not status or status.lower() == 'active':
                        continue
                    
                    injuries.append({
                        'team': team_name,
                        'player': athlete.get('displayName', 'Unknown'),
                        'position': athlete.get('position', {}).get('abbreviation', 'N/A'),
                        'status': status,
                        'description': player_data.get('longComment', player_data.get('shortComment', 'No details available')),
                        'date': datetime.now(),
                        'source': 'ESPN Official'
                    })
            
            if not injuries:
                return pd.DataFrame()
            
            df = pd.DataFrame(injuries)
            df['severity'] = df['status'].apply(self._classify_severity)
            df = df.drop_duplicates(subset=['player', 'team'])
            df = df.sort_values('date', ascending=False)
            
            logging.info(f"Fetched {len(df)} injuries")
            return df
            
        except requests.exceptions.RequestException as e:
            logging.error(f"Network error fetching injuries: {e}")
            st.error(f"Error fetching injuries: {e}")
            return pd.DataFrame()
        except Exception as e:
            logging.error(f"Unexpected error fetching injuries: {e}")
            st.error(f"Error fetching injuries: {e}")
            return pd.DataFrame()
    
    @staticmethod
    def _classify_severity(status: str) -> str:
        """Classify injury severity"""
        status_lower = status.lower()
        
        if any(word in status_lower for word in ['out', 'ir', 'reserve']):
            return 'CRITICAL'
        elif 'doubtful' in status_lower:
            return 'SERIOUS'
        elif 'questionable' in status_lower:
            return 'MODERATE'
        else:
            return 'MILD'

# =============================================================================
# NEWS FEED UTILITIES
# =============================================================================

class FeedFetcher:
    """RSS feed fetching and processing"""
    
    def __init__(self, days_lookback: int = 7, max_entries: int = 30):
        self.days_lookback = days_lookback
        self.max_entries = max_entries
        self.cutoff_date = datetime.now() - timedelta(days=days_lookback)
    
    def fetch_single_feed(self, url: str) -> List[Dict]:
        """Fetch a single RSS feed"""
        try:
            feed = feedparser.parse(url)
            articles = []
            
            for entry in feed.entries[:self.max_entries]:
                title = entry.get('title', '')
                link = entry.get('link', '')
                
                pub_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
                pub_date = datetime(*pub_parsed[:6]) if pub_parsed else datetime.now()
                
                if pub_date >= self.cutoff_date:
                    articles.append({
                        'title': title,
                        'link': link,
                        'published': pub_date
                    })
            
            return articles
        except Exception as e:
            logging.warning(f"Error fetching feed {url}: {e}")
            return []
    
    def fetch_multiple_feeds(self, feeds: List[str], max_workers: int = 10) -> List[Dict]:
        """Fetch multiple feeds in parallel"""
        articles = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.fetch_single_feed, url): url for url in feeds}
            
            for future in as_completed(futures):
                try:
                    articles.extend(future.result())
                except Exception as e:
                    logging.warning(f"Error in future for {futures[future]}: {e}")
        
        return articles

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

class DataProcessor:
    """Data processing utilities"""
    
    @staticmethod
    def create_hash(text: str) -> str:
        """Create MD5 hash for deduplication"""
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
# NFLVERSE STATS CLIENT
# =============================================================================

class NFLVerseStatsClient:
    """Fetch player stats from ESPN web pages"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
    
    def fetch_player_stats(self, stat_type: str = 'passing') -> pd.DataFrame:
        """Fetch player statistics by type"""
        try:
            base_url = "https://www.espn.com/nfl/stats/player/_/stat/"
            if stat_type == 'defense':
                url = base_url + "defense/table/defensive/sort/sacks/dir/desc"
                value_col = 'SACK'
                stat_name = 'Sacks'
            elif stat_type == 'passing':
                url = base_url + "passing"
                value_col = 'YDS'
                stat_name = 'Passing Yards'
            elif stat_type == 'rushing':
                url = base_url + "rushing"
                value_col = 'YDS'
                stat_name = 'Rushing Yards'
            elif stat_type == 'receiving':
                url = base_url + "receiving"
                value_col = 'YDS'
                stat_name = 'Receiving Yards'
            else:
                return pd.DataFrame()
            
            dfs = pd.read_html(url)
            if len(dfs) < 2:
                return pd.DataFrame()
            
            df1 = dfs[0]
            df2 = dfs[1]
            df = pd.concat([df1, df2], axis=1)
            df = df.dropna(subset=['RK']).reset_index(drop=True)
            
            df['rank'] = df['RK'].astype(int)
            df['position'] = df['POS']
            df['value'] = df[value_col].str.replace(',', '').astype(float)
            df['stat_type'] = stat_name
            
            # Parse player and team
            def parse_player_team(player_str):
                match = re.match(r'^(.*?) ([A-Z/]{2,})$', player_str)
                if match:
                    return match.group(1), match.group(2)
                return player_str, 'FA'
            
            df[['player_name', 'team']] = df['PLAYER'].apply(parse_player_team).apply(pd.Series)
            
            df = df[['player_name', 'team', 'position', 'stat_type', 'value', 'rank']]
            
            logging.info(f"Fetched {len(df)} {stat_type} stats")
            return df.sort_values('rank')
            
        except Exception as e:
            logging.error(f"Error fetching {stat_type} stats: {e}")
            return pd.DataFrame()
    
    def search_player(self, player_name: str) -> pd.DataFrame:
        """Search for a specific player's stats"""
        all_stats = []
        
        for stat_type in ['passing', 'rushing', 'receiving', 'defense']:
            df = self.fetch_player_stats(stat_type)
            if not df.empty:
                all_stats.append(df)
        
        if not all_stats:
            return pd.DataFrame()
        
        df_all = pd.concat(all_stats, ignore_index=True)
        
        mask = df_all['player_name'].str.contains(player_name, case=False, na=False)
        return df_all[mask]

# =============================================================================
# DATA FETCHING FUNCTIONS
# =============================================================================

@st.cache_data(ttl=APP.get('cache_ttl', 1800), show_spinner=False)
def fetch_news_data() -> pd.DataFrame:
    """Fetch news from RSS feeds"""
    fetcher = FeedFetcher(days_lookback=APP.get('days_lookback', 7))
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
        logging.warning("No news items fetched")
        return pd.DataFrame()
    
    df = pd.DataFrame(news_items)
    df = DataProcessor.deduplicate_dataframe(df, ['headline', 'link'])
    df = df.sort_values('date', ascending=False)
    
    logging.info(f"Fetched {len(df)} news items")
    return df

@st.cache_data(ttl=APP.get('cache_ttl', 1800), show_spinner=False)
def fetch_injury_data() -> pd.DataFrame:
    """Fetch injury data from ESPN"""
    client = ESPNInjuryClient()
    return client.fetch_all_injuries()

# =============================================================================
# UI COMPONENTS
# =============================================================================

def apply_custom_css():
    """Apply custom CSS styling"""
    theme = UI.get('theme', {})
    
    st.markdown(f"""
    <style>
        .main {{background-color: {theme.get('background', '#000000')};}}
        .news-item {{border-left: 3px solid {theme.get('primary_color', '#00FF00')}; padding: 10px; margin-bottom: 15px; background-color: #1A1A1A; font-family: 'Courier New', monospace;}}
        .injury-item {{border-left: 3px solid {theme.get('secondary_color', '#FF0000')}; padding: 10px; margin-bottom: 15px; background-color: #1A1A1A; font-family: 'Courier New', monospace;}}
        .stat-card {{border-left: 3px solid #FFD700; padding: 10px; margin-bottom: 15px; background-color: #1A1A1A; font-family: 'Courier New', monospace;}}
        .news-headline {{color: {theme.get('primary_color', '#00FF00')}; font-size: 14px; font-weight: bold;}}
        .injury-headline {{color: #FF6666; font-size: 14px; font-weight: bold;}}
        .stat-headline {{color: #FFD700; font-size: 14px; font-weight: bold;}}
        .news-meta, .injury-meta, .stat-meta {{color: {theme.get('meta_color', '#888888')}; font-size: 11px; margin-top: 5px;}}
        .injury-details {{background-color: #0D0D0D; padding: 8px; margin-top: 8px; border-left: 2px solid {theme.get('secondary_color', '#FF0000')}; font-size: 11px; color: #CCCCCC;}}
        .severity-critical {{color: #FF0000; font-weight: bold;}}
        .severity-serious {{color: #FF6600; font-weight: bold;}}
        .severity-moderate {{color: #FFAA00; font-weight: bold;}}
        .severity-mild {{color: #FFFF00; font-weight: bold;}}
        .ticker {{color: {theme.get('primary_color', '#00FF00')}; font-family: 'Courier New', monospace; font-size: 12px;}}
        .stRadio > label, .stSelectbox > label {{color: {theme.get('primary_color', '#00FF00')};}}
        .search-box {{background-color: #1A1A1A; border: 1px solid #00FF00; color: #00FF00; font-family: 'Courier New', monospace;}}
    </style>
    """, unsafe_allow_html=True)

def render_header():
    """Render page header"""
    st.markdown(f"## {APP.get('page_icon', '🏈')} {APP.get('title', 'NFL TERMINAL').upper()}")
    st.markdown(f"<p class='ticker'>SYSTEM TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>", 
                unsafe_allow_html=True)

def render_sidebar_filters() -> Tuple[str, str, str]:
    """Render sidebar filters"""
    st.sidebar.markdown("### TERMINAL MODE")
    mode = st.sidebar.radio("SELECT MODE", ["NEWS", "INJURIES", "PLAYER STATS"])
    
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
    """Render a news item"""
    timestamp = row['date'].strftime('%m/%d %H:%M')
    st.markdown(f"""
    <div class='news-item'>
        <a href='{row['link']}' target='_blank' class='news-headline'>{row['headline']}</a>
        <div class='news-meta'>{timestamp} | {row['team']}</div>
    </div>
    """, unsafe_allow_html=True)

def render_injury_item(row: pd.Series):
    """Render an injury item"""
    timestamp = row['date'].strftime('%m/%d %H:%M')
    severity_class = f"severity-{row['severity'].lower()}"
    
    st.markdown(f"""
    <div class='injury-item'>
        <div class='injury-headline'>{row['player']}</div>
        <div class='injury-meta'>{timestamp} | {row['team']} | {row['position']} | <span class='{severity_class}'>[{row['status']}]</span></div>
        <div class='injury-details'>
            <strong>STATUS:</strong> <span class='{severity_class}'>{row['status']}</span><br>
            <strong>SEVERITY:</strong> <span class='{severity_class}'>{row['severity']}</span><br>
            <strong>DETAILS:</strong> {row['description']}<br>
            <strong>SOURCE:</strong> {row['source']}
        </div>
    </div>
    """, unsafe_allow_html=True)

# =============================================================================
# PLAYER STATS PAGE (StatMuse-style)
# =============================================================================

def render_player_stats_page():
    """Render StatMuse-style player stats interface"""
    st.markdown("### 🎯 PLAYER STATISTICS - ASK ANYTHING")
    
    # Search interface
    col1, col2 = st.columns([3, 1])
    
    with col1:
        query = st.text_input(
            "Search Player Stats",
            placeholder="e.g., Patrick Mahomes, Lamar Jackson, Christian McCaffrey",
            key="player_search"
        )
    
    with col2:
        search_button = st.button("🔍 SEARCH", type="primary", use_container_width=True)
    
    if search_button and query:
        with st.spinner(f"Searching for {query}..."):
            client = NFLVerseStatsClient()
            df_results = client.search_player(query)
        
        if df_results.empty:
            st.warning(f"No stats found for '{query}'")
            return
        
        # Display results
        st.success(f"Found stats for {df_results['player_name'].nunique()} player(s)")
        
        # Group by player
        for player in df_results['player_name'].unique():
            player_data = df_results[df_results['player_name'] == player]
            team = player_data.iloc[0]['team']
            position = player_data.iloc[0]['position']
            
            with st.expander(f"📊 {player} - {team} ({position})", expanded=True):
                # Stats table
                stats_table = player_data[['stat_type', 'value', 'rank']].copy()
                stats_table.columns = ['Category', 'Value', 'Rank']
                stats_table = stats_table.sort_values('Rank')
                
                st.dataframe(stats_table, use_container_width=True, hide_index=True)
                
                # Visualize top stats
                if len(stats_table) > 0:
                    st.markdown(f"#### {player} - Top Statistics")
                    st.bar_chart(stats_table.head(10), x='Category', y='Value')
    
    # Leaderboards
    st.markdown("---")
    st.markdown("### 🏆 LEAGUE LEADERBOARDS")
    
    tab1, tab2, tab3, tab4 = st.tabs(["🎯 PASSING", "🏃 RUSHING", "🙌 RECEIVING", "🛡️ DEFENSE"])
    
    with tab1:
        render_leaderboard("passing")
    
    with tab2:
        render_leaderboard("rushing")
    
    with tab3:
        render_leaderboard("receiving")
    
    with tab4:
        render_leaderboard("defense")

def render_leaderboard(stat_type: str):
    """Render a statistical leaderboard"""
    client = NFLVerseStatsClient()
    
    with st.spinner(f"Loading {stat_type} leaders..."):
        df_stats = client.fetch_player_stats(stat_type)
    
    if df_stats.empty:
        st.warning(f"No {stat_type} stats available")
        return
    
    category = df_stats['stat_type'].iloc[0]
    st.markdown(f"#### {category}")
    
    cat_data = df_stats.sort_values('rank').head(10)
    
    for idx, row in cat_data.iterrows():
        rank_color = '#FFD700' if row['rank'] <= 3 else '#00FF00'
        
        st.markdown(f"""
        <div class='stat-card' style='border-left-color: {rank_color};'>
            <span style='color: {rank_color}; font-weight: bold;'>#{int(row['rank'])}</span> 
            <span style='color: #FFFFFF; font-weight: bold;'>{row['player_name']}</span> 
            <span style='color: #888888;'>| {row['team']} | {row['position']}</span>
            <span style='color: #00FF00; float: right; font-weight: bold;'>{row['value']:.1f}</span>
        </div>
        """, unsafe_allow_html=True)

# =============================================================================
# MAIN APPLICATION
# =============================================================================

def main():
    """Main application logic"""
    apply_custom_css()
    render_header()
    
    mode, selected_team, date_filter = render_sidebar_filters()
    
    # PLAYER STATS MODE
    if mode == "PLAYER STATS":
        render_player_stats_page()
        
        st.sidebar.markdown("---")
        if st.sidebar.button("↻ REFRESH DATA"):
            st.cache_data.clear()
            st.rerun()
        return
    
    # NEWS/INJURIES MODE
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
        st.markdown(f"<p class='ticker'>NO {mode} DATA FOR {selected_team} IN {date_filter}</p>", 
                   unsafe_allow_html=True)
    
    st.sidebar.markdown("---")
    if st.sidebar.button("↻ REFRESH DATA"):
        st.cache_data.clear()
        st.rerun()

if __name__ == "__main__":
    main()
