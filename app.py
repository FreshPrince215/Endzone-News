"""
NFL Terminal - News & Injury Tracker
Real-time news + Official NFL.com injury scraping
"""

import feedparser
import pandas as pd
import re
import json
import hashlib
import requests
from bs4 import BeautifulSoup
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
# NFL.COM INJURY SCRAPER
# =============================================================================

class NFLInjuryScraper:
    """Scrape official injury data from NFL.com"""
    
    BASE_URL = "https://www.nfl.com/injuries/league"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def get_current_week(self) -> int:
        """Determine current NFL week"""
        # NFL season starts first Thursday in September
        # Approximate current week based on date
        now = datetime.now()
        
        # 2025 season started Sep 4
        season_start = datetime(2025, 9, 4)
        
        if now < season_start:
            return 1
        
        days_since_start = (now - season_start).days
        current_week = (days_since_start // 7) + 1
        
        return min(current_week, 18)  # Max 18 weeks in regular season
    
    def scrape_week(self, year: int, week: int) -> List[Dict]:
        """Scrape injuries for a specific week"""
        url = f"{self.BASE_URL}/{year}/REG{week}"
        injuries = []
        
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            tables = soup.findAll("table")
            
            for table in tables:
                # Only process top-level tables
                if table.findParent("table") is None:
                    for tr in table.find_all('tr'):
                        td = tr.find_all('td')
                        rows = [cell.text.strip() for cell in td if cell and len(cell.text.strip()) > 0]
                        
                        if len(rows) >= 4:  # Need at least team, player, position, status
                            injuries.append({
                                'team': rows[0] if len(rows) > 0 else 'Unknown',
                                'player': rows[1] if len(rows) > 1 else 'Unknown',
                                'position': rows[2] if len(rows) > 2 else 'N/A',
                                'status': rows[3] if len(rows) > 3 else 'Unknown',
                                'description': rows[4] if len(rows) > 4 else 'No details',
                                'week': week,
                                'year': year,
                                'source': 'NFL.com Official'
                            })
            
            return injuries
            
        except requests.RequestException as e:
            return []
        except Exception as e:
            return []
    
    def scrape_current_season(self, weeks_back: int = 3) -> pd.DataFrame:
        """Scrape injuries from current season (last N weeks)"""
        current_year = 2025
        current_week = self.get_current_week()
        
        # Get last N weeks
        weeks_to_scrape = list(range(max(1, current_week - weeks_back + 1), current_week + 1))
        
        all_injuries = []
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, week in enumerate(weeks_to_scrape):
            status_text.text(f"Scraping Week {week}...")
            progress_bar.progress((idx + 1) / len(weeks_to_scrape))
            
            injuries = self.scrape_week(current_year, week)
            all_injuries.extend(injuries)
        
        progress_bar.empty()
        status_text.empty()
        
        if not all_injuries:
            return pd.DataFrame()
        
        df = pd.DataFrame(all_injuries)
        
        # Filter for relevant statuses
        relevant_statuses = ['Out', 'Questionable', 'Doubtful', 'IR']
        df = df[df['status'].isin(relevant_statuses)]
        
        # Add date (approximate - use current date for latest week)
        df['date'] = df['week'].apply(
            lambda w: datetime.now() - timedelta(days=(current_week - w) * 7)
        )
        
        return df
    
    def identify_injury_type(self, description: str) -> str:
        """Identify injury type from description"""
        desc_lower = description.lower()
        
        priority = ['concussion', 'acl', 'mcl', 'hamstring', 'ankle', 'knee', 'shoulder']
        for injury in priority:
            if injury in desc_lower:
                return injury
        
        for injury in INJURY_DB.keys():
            if injury in desc_lower:
                return injury
        
        return 'general'
    
    def enhance_injury_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add enhanced injury information"""
        if df.empty:
            return df
        
        # Identify injury types
        df['injury_type'] = df['description'].apply(self.identify_injury_type)
        
        # Add severity classification
        df['severity'] = df['status'].apply(self.classify_severity)
        
        # Add injury database info
        df['injury_info'] = df['injury_type'].apply(
            lambda x: INJURY_DB.get(x, INJURY_DB.get('general', {}))
        )
        
        df['injury_code'] = df['injury_info'].apply(lambda x: x.get('code', 'INJ'))
        df['recovery_time'] = df['injury_info'].apply(lambda x: x.get('recovery', 'Variable'))
        df['medical_desc'] = df['injury_info'].apply(lambda x: x.get('description', ''))
        
        # Remove duplicates (same player, same injury)
        df = df.drop_duplicates(subset=['player', 'team', 'injury_type'], keep='last')
        
        # Sort by week (most recent first)
        df = df.sort_values('week', ascending=False)
        
        return df
    
    @staticmethod
    def classify_severity(status: str) -> str:
        """Classify injury severity based on status"""
        status_lower = status.lower()
        
        if 'out' in status_lower or 'ir' in status_lower:
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
    """Fetch news from RSS feeds"""
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
    """Fetch injury data from NFL.com"""
    st.info("🔄 Scraping official NFL.com injury data...")
    
    scraper = NFLInjuryScraper()
    df = scraper.scrape_current_season(weeks_back=3)
    
    if df.empty:
        st.warning("⚠️ No injuries found on NFL.com")
        return pd.DataFrame()
    
    st.success(f"✅ Found {len(df)} injuries from NFL.com")
    
    # Enhance with injury database info
    df = scraper.enhance_injury_data(df)
    
    return df

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
    mode = st.sidebar.radio("SELECT MODE", ["NEWS", "INJURIES", "PLAYER STATS"])
    
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
    week_display = f"Week {row['week']}"
    severity_class = f"severity-{row['severity'].lower()}"
    medical_info = f"<strong>MEDICAL:</strong> {row['medical_desc']}<br>" if row['medical_desc'] else ""
    
    st.markdown(f"""
    <div class='injury-item'>
        <div class='injury-headline'>{row['player']} - {row['injury_type'].upper()}</div>
        <div class='injury-meta'>{week_display} | {row['team']} | {row['position']} | <span class='{severity_class}'>[{row['injury_code']}]</span></div>
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
# PLAYER STATS MODULE
# =============================================================================

class PlayerStatsClient:
    """Fetch and analyze player statistics"""
    
    ESPN_API = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
    
    def fetch_player_stats(self, season: int = 2025) -> pd.DataFrame:
        """Fetch player stats for current season"""
        try:
            url = f"{self.ESPN_API}/leaders"
            response = self.session.get(url, timeout=10)
            
            if response.status_code != 200:
                return pd.DataFrame()
            
            data = response.json()
            players = []
            
            # Extract player data from leaders
            for category in data.get('categories', []):
                cat_name = category.get('displayName', '')
                
                for leader in category.get('leaders', []):
                    athlete = leader.get('athlete', {})
                    team = leader.get('team', {})
                    
                    players.append({
                        'player_name': athlete.get('displayName', 'Unknown'),
                        'team': team.get('displayName', 'Unknown'),
                        'position': athlete.get('position', {}).get('abbreviation', 'N/A'),
                        'category': cat_name,
                        'value': leader.get('value', 0),
                        'rank': leader.get('rank', 999)
                    })
            
            return pd.DataFrame(players) if players else pd.DataFrame()
            
        except Exception:
            return pd.DataFrame()
    
    def fetch_team_roster(self, team_id: str) -> pd.DataFrame:
        """Fetch team roster"""
        try:
            url = f"{self.ESPN_API}/teams/{team_id}/roster"
            response = self.session.get(url, timeout=10)
            
            if response.status_code != 200:
                return pd.DataFrame()
            
            data = response.json()
            roster = []
            
            for athlete in data.get('athletes', []):
                roster.append({
                    'player_name': athlete.get('displayName', 'Unknown'),
                    'position': athlete.get('position', {}).get('abbreviation', 'N/A'),
                    'jersey': athlete.get('jersey', 'N/A'),
                    'age': athlete.get('age', 'N/A'),
                    'height': athlete.get('height', 'N/A'),
                    'weight': athlete.get('weight', 'N/A')
                })
            
            return pd.DataFrame(roster) if roster else pd.DataFrame()
            
        except Exception:
            return pd.DataFrame()

def render_player_stats_page():
    """Render player stats and comparison page"""
    st.markdown("### 📊 PLAYER STATISTICS & ANALYSIS")
    
    tab1, tab2, tab3 = st.tabs(["🏆 LEADERBOARDS", "⚖️ PLAYER COMPARISON", "📈 TEAM ROSTER"])
    
    with tab1:
        render_leaderboards()
    
    with tab2:
        render_player_comparison()
    
    with tab3:
        render_team_roster()

def render_leaderboards():
    """Render statistical leaderboards"""
    st.markdown("#### Season Leaders")
    
    client = PlayerStatsClient()
    
    with st.spinner("Fetching player stats..."):
        df_stats = client.fetch_player_stats()
    
    if df_stats.empty:
        st.warning("No player stats available")
        return
    
    # Category selector
    categories = df_stats['category'].unique().tolist()
    selected_category = st.selectbox("Select Category", categories)
    
    # Filter by category
    df_filtered = df_stats[df_stats['category'] == selected_category].copy()
    df_filtered = df_filtered.sort_values('rank')
    
    # Display leaderboard
    st.markdown(f"##### {selected_category}")
    
    for idx, row in df_filtered.head(20).iterrows():
        rank_color = '#FFD700' if row['rank'] <= 3 else '#00FF00'
        
        st.markdown(f"""
        <div style='background-color: #1A1A1A; padding: 10px; margin: 5px 0; border-left: 3px solid {rank_color}; font-family: "Courier New", monospace;'>
            <span style='color: {rank_color}; font-weight: bold;'>#{row['rank']}</span> 
            <span style='color: #FFFFFF;'>{row['player_name']}</span> 
            <span style='color: #888888;'>| {row['team']} | {row['position']}</span>
            <span style='color: #00FF00; float: right; font-weight: bold;'>{row['value']}</span>
        </div>
        """, unsafe_allow_html=True)

def render_player_comparison():
    """Render player comparison tool"""
    st.markdown("#### Compare Players")
    
    client = PlayerStatsClient()
    
    with st.spinner("Loading player data..."):
        df_stats = client.fetch_player_stats()
    
    if df_stats.empty:
        st.warning("No player data available")
        return
    
    # Get unique players
    players = sorted(df_stats['player_name'].unique().tolist())
    
    col1, col2 = st.columns(2)
    
    with col1:
        player1 = st.selectbox("Player 1", players, key='p1')
    
    with col2:
        player2 = st.selectbox("Player 2", players, key='p2')
    
    if st.button("COMPARE PLAYERS", type="primary"):
        # Get stats for both players
        p1_stats = df_stats[df_stats['player_name'] == player1]
        p2_stats = df_stats[df_stats['player_name'] == player2]
        
        if p1_stats.empty or p2_stats.empty:
            st.warning("Stats not available for selected players")
            return
        
        # Display comparison
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown(f"##### {player1}")
            p1_team = p1_stats.iloc[0]['team']
            p1_pos = p1_stats.iloc[0]['position']
            st.markdown(f"**Team:** {p1_team}")
            st.markdown(f"**Position:** {p1_pos}")
            st.markdown("---")
            
            for _, row in p1_stats.iterrows():
                st.markdown(f"**{row['category']}:** {row['value']} (Rank: #{row['rank']})")
        
        with col2:
            st.markdown(f"##### {player2}")
            p2_team = p2_stats.iloc[0]['team']
            p2_pos = p2_stats.iloc[0]['position']
            st.markdown(f"**Team:** {p2_team}")
            st.markdown(f"**Position:** {p2_pos}")
            st.markdown("---")
            
            for _, row in p2_stats.iterrows():
                st.markdown(f"**{row['category']}:** {row['value']} (Rank: #{row['rank']})")
        
        # Side-by-side comparison table
        st.markdown("---")
        st.markdown("##### Statistical Comparison")
        
        # Merge stats
        comparison = []
        for cat in p1_stats['category'].unique():
            p1_val = p1_stats[p1_stats['category'] == cat]['value'].values[0] if not p1_stats[p1_stats['category'] == cat].empty else 0
            p2_val = p2_stats[p2_stats['category'] == cat]['value'].values[0] if not p2_stats[p2_stats['category'] == cat].empty else 0
            
            comparison.append({
                'Category': cat,
                player1: p1_val,
                player2: p2_val,
                'Advantage': player1 if p1_val > p2_val else (player2 if p2_val > p1_val else 'Tie')
            })
        
        df_comparison = pd.DataFrame(comparison)
        st.dataframe(df_comparison, use_container_width=True)

def render_team_roster():
    """Render team roster viewer"""
    st.markdown("#### Team Roster")
    
    # Team selector (using ESPN team IDs)
    team_mapping = {
        'Arizona Cardinals': '22', 'Atlanta Falcons': '1', 'Baltimore Ravens': '33',
        'Buffalo Bills': '2', 'Carolina Panthers': '29', 'Chicago Bears': '3',
        'Cincinnati Bengals': '4', 'Cleveland Browns': '5', 'Dallas Cowboys': '6',
        'Denver Broncos': '7', 'Detroit Lions': '8', 'Green Bay Packers': '9',
        'Houston Texans': '34', 'Indianapolis Colts': '11', 'Jacksonville Jaguars': '30',
        'Kansas City Chiefs': '12', 'Las Vegas Raiders': '13', 'Los Angeles Chargers': '24',
        'Los Angeles Rams': '14', 'Miami Dolphins': '15', 'Minnesota Vikings': '16',
        'New England Patriots': '17', 'New Orleans Saints': '18', 'New York Giants': '19',
        'New York Jets': '20', 'Philadelphia Eagles': '21', 'Pittsburgh Steelers': '23',
        'San Francisco 49ers': '25', 'Seattle Seahawks': '26', 'Tampa Bay Buccaneers': '27',
        'Tennessee Titans': '10', 'Washington Commanders': '28'
    }
    
    selected_team_name = st.selectbox("Select Team", sorted(team_mapping.keys()))
    team_id = team_mapping[selected_team_name]
    
    if st.button("LOAD ROSTER", type="primary"):
        client = PlayerStatsClient()
        
        with st.spinner(f"Loading {selected_team_name} roster..."):
            df_roster = client.fetch_team_roster(team_id)
        
        if df_roster.empty:
            st.warning("Roster data not available")
            return
        
        # Position filter
        positions = ['ALL'] + sorted(df_roster['position'].unique().tolist())
        selected_position = st.selectbox("Filter by Position", positions)
        
        if selected_position != 'ALL':
            df_roster = df_roster[df_roster['position'] == selected_position]
        
        # Display roster
        st.markdown(f"##### {selected_team_name} - {len(df_roster)} Players")
        
        # Group by position
        for position in sorted(df_roster['position'].unique()):
            with st.expander(f"{position} ({len(df_roster[df_roster['position'] == position])})"):
                pos_players = df_roster[df_roster['position'] == position]
                
                for _, player in pos_players.iterrows():
                    st.markdown(f"""
                    <div style='background-color: #1A1A1A; padding: 10px; margin: 5px 0; border-left: 3px solid #00FF00; font-family: "Courier New", monospace;'>
                        <span style='color: #00FF00; font-weight: bold;'>#{player['jersey']}</span> 
                        <span style='color: #FFFFFF;'>{player['player_name']}</span><br>
                        <span style='color: #888888; font-size: 11px;'>Age: {player['age']} | Ht: {player['height']} | Wt: {player['weight']}</span>
                    </div>
                    """, unsafe_allow_html=True)

# =============================================================================
# MAIN APPLICATION
# =============================================================================

def main():
    apply_custom_css()
    render_header()
    
    mode, selected_team, date_filter = render_sidebar_filters()
    
    # PLAYER STATS MODE
    if mode == "PLAYER STATS":
        render_player_stats_page()
        
        # Refresh button
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
        st.markdown(f"<p class='ticker'>NO {mode} DATA FOR {selected_team} IN {date_filter}</p>", unsafe_allow_html=True)
    
    st.sidebar.markdown("---")
    if st.sidebar.button("↻ REFRESH DATA"):
        st.cache_data.clear()
        st.rerun()

if __name__ == "__main__":
    main()
