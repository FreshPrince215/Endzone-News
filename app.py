"""
NFL News Terminal 
Professional-grade NFL news aggregation with Player Highlights
"""

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
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

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
# PLAYER HIGHLIGHTS FETCHER
# =============================================================================

class PlayerHighlightsFetcher:
    """Fetch YouTube highlights for NFL players"""
    
    @staticmethod
    @st.cache_data(ttl=3600, show_spinner=False)
    def search_youtube_highlights(player_name: str) -> List[Dict[str, str]]:
        """Search for player highlights on YouTube"""
        query = f"{player_name} NFL highlights 2024 2025 site:youtube.com"
        url = f"https://www.google.com/search?q={query}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        
        videos = []
        try:
            response = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for link in soup.find_all('a'):
                href = link.get('href')
                if href and "youtube.com/watch" in href:
                    if href.startswith('/url?'):
                        parsed = parse_qs(urlparse(href).query)
                        href = parsed.get('q', [None])[0]
                    
                    if href:
                        parsed_url = urlparse(href)
                        vid_id = parse_qs(parsed_url.query).get('v')
                        
                        if vid_id:
                            # Try to extract title from link text
                            title = link.get_text().strip()
                            if not title or len(title) < 10:
                                title = f"{player_name} Highlights"
                            
                            videos.append({
                                'video_id': vid_id[0],
                                'title': title[:100],  # Truncate long titles
                                'url': f"https://www.youtube.com/watch?v={vid_id[0]}"
                            })
                            
                            # Limit to top 5 results
                            if len(videos) >= 5:
                                break
            
        except Exception as e:
            st.error(f"Error searching for videos: {e}")
        
        return videos

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
        
        /* Video Card Styles */
        .video-card {
            background: var(--bg-secondary);
            border-left: 3px solid var(--accent-blue);
            padding: 15px;
            margin-bottom: 15px;
            transition: all 0.2s ease;
        }
        
        .video-card:hover {
            background: var(--bg-tertiary);
            border-left-color: var(--accent-orange);
            transform: translateX(3px);
        }
        
        .video-title {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 14px;
            color: var(--text-primary);
            margin-bottom: 10px;
            font-weight: 600;
        }
        
        .player-search-box {
            background: var(--bg-tertiary);
            border: 2px solid var(--accent-orange);
            padding: 20px;
            margin-bottom: 25px;
            border-radius: 0;
        }
        
        .search-header {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 12px;
            color: var(--accent-orange);
            text-transform: uppercase;
            letter-spacing: 1.5px;
            font-weight: 700;
            margin-bottom: 15px;
        }
        
        .stTabs [data-baseweb="tab-list"] {
            gap: 8px;
            background-color: var(--bg-secondary);
            padding: 10px;
        }
        
        .stTabs [data-baseweb="tab"] {
            background-color: var(--bg-tertiary);
            color: var(--text-secondary);
            font-family: 'IBM Plex Mono', monospace;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 1px;
            border: 1px solid var(--border-color);
            border-radius: 0;
            padding: 12px 24px;
        }
        
        .stTabs [aria-selected="true"] {
            background-color: var(--accent-orange);
            color: #000;
            border-color: var(--accent-orange);
        }
        
        .stTextInput > div > div > input {
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 0;
            color: var(--text-primary);
            font-family: 'IBM Plex Mono', monospace;
            font-size: 14px;
        }
        
        .stTextInput label {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 10px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1px;
            font-weight: 600;
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
                <div class="terminal-subtitle">Real-Time News & Player Highlights</div>
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

# =============================================================================
# PLAYER TAB
# =============================================================================

def render_player_tab():
    """Render Player Highlights tab"""
    st.markdown('<div class="player-search-box">', unsafe_allow_html=True)
    st.markdown('<div class="search-header">🎬 PLAYER HIGHLIGHTS SEARCH</div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        player_name = st.text_input(
            "ENTER PLAYER NAME",
            placeholder="e.g., Patrick Mahomes, CeeDee Lamb, Christian McCaffrey",
            key="player_search"
        )
    
    with col2:
        search_button = st.button("🔍 SEARCH", use_container_width=True, type="primary")
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Popular players quick access
    st.markdown('<div class="section-header">⚡ QUICK ACCESS — POPULAR PLAYERS</div>', unsafe_allow_html=True)
    
    popular_players = [
        "Patrick Mahomes", "Josh Allen", "Lamar Jackson", "Jalen Hurts",
        "Christian McCaffrey", "Tyreek Hill", "Travis Kelce", "Justin Jefferson",
        "CeeDee Lamb", "Saquon Barkley", "Derrick Henry", "Brock Purdy"
    ]
    
    cols = st.columns(4)
    for idx, player in enumerate(popular_players):
        with cols[idx % 4]:
            if st.button(player, key=f"quick_{idx}", use_container_width=True):
                st.session_state.player_search = player
                st.rerun()
    
    # Search and display videos
    if search_button or (player_name and len(player_name) > 2):
        search_name = player_name or st.session_state.get('player_search', '')
        
        if search_name:
            with st.spinner(f'🔍 Searching for {search_name} highlights...'):
                videos = PlayerHighlightsFetcher.search_youtube_highlights(search_name)
            
            if videos:
                st.markdown(f'<div class="section-header">📺 HIGHLIGHTS — {search_name.upper()} ({len(videos)} VIDEOS)</div>', unsafe_allow_html=True)
                
                for video in videos:
                    st.markdown(f"""
                    <div class="video-card">
                        <div class="video-title">▶️ {video['title']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Embed YouTube video
                    st.video(video['url'])
                    
                    st.markdown("<br>", unsafe_allow_html=True)
            else:
                st.warning(f"⚠️ NO VIDEOS FOUND | {search_name}")
                st.info("💡 Try adjusting the player name or check spelling. Make sure to use the full name.")

# =============================================================================
# NEWS TAB
# =============================================================================

def render_news_tab():
    """Render News Feed tab"""
    col1, col2, col3 = st.columns([3, 2, 1])
    
    with col1:
        st.markdown('<div class="control-label">SELECT TEAM</div>', unsafe_allow_html=True)
        team_options = ['ALL TEAMS'] + sorted(TEAMS)
        selected_team = st.selectbox(
            'Team Filter',
            team_options,
            label_visibility="collapsed",
            key='team_filter'
        )
    
    with col2:
        st.markdown('<div class="control-label">TIME RANGE</div>', unsafe_allow_html=True)
        time_options = {
            'LAST 24 HOURS': 1,
            'LAST 3 DAYS': 3,
            'LAST 7 DAYS': 7
        }
        selected_time = st.selectbox(
            'Time Range',
            list(time_options.keys()),
            index=2,
            label_visibility="collapsed",
            key='time_filter'
        )
    
    with col3:
        st.markdown('<div class="control-label">ACTIONS</div>', unsafe_allow_html=True)
        if st.button("⟳ REFRESH", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    
    # Load data
    with st.spinner('▮ LOADING FEED DATA...'):
        df = fetch_all_news()
    
    if df.empty:
        st.warning("⚠ NO DATA AVAILABLE | CHECK FEED SOURCES")
        st.info("Verify that RSS feeds in config.json are accessible and enabled.")
        return
    
    # Filter by team
    if selected_team != 'ALL TEAMS':
        df_filtered = df[df['team'] == selected_team].copy()
    else:
        df_filtered = df.copy()
    
    # Filter by date
    cutoff = datetime.now() - timedelta(days=time_options[selected_time])
    df_filtered = df_filtered[df_filtered['date'] >= cutoff]
    
    # Render stats
    render_stats_dashboard(df_filtered)
    
    # Render news feed
    if not df_filtered.empty:
        st.markdown(f'<div class="section-header">NEWS FEED — {len(df_filtered)} ITEMS</div>', unsafe_allow_html=True)
        
        for _, row in df_filtered.iterrows():
            render_news_item(row)
    else:
        st.info(f"⚠ NO ARTICLES FOUND | {selected_team} | {selected_time}")
        st.caption("Try adjusting the time range or selecting a different team.")

# =============================================================================
# MAIN APPLICATION
# =============================================================================

def main():
    """Main application"""
    apply_bloomberg_css()
    render_terminal_header()
    
    # Create tabs
    tab1, tab2 = st.tabs(["📰 NEWS FEED", "🎬 PLAYER TAP"])
    
    with tab1:
        render_news_tab()
    
    with tab2:
        render_player_tab()

if __name__ == "__main__":
    main()
