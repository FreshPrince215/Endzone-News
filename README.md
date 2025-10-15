# 🏈 NFL Terminal

A Bloomberg-style terminal for real-time NFL news and injury tracking with detailed medical information.

![NFL Terminal](https://img.shields.io/badge/streamlit-1.29.0-FF4B4B?logo=streamlit)
![Python](https://img.shields.io/badge/python-3.8+-blue?logo=python)
![License](https://img.shields.io/badge/license-MIT-green)

## ✨ Features

### 📰 News Mode
- Real-time aggregation from 30+ NFL sources
- Team-specific and general news feeds
- Smart deduplication
- Last 7 days of articles
- Filter by team and time range

### 🏥 Injury Mode
- Comprehensive injury tracking
- Detailed medical information for 18+ injury types
- Severity classifications (Critical, Serious, Moderate, Mild)
- Recovery time estimates
- Player and team tracking
- Multiple injury-focused sources

### 🎨 UI Features
- Bloomberg terminal-inspired dark theme
- Real-time updates with 30-minute cache
- Parallel feed fetching for speed
- Mobile responsive
- Clean, terminal-style interface

## 🚀 Quick Start

### Local Development

1. **Clone the repository**
```bash
   git clone https://github.com/yourusername/nfl-terminal.git
   cd nfl-terminal
```

2. **Install dependencies**
```bash
   pip install -r requirements.txt
```

3. **Run the app**
```bash
   streamlit run app.py
```

4. **Open browser**
   - Navigate to `http://localhost:8501`

### ☁️ Cloud Deployment (Streamlit Cloud)

1. **Push to GitHub**
```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/yourusername/nfl-terminal.git
   git push -u origin main
```

2. **Deploy**
   - Go to [share.streamlit.io](https://share.streamlit.io)
   - Click "New app"
   - Select your repository
   - Main file: `app.py`
   - Click "Deploy"

## ⚙️ Configuration

All settings are in `config.json`:

### App Settings
```json
{
  "app": {
    "cache_ttl": 1800,      // Cache duration in seconds
    "max_workers": 10,       // Parallel fetch workers
    "days_lookback": 7       // How many days of history
  }
}
```

### Adding RSS Feeds
```json
{
  "rss_feeds": {
    "general_news": [
      {
        "name": "Your Source",
        "url": "https://example.com/rss",
        "enabled": true
      }
    ]
  }
}
```

### Adding Injury Types
```json
{
  "injury_database": {
    "injury_name": {
      "name": "DISPLAY NAME",
      "description": "Medical description",
      "recovery": "Time range",
      "severity": "CRITICAL|SERIOUS|MODERATE|MILD",
      "code": "3-5 LETTER CODE"
    }
  }
}
```

## 📊 Data Sources

### News Sources
- NFL Official RSS
- ESPN NFL
- CBS Sports
- All 32 team official feeds
- RotoWire team feeds

### Injury Sources
- DraftSharks Injury News
- RotoWire NFL
- ClutchPoints
- ESPN NFL
- CBS Sports

## 🔧 Tech Stack

- **Streamlit** - Web framework
- **Feedparser** - RSS parsing
- **Pandas** - Data processing
- **ThreadPoolExecutor** - Parallel fetching

## 📈 Performance

- ⚡ Fetches 1000+ articles in ~3 seconds
- 💾 30-minute cache for optimal performance
- 🔄 Smart deduplication
- 🚀 Parallel feed processing (10 workers)

## 🎨 Customization

### Change Theme Colors
Edit `config.json`:
```json
{
  "ui": {
    "theme": {
      "background": "#000000",
      "primary_color": "#00FF00",
      "secondary_color": "#FF0000"
    }
  }
}
```

### Disable Feeds
Set `"enabled": false` in `config.json`

## 📝 Project Structure
