import feedparser
import pandas as pd
import re
from datetime import datetime, timedelta
import streamlit as st
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib

# Page config
st.set_page_config(page_title="NFL Terminal", layout="wide", page_icon="🏈")

# =============================================================================
# NFL TEAMS & FEEDS
# =============================================================================

NFL_TEAMS = [
    'Arizona Cardinals', 'Atlanta Falcons', 'Baltimore Ravens', 'Buffalo Bills',
    'Carolina Panthers', 'Chicago Bears', 'Cincinnati Bengals', 'Cleveland Browns',
    'Dallas Cowboys', 'Denver Broncos', 'Detroit Lions', 'Green Bay Packers',
    'Houston Texans', 'Indianapolis Colts', 'Jacksonville Jaguars', 'Kansas City Chiefs',
    'Las Vegas Raiders', 'Los Angeles Chargers', 'Los Angeles Rams', 'Miami Dolphins',
    'Minnesota Vikings', 'New England Patriots', 'New Orleans Saints', 'New York Giants',
    'New York Jets', 'Philadelphia Eagles', 'Pittsburgh Steelers', 'San Francisco 49ers',
    'Seattle Seahawks', 'Tampa Bay Buccaneers', 'Tennessee Titans', 'Washington Commanders'
]

GENERAL_RSS_FEEDS = [
    "https://www.nfl.com/feeds/rss/home",
    "https://www.espn.com/espn/rss/nfl/news",
    "https://www.cbssports.com/rss/headlines/nfl/"
]

INJURY_RSS_FEEDS = {
    'DraftSharks': 'https://www.draftsharks.com/rss/injury-news',
    'ESPN': 'https://www.espn.com/espn/rss/nfl/news',
    'RotoWire': 'https://www.rotowire.com/rss/news.php?sport=NFL',
    'ClutchPoints': 'https://clutchpoints.com/nfl/feed',
    'CBS Sports': 'https://www.cbssports.com/rss/headlines/nfl'
}

TEAM_FEEDS = {
    'Arizona Cardinals': ['https://www.azcardinals.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=ARI'],
    'Atlanta Falcons': ['https://www.atlantafalcons.com/rss/article', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=ATL'],
    'Baltimore Ravens': ['https://www.baltimoreravens.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=BAL'],
    'Buffalo Bills': ['https://www.buffalobills.com/rss/article', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=BUF'],
    'Carolina Panthers': ['https://www.panthers.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=CAR'],
    'Chicago Bears': ['https://www.chicagobears.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=CHI'],
    'Cincinnati Bengals': ['https://www.bengals.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=CIN'],
    'Cleveland Browns': ['https://www.clevelandbrowns.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=CLE'],
    'Dallas Cowboys': ['https://www.dallascowboys.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=DAL'],
    'Denver Broncos': ['https://www.denverbroncos.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=DEN'],
    'Detroit Lions': ['https://www.detroitlions.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=DET'],
    'Green Bay Packers': ['https://www.packers.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=GB'],
    'Houston Texans': ['https://www.houstontexans.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=HOU'],
    'Indianapolis Colts': ['https://www.colts.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=IND'],
    'Jacksonville Jaguars': ['https://www.jaguars.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=JAX'],
    'Kansas City Chiefs': ['https://www.chiefs.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=KC'],
    'Las Vegas Raiders': ['https://www.raiders.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=LV'],
    'Los Angeles Chargers': ['https://www.chargers.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=LAC'],
    'Los Angeles Rams': ['https://www.therams.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=LAR'],
    'Miami Dolphins': ['https://www.miamidolphins.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=MIA'],
    'Minnesota Vikings': ['https://www.vikings.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=MIN'],
    'New England Patriots': ['https://www.patriots.com/rss/article', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=NE'],
    'New Orleans Saints': ['https://www.neworleanssaints.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=NO'],
    'New York Giants': ['https://www.giants.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=NYG'],
    'New York Jets': ['https://www.newyorkjets.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=NYJ'],
    'Philadelphia Eagles': ['https://www.philadelphiaeagles.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=PHI'],
    'Pittsburgh Steelers': ['https://www.steelers.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=PIT'],
    'San Francisco 49ers': ['https://www.49ers.com/rss/article', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=SF'],
    'Seattle Seahawks': ['https://www.seahawks.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=SEA'],
    'Tampa Bay Buccaneers': ['https://www.buccaneers.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=TB'],
    'Tennessee Titans': ['https://www.tennesseetitans.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=TEN'],
    'Washington Commanders': ['https://www.commanders.com/rss/news', 'https://www.rotowire.com/rss/news.htm?type=news&sport=nfl&team=WAS']
}

# =============================================================================
# INJURY DATABASE
# =============================================================================

INJURY_DATABASE = {
    'concussion': {
        'name': 'CONCUSSION',
        'desc': 'Traumatic brain injury. Requires NFL protocol clearance before return.',
        'recovery': '1-4 weeks + protocol',
        'severity': 'SERIOUS',
        'code': 'CONC'
    },
    'acl': {
        'name': 'ACL TEAR',
        'desc': 'Anterior cruciate ligament tear. Usually requires surgery.',
        'recovery': '6-12 months',
        'severity': 'CRITICAL',
        'code': 'ACL'
    },
    'mcl': {
        'name': 'MCL SPRAIN',
        'desc': 'Medial collateral ligament injury. Grade dependent severity.',
        'recovery': '1-8 weeks',
        'severity': 'MODERATE',
        'code': 'MCL'
    },
    'hamstring': {
        'name': 'HAMSTRING',
        'desc': 'Muscle strain/tear in back of thigh. Common in explosive movements.',
        'recovery': '2-8 weeks',
        'severity': 'MODERATE',
        'code': 'HAMS'
    },
    'ankle': {
        'name': 'ANKLE SPRAIN',
        'desc': 'Ligament damage. High ankle sprains take longer to heal.',
        'recovery': '1-6 weeks',
        'severity': 'MODERATE',
        'code': 'ANK'
    },
    'shoulder': {
        'name': 'SHOULDER',
        'desc': 'Sprains, separations, dislocations, or rotator cuff damage.',
        'recovery': '2-12 weeks',
        'severity': 'MODERATE',
        'code': 'SHLDR'
    },
    'groin': {
        'name': 'GROIN STRAIN',
        'desc': 'Inner thigh muscle strain. Common in lateral movements.',
        'recovery': '2-6 weeks',
        'severity': 'MODERATE',
        'code': 'GROIN'
    },
    'knee': {
        'name': 'KNEE INJURY',
        'desc': 'Various knee injuries. Requires specific diagnosis.',
        'recovery': '1-8 weeks',
        'severity': 'MODERATE',
        'code': 'KNEE'
    },
    'foot': {
        'name': 'FOOT INJURY',
        'desc': 'Includes plantar fasciitis, turf toe, fractures.',
        'recovery': '2-8 weeks',
        'severity': 'MODERATE',
        'code': 'FOOT'
    },
    'back': {
        'name': 'BACK INJURY',
        'desc': 'Muscle strains, herniated discs, or spinal issues.',
        'recovery': '1-8+ weeks',
        'severity': 'MODERATE',
        'code': 'BACK'
    },
    'ribs': {
        'name': 'RIB INJURY',
        'desc': 'Bruised or fractured ribs. Painful but often playable.',
        'recovery': '2-6 weeks',
        'severity': 'MODERATE',
        'code': 'RIBS'
    },
    'quadriceps': {
        'name': 'QUAD STRAIN',
        'desc': 'Front thigh muscle strain. Ranges from minor to severe.',
        'recovery': '2-8 weeks',
        'severity': 'MODERATE',
        'code': 'QUAD'
    },
    'calf': {
        'name': 'CALF STRAIN',
        'desc': 'Lower leg muscle strain. Impacts running ability.',
        'recovery': '2-6 weeks',
        'severity': 'MODERATE',
        'code': 'CALF'
    },
    'hip': {
        'name': 'HIP INJURY',
        'desc': 'Strains, labral tears, or joint issues. Affects mobility.',
        'recovery': '2-12 weeks',
        'severity': 'MODERATE',
        'code': 'HIP'
    },
    'neck': {
        'name': 'NECK INJURY',
        'desc': 'Cervical spine issues. Treated with extreme caution.',
        'recovery': '2-8+ weeks',
        'severity': 'SERIOUS',
        'code': 'NECK'
    },
    'wrist': {
        'name': 'WRIST',
        'desc': 'Bone or ligament injury. Can be braced for some positions.',
        'recovery': '2-8 weeks',
        'severity': 'MILD',
        'code': 'WRST'
    },
    'elbow': {
        'name': 'ELBOW',
        'desc': 'Sprains, hyperextensions. Common for QBs and linemen.',
        'recovery': '2-6 weeks',
        'severity': 'MODERATE',
        'code': 'ELBW'
    },
    'finger': {
        'name': 'FINGER',
        'desc': 'Sprains, dislocations, fractures. Common for receivers.',
        'recovery': '1-4 weeks',
        'severity': 'MILD',
        'code': 'FNGR'
    }
}

INJURY_KEYWORDS = list(INJURY_DATABASE.keys()) + [
    'injury', 'injured', 'out', 'questionable', 'doubtful', 'IR', 
    'inactive', 'limited', 'DNP', 'ruled out'
]

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
        seven_days_ago = datetime.now() - timedelta(days=7)
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
            
            if pub_date >= seven_days_ago:
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

@st.cache_data(ttl=1800)
def fetch_all_news():
    """Fetch all news feeds in parallel"""
    news_items = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
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
    
    with ThreadPoolExecutor(max_workers=10) as executor:
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

@st.cache_data(ttl=1800)
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
                        'description': injury_info.get('desc', 'Injury details not available'),
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

st.markdown("""
<style>
    .main {
        background-color: #000000;
    }
    .news-item {
        border-left: 3px solid #00FF00;
        padding: 10px;
        margin-bottom: 15px;
        background-color: #1A1A1A;
        font-family: 'Courier New', monospace;
    }
    .injury-item {
        border-left: 3px solid #FF0000;
        padding: 10px;
        margin-bottom: 15px;
        background-color: #1A1A1A;
        font-family: 'Courier New', monospace;
    }
    .news-headline {
        color: #00FF00;
        font-size: 14px;
        font-weight: bold;
        text-decoration: none;
    }
    .injury-headline {
        color: #FF6666;
        font-size: 14px;
        font-weight: bold;
        text-decoration: none;
    }
    .news-meta {
        color: #888888;
        font-size: 11px;
        margin-top: 5px;
    }
    .injury-meta {
        color: #888888;
        font-size: 11px;
        margin-top: 5px;
    }
    .injury-details {
        background-color: #0D0D0D;
        padding: 8px;
        margin-top: 8px;
        border-left: 2px solid #FF0000;
        font-size: 11px;
        color: #CCCCCC;
    }
    .severity-critical {
        color: #FF0000;
        font-weight: bold;
    }
    .severity-serious {
        color: #FF6600;
        font-weight: bold;
    }
    .severity-moderate {
        color: #FFAA00;
        font-weight: bold;
    }
    .severity-mild {
        color: #FFFF00;
        font-weight: bold;
    }
    .ticker {
        color: #00FF00;
        font-family: 'Courier New', monospace;
        font-size: 12px;
    }
    .stRadio > label {
        color: #00FF00;
    }
    .stSelectbox > label {
        color: #00FF00;
    }
</style>
""", unsafe_allow_html=True)

# =============================================================================
# MAIN APP
# =============================================================================

# Header
st.markdown("## 🏈 NFL TERMINAL")
st.markdown(f"<p class='ticker'>SYSTEM TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>", unsafe_allow_html=True)

# Sidebar Navigation
st.sidebar.markdown("### TERMINAL MODE")
mode = st.sidebar.radio("SELECT MODE", ["NEWS", "INJURIES"])

st.sidebar.markdown("---")
st.sidebar.markdown("### FILTERS")

# Common filters
team_options = ['ALL TEAMS'] + sorted(NFL_TEAMS) + ['GENERAL']
selected_team = st.sidebar.selectbox('TEAM', team_options)

date_filter = st.sidebar.radio("TIME RANGE", ["24H", "3D", "7D"], index=2)

# =============================================================================
# NEWS MODE
# =============================================================================

if mode == "NEWS":
    with st.spinner('LOADING NEWS FEED...'):
        df_all = fetch_all_news()
    
    if not df_all.empty:
        # Filter by team
        if selected_team == 'ALL TEAMS':
            filtered = df_all.copy()
        elif selected_team == 'GENERAL':
            filtered = df_all[df_all['team'] == 'General'].copy()
        else:
            filtered = df_all[df_all['team'] == selected_team].copy()
        
        # Filter by date
        now = datetime.now()
        if date_filter == "24H":
            cutoff = now - timedelta(days=1)
        elif date_filter == "3D":
            cutoff = now - timedelta(days=3)
        else:
            cutoff = now - timedelta(days=7)
        
        filtered = filtered[filtered['published'] >= cutoff]
        
        # Stats
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"<p class='ticker'>ARTICLES: {len(filtered)}</p>", unsafe_allow_html=True)
        with col2:
            st.markdown(f"<p class='ticker'>TEAMS: {filtered['team'].nunique()}</p>", unsafe_allow_html=True)
        with col3:
            st.markdown(f"<p class='ticker'>FILTER: {selected_team}</p>", unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Display news
        if not filtered.empty:
            for idx, row in filtered.iterrows():
                timestamp = row['published'].strftime('%m/%d %H:%M')
                st.markdown(f"""
                <div class='news-item'>
                    <a href='{row['link']}' target='_blank' class='news-headline'>{row['headline']}</a>
                    <div class='news-meta'>{timestamp} | {row['team']}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown(f"<p class='ticker'>NO NEWS DATA FOR {selected_team} IN {date_filter}</p>", unsafe_allow_html=True)
    else:
        st.error("NEWS FEED ERROR - RETRY")

# =============================================================================
# INJURY MODE
# =============================================================================

else:
    # Additional injury filters
    injury_type_options = ['ALL INJURIES'] + sorted(list(set([v['name'] for v in INJURY_DATABASE.values()])))
    selected_injury_type = st.sidebar.selectbox('INJURY TYPE', injury_type_options)
    
    severity_options = ['ALL', 'CRITICAL', 'SERIOUS', 'MODERATE', 'MILD']
    selected_severity = st.sidebar.selectbox('SEVERITY', severity_options)
    
    with st.spinner('LOADING INJURY FEED...'):
        df_injuries = fetch_all_injuries()
    
    if not df_injuries.empty:
        # Filter by team
        if selected_team == 'ALL TEAMS':
            filtered = df_injuries.copy()
        elif selected_team == 'GENERAL':
            filtered = df_injuries[df_injuries['team'] == 'General'].copy()
        else:
            filtered = df_injuries[df_injuries['team'] == selected_team].copy()
        
        # Filter by injury type
        if selected_injury_type != 'ALL INJURIES':
            filtered = filtered[filtered['injury_name'] == selected_injury_type]
        
        # Filter by severity
        if selected_severity != 'ALL':
            filtered = filtered[filtered['severity'] == selected_severity]
        
        # Filter by date
        now = datetime.now()
        if date_filter == "24H":
            cutoff = now - timedelta(days=1)
        elif date_filter == "3D":
            cutoff = now - timedelta(days=3)
        else:
            cutoff = now - timedelta(days=7)
        
        filtered = filtered[filtered['published'] >= cutoff]
        
        # Stats
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f"<p class='ticker'>INJURIES: {len(filtered)}</p>", unsafe_allow_html=True)
        with col2:
            st.markdown(f"<p class='ticker'>PLAYERS: {filtered['player'].nunique()}</p>", unsafe_allow_html=True)
        with col3:
            critical = len(filtered[filtered['severity'] == 'CRITICAL'])
            st.markdown(f"<p class='ticker'>CRITICAL: {critical}</p>", unsafe_allow_html=True)
        with col4:
            st.markdown(f"<p class='ticker'>FILTER: {selected_team}</p>", unsafe_allow_html=True)
        
        st.markdown("---")
        
        # Display injuries
        if not filtered.empty:
            for idx, row in filtered.iterrows():
                timestamp = row['published'].strftime('%m/%d %H:%M')
                severity_class = f"severity-{row['severity'].lower()}"
                
                st.markdown(f"""
                <div class='injury-item'>
                    <a href='{row['link']}' target='_blank' class='injury-headline'>{row['headline']}</a>
                    <div class='injury-meta'>{timestamp} | {row['player']} | {row['team']} | <span class='{severity_class}'>[{row['injury_code']}]</span></div>
                    <div class='injury-details'>
                        <strong>INJURY:</strong> {row['injury_name']}<br>
                        <strong>SEVERITY:</strong> <span class='{severity_class}'>{row['severity']}</span><br>
                        <strong>RECOVERY:</strong> {row['recovery']}<br>
                        <strong>DETAILS:</strong> {row['description']}
                    </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown(f"<p class='ticker'>NO INJURY DATA FOR {selected_team} IN {date_filter}</p>", unsafe_allow_html=True)
    else:
        st.error("INJURY FEED ERROR - RETRY")

# Refresh button
st.sidebar.markdown("---")
if st.sidebar.button("↻ REFRESH FEED"):
    st.cache_data.clear()
    st.rerun()
