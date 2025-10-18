"""
NFL News Hub - Apple-Inspired Design
Premium NFL news aggregation with minimalist design
"""

import feedparser
import pandas as pd
import json
import hashlib
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple
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

# =============================================================================
# PAGE CONFIGURATION
# =============================================================================

st.set_page_config(
    page_title=APP.get('title', 'NFL News Hub'),
    page_icon=APP.get('page_icon', '🏈'),
    layout="wide",
    initial_sidebar_state="collapsed"
)

# =============================================================================
# FEED FETCHER
# =============================================================================

class FeedFetcher:
    """RSS feed fetching with parallel processing"""
    
    def __init__(self, days_lookback: int = 7, max_entries: int = 50):
        self.days_lookback = days_lookback
        self.max_entries = max_entries
        self.cutoff_date = datetime.now() - timedelta(days=days_lookback)
    
    def fetch_single_feed(self, url: str, source_name: str = "") -> List[Dict]:
        """Fetch a single RSS feed"""
        try:
            feed = feedparser.parse(url)
            articles = []
            
            for entry in feed.entries[:self.max_entries]:
                title = entry.get('title', '').strip()
                link = entry.get('link', '')
                
                if not title or not link:
                    continue
                
                pub_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
                pub_date = datetime(*pub_parsed[:6]) if pub_parsed else datetime.now()
                
                if pub_date >= self.cutoff_date:
                    summary = entry.get('summary', entry.get('description', ''))
                    
                    # Clean summary
                    if summary:
                        summary = summary.replace('<p>', '').replace('</p>', '')
                        summary = summary.replace('<br>', ' ').replace('<br/>', ' ')
                        summary = summary[:200] + '...' if len(summary) > 200 else summary
                    
                    articles.append({
                        'title': title,
                        'link': link,
                        'published': pub_date,
                        'source': source_name,
                        'summary': summary
                    })
            
            return articles
        except:
            return []
    
    def fetch_multiple_feeds(self, feeds: List[Tuple[str, str]], max_workers: int = 10) -> List[Dict]:
        """Fetch multiple feeds in parallel"""
        articles = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.fetch_single_feed, url, name): (url, name) for url, name in feeds}
            
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
        """Create MD5 hash"""
        return hashlib.md5(text.encode()).hexdigest()
    
    @staticmethod
    def deduplicate_dataframe(df: pd.DataFrame) -> pd.DataFrame:
        """Remove duplicates"""
        if df.empty:
            return df
        
        df['hash'] = df['title'].apply(DataProcessor.create_hash)
        df = df.drop_duplicates(subset=['hash']).drop(columns=['hash'])
        
        return df
    
    @staticmethod
    def extract_team_from_title(text: str, teams: List[str]) -> str:
        """Extract team name from text"""
        text_upper = text.upper()
        for team in teams:
            if team.upper() in text_upper:
                return team
        return 'NFL General'

# =============================================================================
# DATA FETCHING
# =============================================================================

@st.cache_data(ttl=APP.get('cache_ttl', 1800), show_spinner=False)
def fetch_all_news() -> pd.DataFrame:
    """Fetch all news from configured sources"""
    fetcher = FeedFetcher(days_lookback=APP.get('days_lookback', 7))
    news_items = []
    
    # Fetch general news
    general_feeds = [(f['url'], f['name']) for f in RSS_FEEDS.get('general_news', []) if f.get('enabled', True)]
    articles = fetcher.fetch_multiple_feeds(general_feeds, max_workers=APP.get('max_workers', 15))
    
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
    
    # Fetch team-specific feeds
    team_feeds_dict = RSS_FEEDS.get('team_feeds', {})
    for team, feeds in team_feeds_dict.items():
        team_feed_list = [(url, team) for url in feeds]
        articles = fetcher.fetch_multiple_feeds(team_feed_list, max_workers=APP.get('max_workers', 15))
        
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
# APPLE-STYLE UI
# =============================================================================

def apply_apple_css():
    """Apply Apple Store inspired CSS"""
    st.markdown("""
    <style>
        /* Global Styles */
        @import url('https://fonts.googleapis.com/css2?family=SF+Pro+Display:wght@300;400;500;600;700&display=swap');
        
        .main {
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', sans-serif;
        }
        
        .stApp {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        
        /* Header */
        .main-header {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border-radius: 20px;
            padding: 40px;
            margin-bottom: 40px;
            box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.15);
            text-align: center;
        }
        
        .main-title {
            font-size: 48px;
            font-weight: 700;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 10px;
            letter-spacing: -1px;
        }
        
        .main-subtitle {
            font-size: 18px;
            color: #86868b;
            font-weight: 400;
        }
        
        /* News Card */
        .news-card {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 16px;
            box-shadow: 0 4px 24px 0 rgba(31, 38, 135, 0.1);
            transition: all 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94);
            border: 1px solid rgba(255, 255, 255, 0.2);
        }
        
        .news-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 12px 48px 0 rgba(31, 38, 135, 0.2);
        }
        
        .news-headline {
            font-size: 20px;
            font-weight: 600;
            color: #1d1d1f;
            text-decoration: none;
            display: block;
            margin-bottom: 12px;
            line-height: 1.4;
            transition: color 0.2s ease;
        }
        
        .news-headline:hover {
            color: #667eea;
        }
        
        .news-meta {
            display: flex;
            align-items: center;
            gap: 12px;
            font-size: 13px;
            color: #86868b;
            margin-bottom: 12px;
            flex-wrap: wrap;
        }
        
        .news-summary {
            font-size: 15px;
            color: #6e6e73;
            line-height: 1.6;
            margin-top: 8px;
        }
        
        .team-badge {
            display: inline-block;
            padding: 4px 12px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 0.5px;
        }
        
        .source-badge {
            padding: 4px 10px;
            background: rgba(0, 0, 0, 0.05);
            border-radius: 8px;
            font-size: 12px;
            font-weight: 500;
        }
        
        .date-badge {
            font-size: 12px;
            color: #86868b;
        }
        
        /* Filter Bar */
        .filter-bar {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 32px;
            box-shadow: 0 4px 24px 0 rgba(31, 38, 135, 0.1);
        }
        
        /* Stats Bar */
        .stats-container {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }
        
        .stat-card {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            border-radius: 16px;
            padding: 24px;
            text-align: center;
            box-shadow: 0 4px 24px 0 rgba(31, 38, 135, 0.1);
        }
        
        .stat-number {
            font-size: 36px;
            font-weight: 700;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }
        
        .stat-label {
            font-size: 14px;
            color: #86868b;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        /* Streamlit Overrides */
        .stSelectbox > div > div {
            background: rgba(255, 255, 255, 0.9);
            border-radius: 12px;
            border: none;
        }
        
        .stButton > button {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 12px;
            padding: 12px 32px;
            font-weight: 600;
            transition: all 0.3s ease;
        }
        
        .stButton > button:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 24px 0 rgba(102, 126, 234, 0.4);
        }
        
        /* Hide Streamlit branding */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        header {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

def render_header():
    """Render Apple-style header"""
    st.markdown("""
    <div class="main-header">
        <div class="main-title">🏈 NFL News Hub</div>
        <div class="main-subtitle">Your premium source for NFL news across all teams</div>
    </div>
    """, unsafe_allow_html=True)

def render_filters() -> Tuple[str, str]:
    """Render filter controls"""
    col1, col2, col3 = st.columns([2, 2, 1])
    
    with col1:
        team_options = ['All Teams'] + sorted(TEAMS)
        selected_team = st.selectbox('📍 Filter by Team', team_options, label_visibility="collapsed", 
                                     key='team_filter', help="Filter news by specific team")
    
    with col2:
        time_options = {
            'Last 24 Hours': 1,
            'Last 3 Days': 3,
            'Last Week': 7
        }
        selected_time = st.selectbox('⏰ Time Range', list(time_options.keys()), 
                                     index=2, label_visibility="collapsed", key='time_filter')
    
    with col3:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    
    return selected_team, time_options[selected_time]

def render_stats(df: pd.DataFrame):
    """Render statistics cards"""
    if df.empty:
        return
    
    st.markdown("""
    <div class="stats-container">
        <div class="stat-card">
            <div class="stat-number">{}</div>
            <div class="stat-label">Total Articles</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{}</div>
            <div class="stat-label">Teams Covered</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{}</div>
            <div class="stat-label">News Sources</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{}</div>
            <div class="stat-label">Last Updated</div>
        </div>
    </div>
    """.format(
        len(df),
        df['team'].nunique(),
        df['source'].nunique(),
        datetime.now().strftime('%I:%M %p')
    ), unsafe_allow_html=True)

def render_news_card(row: pd.Series):
    """Render individual news card"""
    time_ago = get_time_ago(row['date'])
    
    summary_html = f"<div class='news-summary'>{row['summary']}</div>" if row['summary'] else ""
    
    st.markdown(f"""
    <div class="news-card">
        <a href="{row['link']}" target="_blank" class="news-headline">
            {row['headline']}
        </a>
        <div class="news-meta">
            <span class="team-badge">{row['team']}</span>
            <span class="source-badge">{row['source']}</span>
            <span class="date-badge">⏱️ {time_ago}</span>
        </div>
        {summary_html}
    </div>
    """, unsafe_allow_html=True)

def get_time_ago(date: datetime) -> str:
    """Get human-readable time ago string"""
    now = datetime.now()
    diff = now - date
    
    if diff.days > 0:
        return f"{diff.days}d ago"
    elif diff.seconds >= 3600:
        hours = diff.seconds // 3600
        return f"{hours}h ago"
    elif diff.seconds >= 60:
        minutes = diff.seconds // 60
        return f"{minutes}m ago"
    else:
        return "just now"

# =============================================================================
# MAIN APPLICATION
# =============================================================================

def main():
    """Main application"""
    apply_apple_css()
    render_header()
    
    # Filters
    selected_team, days_back = render_filters()
    
    # Load data
    with st.spinner('Loading latest NFL news...'):
        df = fetch_all_news()
    
    if df.empty:
        st.warning("No news available at this time. Please try again later.")
        return
    
    # Filter by team
    if selected_team != 'All Teams':
        df_filtered = df[df['team'] == selected_team].copy()
    else:
        df_filtered = df.copy()
    
    # Filter by date
    cutoff = datetime.now() - timedelta(days=days_back)
    df_filtered = df_filtered[df_filtered['date'] >= cutoff]
    
    # Render stats
    render_stats(df_filtered)
    
    # Render news cards
    if not df_filtered.empty:
        st.markdown(f"### 📰 {len(df_filtered)} Articles")
        
        for _, row in df_filtered.iterrows():
            render_news_card(row)
    else:
        st.info(f"No articles found for {selected_team} in the selected time range.")

if __name__ == "__main__":
    main()
