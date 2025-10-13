# NFL News Terminal 🏈

A  news aggregator for NFL data. Real-time news feeds from all 32 NFL teams and major sports outlets, displayed in a professional interface.

![Terminal Style](https://img.shields.io/badge/style-terminal-green)
![Python](https://img.shields.io/badge/python-3.8+-blue)
![Streamlit](https://img.shields.io/badge/streamlit-1.28+-red)

## Features

- **Real-Time News Aggregation**: Pulls from 70+ RSS feeds across all 32 NFL teams
- **Team-Specific Filtering**: View news for individual teams or league-wide updates
- **Time Range Filters**: 24H, 3D, or 7D news views
- **Smart Caching**: 30-minute cache for optimal performance
- **Parallel Feed Fetching**: Multi-threaded RSS parsing for speed
- **Auto-Deduplication**: Removes duplicate stories across sources

## Data Sources

### General NFL News
- NFL.com Official Feed
- ESPN NFL News
- CBS Sports NFL

### Team-Specific Feeds
- Official team websites (all 32 teams)
- RotoWire team coverage
- 70+ total RSS feeds

## Installation

### Prerequisites
- Python 3.8 or higher
- pip package manager




### Theme Customization

Edit `.streamlit/config.toml` to customize colors:

```toml
[theme]
base = "dark"
primaryColor = "#00FF00"  # Terminal green
backgroundColor = "#000000"
secondaryBackgroundColor = "#1A1A1A"
textColor = "#FFFFFF"
font = "monospace"
```

### Cache Settings

Modify cache duration in `app.py`:
```python
@st.cache_data(ttl=1800)  # 1800 seconds = 30 minutes
```

## Usage

### Filter by Team
Use the sidebar dropdown to select:
- **ALL TEAMS**: View all NFL news
- **Specific Team**: Filter to one team (e.g., "Dallas Cowboys")
- **GENERAL**: League-wide news only

### Time Ranges
- **24H**: Last 24 hours
- **3D**: Last 3 days
- **7D**: Last 7 days (default)

### Refresh Data
Click "↻ REFRESH FEED" in the sidebar to clear cache and fetch latest news.

## Project Structure

```
nfl-news-terminal/
│
├── app.py                 # Main Streamlit application
├── requirements.txt       # Python dependencies
├── .streamlit/
│   └── config.toml       # Streamlit theme configuration
├── README.md             # This file
└── .gitignore            # Git ignore file
```

## Technical Details

### Performance Optimizations
- **Parallel Fetching**: 10 concurrent workers via ThreadPoolExecutor
- **Smart Caching**: 30-minute TTL on feed data
- **Entry Limiting**: Max 30 entries per feed
- **Hash-Based Deduplication**: MD5 hashing to remove duplicates

### Error Handling
- Graceful feed failures (continues if feeds timeout)
- Fallback date parsing
- Safe team extraction with regex

## Dependencies

```
streamlit>=1.28.0
feedparser>=6.0.10
pandas>=2.0.0
python-dateutil>=2.8.2
```



## Roadmap

- [ ] Add player-specific news filtering
- [ ] Integrate injury reports
- [ ] Add sentiment analysis
- [ ] Include betting odds data
- [ ] Export news to CSV/PDF
- [ ] Email alerts for team news
- [ ] Mobile-responsive design improvements



This application aggregates publicly available RSS feeds for informational purposes. All news content is owned by the respective publishers. This is not affiliated with the NFL.

---
