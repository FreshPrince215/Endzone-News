import feedparser
import pandas as pd
import json
import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit as st

# =============================================================================
# CONFIGURATION MANAGEMENT
# =============================================================================

@st.cache_resource
def load_application_config() -> Dict:
    """Load application configuration from config.json file"""
    config_path = Path(__file__).parent / 'config.json'
    
    if not config_path.exists():
        st.error("⚠️ Configuration file not found. Please ensure config.json exists.")
        st.stop()
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"❌ Error loading configuration: {e}")
        st.stop()

CONFIG = load_application_config()
APP_SETTINGS = CONFIG.get('app', {})
NFL_TEAMS = CONFIG.get('teams', [])
RSS_FEED_SOURCES = CONFIG.get('rss_feeds', {})

# =============================================================================
# PAGE CONFIGURATION
# =============================================================================

st.set_page_config(
    page_title=APP_SETTINGS.get('title', 'NFL News Aggregator'),
    page_icon=APP_SETTINGS.get('page_icon', '🏈'),
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Initialize theme in session state
if 'theme_mode' not in st.session_state:
    st.session_state.theme_mode = 'dark'

# =============================================================================
# RSS FEED FETCHER
# =============================================================================

class RSSFeedFetcher:
    """Handles RSS feed fetching with robust error handling and parallel processing"""
    
    def __init__(self, days_lookback: int = 7, max_entries: int = 100):
        self.days_lookback = days_lookback
        self.max_entries = max_entries
        self.cutoff_date = datetime.now() - timedelta(days=days_lookback)
        self.successful_fetches = 0
        self.failed_fetches = 0
    
    def sanitize_html_content(self, text: str) -> str:
        """Remove HTML tags and clean text content"""
        if not text:
            return ""
        text = re.sub(r'<[^>]+>', '', text)
        text = ' '.join(text.split())
        if len(text) > 300:
            text = text[:300] + '...'
        return text
    
   def fetch_feed(self, url: str, source_name: str = "") -> List[Dict]:
        """Fetch a single RSS feed with comprehensive error handling"""
        try:
            feed = feedparser.parse(url, request_headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            })
            
            if not feed.entries:
                self.failed_fetches += 1
                return []
            
            articles = []
            for entry in feed.entries[:self.max_entries]:
                title = entry.get('title', '').strip()
                link = entry.get('link', '')
                
                if not title or not link:
                    continue
                
                # IMPROVED DATE PARSING
                pub_date = None
                
                # Try published_parsed first, then updated_parsed
                pub_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
                
                if pub_parsed:
                    try:
                        # Convert struct_time to datetime properly
                        import time
                        pub_date = datetime.fromtimestamp(time.mktime(pub_parsed))
                    except (ValueError, OverflowError, OSError):
                        pass
                
                # If parsing failed or no date found, try string parsing
                if pub_date is None:
                    for date_field in ['published', 'updated']:
                        date_str = entry.get(date_field, '')
                        if date_str:
                            try:
                                from email.utils import parsedate_to_datetime
                                pub_date = parsedate_to_datetime(date_str)
                                break
                            except:
                                pass
                
                # Fall back to current time if all parsing failed
                if pub_date is None:
                    pub_date = datetime.now()
                
                # Ensure pub_date is timezone-naive for comparison
                if pub_date.tzinfo is not None:
                    pub_date = pub_date.replace(tzinfo=None)
                
                if pub_date >= self.cutoff_date:
                    summary = entry.get('summary', entry.get('description', ''))
                    summary = self.sanitize_html_content(summary)
                    
                    articles.append({
                        'title': title,
                        'link': link,
                        'published': pub_date,
                        'source': source_name,
                        'summary': summary
                    })
            
            self.successful_fetches += 1
            return articles
            
        except Exception as e:
            self.failed_fetches += 1
            return []
    
    def fetch_multiple_feeds(self, feeds: List[Tuple[str, str]], max_workers: int = 10) -> List[Dict]:
        """Fetch multiple RSS feeds in parallel for improved performance"""
        articles = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.fetch_feed, url, name): (url, name)
                      for url, name in feeds}
            
            for future in as_completed(futures):
                try:
                    articles.extend(future.result())
                except:
                    pass
        
        return articles

# =============================================================================
# DATA PROCESSING UTILITIES
# =============================================================================

class NewsDataProcessor:
    """Utilities for processing and cleaning news data"""
    
    @staticmethod
    def generate_content_hash(text: str) -> str:
        """Generate MD5 hash for content deduplication"""
        return hashlib.md5(text.encode()).hexdigest()
    
    @staticmethod
    def remove_duplicate_articles(df: pd.DataFrame) -> pd.DataFrame:
        """Remove duplicate articles based on headline content"""
        if df.empty:
            return df
        
        df['content_hash'] = df['headline'].apply(NewsDataProcessor.generate_content_hash)
        df = df.drop_duplicates(subset=['content_hash']).drop(columns=['content_hash'])
        
        return df
    
    @staticmethod
    def identify_team_from_content(text: str, teams: List[str]) -> str:
        """Extract NFL team name from article content using keyword matching"""
        text_upper = text.upper()
        
        team_keyword_mapping = {
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
        
        for keyword, team in team_keyword_mapping.items():
            if keyword in text_upper:
                return team
        
        for team in teams:
            if team.upper() in text_upper:
                return team
        
        return 'NFL General'

# =============================================================================
# DATA FETCHING AND CACHING
# =============================================================================

@st.cache_data(ttl=APP_SETTINGS.get('cache_ttl', 1800), show_spinner=False)
def fetch_all_news_articles() -> pd.DataFrame:
    """Fetch and process all news articles from configured RSS feeds"""
    fetcher = RSSFeedFetcher(days_lookback=APP_SETTINGS.get('days_lookback', 7))
    news_items = []
    
    # Fetch from general NFL news sources
    general_feeds = [
        (feed['url'], feed['name'])
        for feed in RSS_FEED_SOURCES.get('general_news', [])
        if feed.get('enabled', True)
    ]
    
    if general_feeds:
        articles = fetcher.fetch_multiple_feeds(general_feeds, max_workers=APP_SETTINGS.get('max_workers', 10))
        
        for article in articles:
            team = NewsDataProcessor.identify_team_from_content(article['title'], NFL_TEAMS)
            news_items.append({
                'team': team,
                'headline': article['title'],
                'link': article['link'],
                'date': article['published'],
                'source': article['source'],
                'summary': article['summary']
            })
    
    # Fetch from team-specific feeds
    team_feeds_dict = RSS_FEED_SOURCES.get('team_feeds', {})
    for team, feeds in team_feeds_dict.items():
        if isinstance(feeds, list):
            team_feed_list = [(url, team) for url in feeds if url]
            articles = fetcher.fetch_multiple_feeds(team_feed_list, max_workers=APP_SETTINGS.get('max_workers', 10))
            
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
    df = NewsDataProcessor.remove_duplicate_articles(df)
    df = df.sort_values('date', ascending=False)
    
    return df

# =============================================================================
# THEME MANAGEMENT
# =============================================================================

def get_theme_styles() -> str:
    """Generate CSS styles based on current theme mode"""
    
    if st.session_state.theme_mode == 'dark':
        return """
        :root {
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-tertiary: #334155;
            --accent-primary: #3b82f6;
            --accent-secondary: #06b6d4;
            --accent-success: #10b981;
            --accent-warning: #f59e0b;
            --text-primary: #f1f5f9;
            --text-secondary: #94a3b8;
            --border-color: #475569;
            --hover-bg: #2d3748;
        }
        """
    else:
        return """
        :root {
            --bg-primary: #ffffff;
            --bg-secondary: #f8fafc;
            --bg-tertiary: #e2e8f0;
            --accent-primary: #2563eb;
            --accent-secondary: #0891b2;
            --accent-success: #059669;
            --accent-warning: #d97706;
            --text-primary: #1e293b;
            --text-secondary: #64748b;
            --border-color: #cbd5e1;
            --hover-bg: #f1f5f9;
        }
        """

def apply_application_styles():
    """Apply comprehensive CSS styling to the application"""
    theme_vars = get_theme_styles()
    
    st.markdown(f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
        
        {theme_vars}
        
        * {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        }}
        
        .stApp {{
            background-color: var(--bg-primary);
            transition: background-color 0.3s ease;
        }}
        
        .main {{
            background-color: var(--bg-primary);
        }}
        
        .app-header {{
            background: linear-gradient(135deg, var(--bg-secondary) 0%, var(--bg-tertiary) 100%);
            border-bottom: 3px solid var(--accent-primary);
            padding: 2rem;
            margin: -2rem -2rem 2rem -2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }}
        
        .header-content {{
            display: flex;
            align-items: center;
            gap: 1.5rem;
        }}
        
        .app-title {{
            font-size: 2rem;
            font-weight: 800;
            color: var(--accent-primary);
            letter-spacing: -0.5px;
        }}
        
        .app-subtitle {{
            font-size: 0.875rem;
            color: var(--text-secondary);
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .theme-toggle {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        
        .status-indicator {{
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 0.875rem;
            color: var(--accent-success);
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .status-dot {{
            width: 10px;
            height: 10px;
            background: var(--accent-success);
            border-radius: 50%;
            animation: pulse 2s infinite;
        }}
        
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.5; transform: scale(1.1); }}
        }}
        
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }}
        
        .metric-card {{
            background: var(--bg-secondary);
            border-left: 4px solid var(--accent-primary);
            padding: 1.5rem;
            border-radius: 8px;
            transition: all 0.3s ease;
        }}
        
        .metric-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 16px -4px rgba(0, 0, 0, 0.15);
        }}
        
        .metric-value {{
            font-size: 2.5rem;
            font-weight: 800;
            color: var(--accent-primary);
            line-height: 1;
            margin-bottom: 0.5rem;
        }}
        
        .metric-label {{
            font-size: 0.875rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1px;
            font-weight: 600;
        }}
        
        .news-article {{
            background: var(--bg-secondary);
            border-left: 4px solid var(--accent-secondary);
            padding: 1.5rem;
            margin-bottom: 1rem;
            border-radius: 8px;
            transition: all 0.3s ease;
        }}
        
        .news-article:hover {{
            background: var(--hover-bg);
            border-left-color: var(--accent-primary);
            transform: translateX(4px);
            box-shadow: 0 4px 12px -2px rgba(0, 0, 0, 0.1);
        }}
        
        .article-header {{
            display: flex;
            align-items: center;
            gap: 1rem;
            margin-bottom: 1rem;
            flex-wrap: wrap;
        }}
        
        .article-timestamp {{
            font-size: 0.875rem;
            color: var(--accent-success);
            font-weight: 600;
            min-width: 100px;
        }}
        
        .article-team-badge {{
            font-size: 0.75rem;
            background: var(--accent-primary);
            color: white;
            padding: 0.25rem 0.75rem;
            border-radius: 4px;
            font-weight: 700;
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }}
        
        .article-source {{
            font-size: 0.75rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 600;
        }}
        
        .article-headline {{
            font-size: 1.125rem;
            font-weight: 600;
            color: var(--text-primary);
            text-decoration: none;
            display: block;
            line-height: 1.6;
            margin-bottom: 0.75rem;
            transition: color 0.2s ease;
        }}
        
        .article-headline:hover {{
            color: var(--accent-primary);
        }}
        
        .article-summary {{
            font-size: 0.9375rem;
            color: var(--text-secondary);
            line-height: 1.7;
            margin-top: 0.75rem;
        }}
        
        .filter-label {{
            font-size: 0.875rem;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 0.5rem;
            font-weight: 600;
        }}
        
        .stSelectbox > div > div {{
            background: var(--bg-tertiary);
            border: 2px solid var(--border-color);
            border-radius: 8px;
            color: var(--text-primary);
            font-weight: 500;
        }}
        
        .stButton > button {{
            background: var(--bg-tertiary);
            border: 2px solid var(--accent-primary);
            color: var(--accent-primary);
            border-radius: 8px;
            padding: 0.75rem 1.5rem;
            font-weight: 600;
            font-size: 0.875rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            transition: all 0.3s ease;
        }}
        
        .stButton > button:hover {{
            background: var(--accent-primary);
            color: white;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px -2px rgba(59, 130, 246, 0.5);
        }}
        
        .section-title {{
            font-size: 1.25rem;
            color: var(--accent-primary);
            text-transform: uppercase;
            letter-spacing: 1.5px;
            font-weight: 700;
            margin-bottom: 1.5rem;
            padding-bottom: 0.75rem;
            border-bottom: 2px solid var(--border-color);
        }}
        
        ::-webkit-scrollbar {{
            width: 12px;
        }}
        
        ::-webkit-scrollbar-track {{
            background: var(--bg-primary);
        }}
        
        ::-webkit-scrollbar-thumb {{
            background: var(--accent-primary);
            border-radius: 6px;
        }}
        
        ::-webkit-scrollbar-thumb:hover {{
            background: var(--accent-secondary);
        }}
        
        #MainMenu {{visibility: hidden;}}
        footer {{visibility: hidden;}}
        header {{visibility: hidden;}}
        .stDeployButton {{display: none;}}
    </style>
    """, unsafe_allow_html=True)

# =============================================================================
# UI COMPONENTS
# =============================================================================

def render_application_header():
    """Render the application header with theme toggle"""
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.markdown(f"""
        <div class="app-header">
            <div class="header-content">
                <div>
                    <div class="app-title">🏈 NFL News Aggregator</div>
                    <div class="app-subtitle">Real-Time News from Multiple Sources</div>
                </div>
            </div>
            <div>
                <div class="status-indicator">
                    <div class="status-dot"></div>
                    LIVE
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        if st.button("🌓 Toggle Theme", use_container_width=True):
            st.session_state.theme_mode = 'light' if st.session_state.theme_mode == 'dark' else 'dark'
            st.rerun()

def render_metrics_dashboard(df: pd.DataFrame):
    """Render key metrics dashboard"""
    if df.empty:
        return
    
    total_articles = len(df)
    
    st.markdown(f"""
    <div class="metrics-grid">
        <div class="metric-card">
            <div class="metric-value">{total_articles}</div>
            <div class="metric-label">Total Articles</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

def render_news_article(row: pd.Series):
    """Render individual news article card"""
    date_str = row['date'].strftime('%b %d, %Y')
    
    summary_html = f"<div class='article-summary'>{row['summary']}</div>" if row['summary'] else ""
    
    st.markdown(f"""
    <div class="news-article">
        <div class="article-header">
            <span class="article-timestamp">{date_str}</span>
            <span class="article-team-badge">{row['team']}</span>
            <span class="article-source">{row['source']}</span>
        </div>
        <a href="{row['link']}" target="_blank" class="article-headline">
            {row['headline']}
        </a>
        {summary_html}
    </div>
    """, unsafe_allow_html=True)

# =============================================================================
# MAIN APPLICATION
# =============================================================================

def main():
    """Main application logic"""
    apply_application_styles()
    render_application_header()
    
    # Fetch news data with loading indicator
    with st.spinner('📡 Fetching latest NFL news...'):
        df = fetch_all_news_articles()
    
    # Display metrics
    render_metrics_dashboard(df)
    
    if df.empty:
        st.error("⚠️ No news articles available. Please check your RSS feed configuration.")
        return
    
    # Filters
    st.markdown('<div class="section-title">📰 News Feed</div>', unsafe_allow_html=True)
    
    col1, col2 = st.columns([2, 2])
    
    with col1:
        st.markdown('<div class="filter-label">Filter by Team</div>', unsafe_allow_html=True)
        selected_team = st.selectbox(
            'Team',
            ['All Teams'] + sorted(df['team'].unique().tolist()),
            label_visibility="collapsed",
            key='team_filter'
        )
    
    with col2:
        st.markdown('<div class="filter-label">Sort By</div>', unsafe_allow_html=True)
        sort_order = st.selectbox(
            'Sort',
            ['Newest First', 'Oldest First'],
            label_visibility="collapsed",
            key='sort_filter'
        )
    
    # Apply filters
    filtered_df = df.copy()
    
    if selected_team != 'All Teams':
        filtered_df = filtered_df[filtered_df['team'] == selected_team]
    
    # Apply sorting
    if sort_order == 'Oldest First':
        filtered_df = filtered_df.sort_values('date', ascending=True)
    
    # Display article count
    st.markdown(f"<div style='margin: 1.5rem 0 1rem 0; color: var(--text-secondary); font-size: 0.875rem;'>Showing <strong>{len(filtered_df)}</strong> articles</div>", unsafe_allow_html=True)
    
    # Render articles
    if filtered_df.empty:
        st.info("No articles match your filter criteria.")
    else:
        for _, row in filtered_df.iterrows():
            render_news_article(row)

if __name__ == "__main__":
    main()
