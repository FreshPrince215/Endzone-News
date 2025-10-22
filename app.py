import feedparser
import pandas as pd
import json
import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit as st
import streamlit.components.v1 as components
# =============================================================================
# CONFIGURATION
# =============================================================================
@st.cache_resource
def load_config() -> Dict:
    """Load configuration from config.json"""
    config_path = Path(__file__).parent / 'config.json'
  
    if not config_path.exists():
        st.error("⚠️ config.json not found. Please create config.json in the same directory.")
        st.stop()
  
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"❌ Error loading config.json: {e}")
        st.stop()
CONFIG = load_config()
APP = CONFIG.get('app', {})
TEAMS = CONFIG.get('teams', [])
RSS_FEEDS = CONFIG.get('rss_feeds', {})
PLAYER_HIGHLIGHTS = CONFIG.get('player_highlights', {})
INJURY_ANALYSIS = CONFIG.get('injury_analysis', {})
# =============================================================================
# PAGE CONFIGURATION
# =============================================================================
st.set_page_config(
    page_title=APP.get('title', 'NFL News Terminal'),
    page_icon=APP.get('page_icon', '🏈'),
    layout="wide",
    initial_sidebar_state="collapsed"
)
# =============================================================================
# FEED FETCHER
# =============================================================================
class FeedFetcher:
    """RSS feed fetching with robust error handling"""
  
    def __init__(self, days_lookback: int = 7, max_entries: int = 100):
        self.days_lookback = days_lookback
        self.max_entries = max_entries
        self.cutoff_date = datetime.now() - timedelta(days=days_lookback)
        self.success_count = 0
        self.error_count = 0
  
    def clean_html(self, text: str) -> str:
        """Remove HTML tags and clean text"""
        if not text:
            return ""
        text = re.sub(r'<[^>]+>', '', text)
        text = ' '.join(text.split())
        if len(text) > 300:
            text = text[:300] + '...'
        return text
  
    def fetch_single_feed(self, url: str, source_name: str = "") -> List[Dict]:
        """Fetch a single RSS feed with error handling"""
        try:
            feed = feedparser.parse(url, request_headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
          
            if not feed.entries:
                self.error_count += 1
                return []
          
            articles = []
            for entry in feed.entries[:self.max_entries]:
                title = entry.get('title', '').strip()
                link = entry.get('link', '')
              
                if not title or not link:
                    continue
              
                pub_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
                if pub_parsed:
                    try:
                        pub_date = datetime(*pub_parsed[:6])
                    except:
                        pub_date = datetime.now()
                else:
                    pub_date = datetime.now()
              
                if pub_date >= self.cutoff_date:
                    summary = entry.get('summary', entry.get('description', ''))
                    summary = self.clean_html(summary)
                  
                    articles.append({
                        'title': title,
                        'link': link,
                        'published': pub_date,
                        'source': source_name,
                        'summary': summary
                    })
          
            self.success_count += 1
            return articles
          
        except Exception as e:
            self.error_count += 1
            return []
  
    def fetch_multiple_feeds(self, feeds: List[Tuple[str, str]], max_workers: int = 10) -> List[Dict]:
        """Fetch multiple feeds in parallel"""
        articles = []
      
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.fetch_single_feed, url, name): (url, name)
                      for url, name in feeds}
          
            for future in as_completed(futures):
                try:
                    articles.extend(future.result())
                except:
                    pass
      
        return articles
# =============================================================================
# DATA PROCESSING
# =============================================================================
class DataProcessor:
    """Data processing utilities"""
  
    @staticmethod
    def create_hash(text: str) -> str:
        """Create MD5 hash for deduplication"""
        return hashlib.md5(text.encode()).hexdigest()
  
    @staticmethod
    def deduplicate_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        """Remove duplicate articles"""
        if df.empty:
            return df
      
        df['hash'] = df['headline'].apply(DataProcessor.create_hash)
        df = df.drop_duplicates(subset=['hash']).drop(columns=['hash'])
      
        return df
  
    @staticmethod
    def extract_team_from_title(text: str, teams: List[str]) -> str:
        """Extract team name from article title"""
        text_upper = text.upper()
      
        team_keywords = {
            'CARDINALS': 'Arizona Cardinals',
            'FALCONS': 'Atlanta Falcons',
            'RAVENS': 'Baltimore Ravens',
            'BILLS': 'Buffalo Bills',
            'PANTHERS': 'Carolina Panthers',
            'BEARS': 'Chicago Bears',
            'BENGALS': 'Cincinnati Bengals',
            'BROWNS': 'Cleveland Browns',
            'COWBOYS': 'Dallas Cowboys',
            'BRONCOS': 'Denver Broncos',
            'LIONS': 'Detroit Lions',
            'PACKERS': 'Green Bay Packers',
            'TEXANS': 'Houston Texans',
            'COLTS': 'Indianapolis Colts',
            'JAGUARS': 'Jacksonville Jaguars',
            'CHIEFS': 'Kansas City Chiefs',
            'RAIDERS': 'Las Vegas Raiders',
            'CHARGERS': 'Los Angeles Chargers',
            'RAMS': 'Los Angeles Rams',
            'DOLPHINS': 'Miami Dolphins',
            'VIKINGS': 'Minnesota Vikings',
            'PATRIOTS': 'New England Patriots',
            'SAINTS': 'New Orleans Saints',
            'GIANTS': 'New York Giants',
            'JETS': 'New York Jets',
            'EAGLES': 'Philadelphia Eagles',
            'STEELERS': 'Pittsburgh Steelers',
            '49ERS': 'San Francisco 49ers',
            'SEAHAWKS': 'Seattle Seahawks',
            'BUCCANEERS': 'Tampa Bay Buccaneers',
            'BUCS': 'Tampa Bay Buccaneers',
            'TITANS': 'Tennessee Titans',
            'COMMANDERS': 'Washington Commanders'
        }
      
        for keyword, team in team_keywords.items():
            if keyword in text_upper:
                return team
      
        for team in teams:
            if team.upper() in text_upper:
                return team
      
        return 'NFL General'
# =============================================================================
# DATA FETCHING
# =============================================================================
@st.cache_data(ttl=APP.get('cache_ttl', 1800), show_spinner=False)
def fetch_all_news() -> pd.DataFrame:
    """Fetch all news from configured RSS feeds"""
    fetcher = FeedFetcher(days_lookback=APP.get('days_lookback', 7))
    news_items = []
  
    general_feeds = [
        (feed['url'], feed['name'])
        for feed in RSS_FEEDS.get('general_news', [])
        if feed.get('enabled', True)
    ]
  
    if general_feeds:
        articles = fetcher.fetch_multiple_feeds(general_feeds, max_workers=APP.get('max_workers', 10))
      
        for article in articles:
            team = DataProcessor.extract_team_from_title(article['title'], TEAMS)
            news_items.append({
                'team': team,
                'headline': article['title'],
                'link': article['link'],
                'date': article['published'],
                'source': article['source'],
                'summary': article['summary']
            })
  
    team_feeds_dict = RSS_FEEDS.get('team_feeds', {})
    for team, feeds in team_feeds_dict.items():
        if isinstance(feeds, list):
            team_feed_list = [(url, team) for url in feeds if url]
            articles = fetcher.fetch_multiple_feeds(team_feed_list, max_workers=APP.get('max_workers', 10))
          
            for article in articles:
                news_items.append({
                    'team': team,
                    'headline': article['title'],
                    'link': article['link'],
                    'date': article['published'],
                    'source': article['source'],
                    'summary': article['summary']
                })
  
    if not news_items:
        return pd.DataFrame()
  
    df = pd.DataFrame(news_items)
    df = DataProcessor.deduplicate_dataframe(df)
    df = df.sort_values('date', ascending=False)
  
    return df
# =============================================================================
# BLOOMBERG TERMINAL UI
# =============================================================================
def apply_bloomberg_css():
    """Apply Bloomberg Terminal inspired CSS"""
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
      
        :root {
            --bg-primary: #0a0e27;
            --bg-secondary: #12172e;
            --bg-tertiary: #1a1f3a;
            --accent-orange: #ff8c00;
            --accent-blue: #00a0dc;
            --accent-green: #00d084;
            --accent-red: #dc2626;
            --text-primary: #e8e8e8;
            --text-secondary: #a0a0a0;
            --border-color: #2a2f4a;
        }
      
        .stApp {
            background-color: var(--bg-primary);
            font-family: 'IBM Plex Sans', -apple-system, sans-serif;
        }
      
        .main {
            background-color: var(--bg-primary);
        }
      
        .terminal-header {
            background: linear-gradient(180deg, var(--bg-secondary) 0%, var(--bg-tertiary) 100%);
            border-bottom: 2px solid var(--accent-orange);
            padding: 20px 30px;
            margin: -20px -20px 30px -20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
      
        .terminal-logo {
            display: flex;
            align-items: center;
            gap: 15px;
        }
      
        .terminal-title {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 24px;
            font-weight: 700;
            color: var(--accent-orange);
            letter-spacing: 2px;
            text-transform: uppercase;
        }
      
        .terminal-subtitle {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 11px;
            color: var(--text-secondary);
            letter-spacing: 1px;
            text-transform: uppercase;
        }
      
        .live-indicator {
            display: flex;
            align-items: center;
            gap: 8px;
            font-family: 'IBM Plex Mono', monospace;
            font-size: 11px;
            color: var(--accent-green);
            text-transform: uppercase;
            letter-spacing: 1px;
        }
      
        .live-dot {
            width: 8px;
            height: 8px;
            background: var(--accent-green);
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
      
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }
      
        .control-label {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 10px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
            font-weight: 600;
        }
      
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 25px;
        }
      
        .stat-box {
            background: var(--bg-secondary);
            border-left: 3px solid var(--accent-orange);
            padding: 15px 20px;
            border-radius: 0;
        }
      
        .stat-value {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 32px;
            font-weight: 700;
            color: var(--accent-orange);
            line-height: 1;
            margin-bottom: 5px;
        }
      
        .stat-label {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 10px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1.5px;
        }
      
        .news-item {
            background: var(--bg-secondary);
            border-left: 3px solid var(--accent-blue);
            padding: 18px 20px;
            margin-bottom: 12px;
            transition: all 0.2s ease;
        }
      
        .news-item:hover {
            background: var(--bg-tertiary);
            border-left-color: var(--accent-orange);
            transform: translateX(3px);
        }
      
        .news-header {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 10px;
            flex-wrap: wrap;
        }
      
        .news-timestamp {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 11px;
            color: var(--accent-green);
            min-width: 80px;
            font-weight: 600;
        }
      
        .news-team {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 11px;
            background: var(--accent-orange);
            color: #000;
            padding: 3px 10px;
            font-weight: 700;
            letter-spacing: 0.5px;
        }
      
        .news-source {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 10px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1px;
        }
      
        .news-headline {
            font-size: 16px;
            font-weight: 600;
            color: var(--text-primary);
            text-decoration: none;
            display: block;
            line-height: 1.5;
            margin-bottom: 8px;
            transition: color 0.2s ease;
        }
      
        .news-headline:hover {
            color: var(--accent-orange);
        }
      
        .news-summary {
            font-size: 13px;
            color: var(--text-secondary);
            line-height: 1.6;
            margin-top: 8px;
        }
      
        /* Player Film Styles */
        .player-card {
            background: var(--bg-secondary);
            border-left: 3px solid var(--accent-blue);
            padding: 20px;
            margin-bottom: 20px;
        }
      
        .player-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            flex-wrap: wrap;
            gap: 10px;
        }
      
        .player-name {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 20px;
            font-weight: 700;
            color: var(--accent-orange);
            letter-spacing: 1px;
        }
      
        .player-info {
            display: flex;
            gap: 20px;
            align-items: center;
        }
      
        .player-badge {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 10px;
            background: var(--bg-tertiary);
            color: var(--accent-green);
            padding: 5px 12px;
            font-weight: 600;
            letter-spacing: 1px;
            border: 1px solid var(--border-color);
        }
      
        .video-container {
            margin-top: 15px;
            border-top: 1px solid var(--border-color);
            padding-top: 15px;
        }
      
        .video-wrapper {
            position: relative;
            padding-bottom: 56.25%;
            height: 0;
            overflow: hidden;
            background: #000;
            margin-bottom: 15px;
        }
      
        .video-wrapper iframe {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            border: 2px solid var(--border-color);
        }
      
        /* Injury Analysis Styles */
        .injury-reel-container {
            background: var(--bg-secondary);
            border-left: 3px solid var(--accent-red);
            padding: 20px;
            margin-bottom: 20px;
        }
      
        .injury-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            flex-wrap: wrap;
            gap: 10px;
        }
      
        .injury-player-name {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 18px;
            font-weight: 700;
            color: var(--accent-red);
            letter-spacing: 1px;
        }
      
        .injury-badge {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 10px;
            background: var(--bg-tertiary);
            color: var(--accent-red);
            padding: 5px 12px;
            font-weight: 600;
            letter-spacing: 1px;
            border: 1px solid var(--accent-red);
        }
      
        .instagram-embed-container {
            max-width: 540px;
            margin: 20px auto;
        }
      
        .stSelectbox > div > div {
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 0;
            color: var(--text-primary);
            font-family: 'IBM Plex Mono', monospace;
        }
      
        .stSelectbox label {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 10px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1px;
            font-weight: 600;
        }
      
        .stButton > button {
            background: var(--bg-tertiary);
            border: 1px solid var(--accent-orange);
            color: var(--accent-orange);
            border-radius: 0;
            padding: 10px 24px;
            font-family: 'IBM Plex Mono', monospace;
            font-weight: 600;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 1px;
            transition: all 0.2s ease;
        }
      
        .stButton > button:hover {
            background: var(--accent-orange);
            color: #000;
        }
      
        .stTabs [data-baseweb="tab-list"] {
            gap: 0px;
            background-color: var(--bg-secondary);
        }
      
        .stTabs [data-baseweb="tab"] {
            background-color: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-bottom: none;
            color: var(--text-secondary);
            font-family: 'IBM Plex Mono', monospace;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            padding: 12px 24px;
        }
      
        .stTabs [data-baseweb="tab"][aria-selected="true"] {
            background-color: var(--bg-primary);
            color: var(--accent-orange);
            border-bottom: 2px solid var(--accent-orange);
        }
      
        ::-webkit-scrollbar {
            width: 10px;
        }
      
        ::-webkit-scrollbar-track {
            background: var(--bg-primary);
        }
      
        ::-webkit-scrollbar-thumb {
            background: var(--accent-orange);
            border-radius: 0;
        }
      
        ::-webkit-scrollbar-thumb:hover {
            background: #ff9d1f;
        }
      
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
        .stDeployButton {display: none;}
      
        .section-header {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 13px;
            color: var(--accent-orange);
            text-transform: uppercase;
            letter-spacing: 2px;
            font-weight: 700;
            margin-bottom: 15px;
            padding-bottom: 8px;
            border-bottom: 1px solid var(--border-color);
        }
    </style>
    """, unsafe_allow_html=True)
def render_terminal_header():
    """Render Bloomberg-style terminal header"""
    current_time = datetime.now().strftime('%H:%M:%S EST')
  
    st.markdown(f"""
    <div class="terminal-header">
        <div class="terminal-logo">
            <div>
                <div class="terminal-title">🏈 NFL TERMINAL</div>
                <div class="terminal-subtitle">Real-Time News Aggregation, Film Room & Injury Analysis</div>
            </div>
        </div>
        <div>
            <div class="live-indicator">
                <div class="live-dot"></div>
                LIVE | {current_time}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
def render_stats_dashboard(df: pd.DataFrame):
    """Render stats dashboard"""
    if df.empty:
        return
  
    total_articles = len(df)
    teams_covered = df['team'].nunique()
    sources = df['source'].nunique()
    last_update = datetime.now().strftime('%H:%M')
  
    st.markdown(f"""
    <div class="stats-grid">
        <div class="stat-box">
            <div class="stat-value">{total_articles}</div>
            <div class="stat-label">TOTAL ARTICLES</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">{teams_covered}</div>
            <div class="stat-label">TEAMS TRACKED</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">{sources}</div>
            <div class="stat-label">DATA SOURCES</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">{last_update}</div>
            <div class="stat-label">LAST REFRESH</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
def render_news_item(row: pd.Series):
    """Render individual news item"""
    timestamp = row['date'].strftime('%H:%M')
  
    summary_html = f"<div class='news-summary'>{row['summary']}</div>" if row['summary'] else ""
  
    st.markdown(f"""
    <div class="news-item">
        <div class="news-header">
            <span class="news-timestamp">{timestamp}</span>
            <span class="news-team">{row['team']}</span>
            <span class="news-source">{row['source']}</span>
        </div>
        <a href="{row['link']}" target="_blank" class="news-headline">
            {row['headline']}
        </a>
        {summary_html}
    </div>
    """, unsafe_allow_html=True)
def render_player_film():
    """Render player film room with embedded videos"""
    st.markdown('<div class="section-header">PLAYER FILM ROOM</div>', unsafe_allow_html=True)
  
    if not PLAYER_HIGHLIGHTS:
        st.info("⚠️ No player highlights configured. Add 'player_highlights' to config.json")
        return
  
    # Team and Player filters
    teams_with_players = sorted(list(PLAYER_HIGHLIGHTS.keys()))
  
    col1, col2 = st.columns([2, 2])
    with col1:
        st.markdown('<div class="control-label">SELECT TEAM</div>', unsafe_allow_html=True)
        selected_team = st.selectbox(
            'Team',
            ['ALL TEAMS'] + teams_with_players,
            label_visibility="collapsed",
            key='film_team_filter'
        )
  
    with col2:
        # Get available players based on team selection
        if selected_team == 'ALL TEAMS':
            all_players = []
            for team_players in PLAYER_HIGHLIGHTS.values():
                all_players.extend(list(team_players.keys()))
            available_players = sorted(all_players)
        else:
            available_players = sorted(list(PLAYER_HIGHLIGHTS.get(selected_team, {}).keys()))
      
        st.markdown('<div class="control-label">SELECT PLAYER</div>', unsafe_allow_html=True)
        selected_player = st.selectbox(
            'Player',
            ['ALL PLAYERS'] + available_players,
            label_visibility="collapsed",
            key='film_player_filter'
        )
  
    # Display players
    teams_to_show = teams_with_players if selected_team == 'ALL TEAMS' else [selected_team]
  
    for team in teams_to_show:
        if team not in PLAYER_HIGHLIGHTS:
            continue
      
        players_dict = PLAYER_HIGHLIGHTS[team]
      
        # Filter players if specific player selected
        if selected_player != 'ALL PLAYERS':
            if selected_player not in players_dict:
                continue
            players_dict = {selected_player: players_dict[selected_player]}
      
        if not players_dict:
            continue
      
        st.markdown(f'<div class="section-header" style="margin-top: 25px;">{team}</div>', unsafe_allow_html=True)
      
        for player_name, player_data in players_dict.items():
            position = player_data.get('position', 'N/A')
            number = player_data.get('number', 'N/A')
            videos = player_data.get('videos', [])
          
            # Player card header
            st.markdown(f"""
            <div class="player-card">
                <div class="player-header">
                    <div class="player-name">#{number} {player_name}</div>
                    <div class="player-info">
                        <span class="player-badge">POS: {position}</span>
                        <span class="player-badge">VIDEOS: {len(videos)}</span>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
          
            # Display videos in columns
            if videos:
                num_cols = min(2, len(videos))
                cols = st.columns(num_cols)
              
                for idx, video_id in enumerate(videos):
                    col_idx = idx % num_cols
                    with cols[col_idx]:
                        st.markdown(f"""
                        <div class="video-wrapper">
                            <iframe
                                src="https://www.youtube.com/embed/{video_id}"
                                frameborder="0"
                                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                                allowfullscreen>
                            </iframe>
                        </div>
                        """, unsafe_allow_html=True)
def render_injury_analysis():
    """Render player injury analysis with Instagram reels"""
    st.markdown('<div class="section-header">⚕️ PLAYER INJURY ANALYSIS</div>', unsafe_allow_html=True)
  
    if not INJURY_ANALYSIS or 'reels' not in INJURY_ANALYSIS:
        st.info("⚠️ No injury analysis configured. Add 'injury_analysis' to config.json")
        return
  
    reels = INJURY_ANALYSIS.get('reels', [])
  
    if not reels:
        st.info("⚠️ No injury analysis reels available.")
        return
  
    # Team and Injury Type filters
    available_teams = sorted(list(set([reel.get('team', 'NFL General') for reel in reels])))
    available_injury_types = sorted(list(set([reel.get('injury_type', 'General Analysis') for reel in reels])))
  
    col1, col2 = st.columns([2, 2])
    with col1:
        st.markdown('<div class="control-label">SELECT TEAM</div>', unsafe_allow_html=True)
        selected_team = st.selectbox(
            'Team',
            ['ALL TEAMS'] + available_teams,
            label_visibility="collapsed",
            key='injury_team_filter'
        )
  
    with col2:
        st.markdown('<div class="control-label">SELECT INJURY TYPE</div>', unsafe_allow_html=True)
        selected_injury = st.selectbox(
            'Injury Type',
            ['ALL TYPES'] + available_injury_types,
            label_visibility="collapsed",
            key='injury_type_filter'
        )
  
    # Filter reels
    reels_to_show = []
    for reel in reels:
        reel_team = reel.get('team', 'NFL General')
        reel_injury = reel.get('injury_type', 'General Analysis')
        if (selected_team == 'ALL TEAMS' or reel_team == selected_team) and \
           (selected_injury == 'ALL TYPES' or reel_injury == selected_injury):
            reels_to_show.append(reel)
  
    if not reels_to_show:
        st.info("No injury analyses match the selected filters.")
    else:
        for reel in reels_to_show:
            player = reel.get('player', 'Unknown')
            injury_type = reel.get('injury_type', 'General')
            team = reel.get('team', 'NFL General')
            url = reel.get('url', '')
            summary = reel.get('summary', '')
            summary_html = f"<div class='news-summary'>{summary}</div>" if summary else ""
            code = url.split('/reel/')[1].rstrip('/')
            embed_url = f"https://www.instagram.com/reel/{code}/embed"
            st.markdown(f"""
            <div class="injury-reel-container">
                <div class="injury-header">
                    <div class="injury-player-name">{player}</div>
                    <div class="player-info">
                        <span class="injury-badge">{injury_type.upper()}</span>
                        <span class="player-badge">{team.upper()}</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)
            components.iframe(embed_url, width=540, height=600)
            st.markdown(f"""
                {summary_html}
            </div>
            """, unsafe_allow_html=True)
# =============================================================================
# MAIN APP
# =============================================================================
apply_bloomberg_css()
render_terminal_header()
df = fetch_all_news()
render_stats_dashboard(df)
tab1, tab2, tab3 = st.tabs(["📰 NEWS FEED", "🎥 PLAYER FILM", "⚕️ INJURY ANALYSIS"])
with tab1:
    if df.empty:
        st.error("No news available.")
    else:
        st.markdown('<div class="control-label">SELECT TEAM</div>', unsafe_allow_html=True)
        selected_news_team = st.selectbox(
            'Team Filter',
            ['ALL TEAMS'] + sorted(df['team'].unique().tolist()),
            label_visibility="collapsed",
            key='news_team_filter'
        )
        filtered_df = df if selected_news_team == 'ALL TEAMS' else df[df['team'] == selected_news_team]
        for _, row in filtered_df.iterrows():
            render_news_item(row)
with tab2:
    render_player_film()
with tab3:
    render_injury_analysis()
