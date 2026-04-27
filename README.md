# Aeloria - Living World Simulator

## Local Setup

1. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Install Node dependencies:
   ```bash
   npm install
   ```

3. Copy the example env and fill in your keys (the example has `FLASK_DEBUG=1` so **Flask restarts when you change `.py` files**; set `FLASK_DEBUG=0` for a single long-lived process or production). Keep `MAP_PUBLIC_URL=http://127.0.0.1:3000/map` for local dev so the home-page map iframe can reach Next.js.
   ```bash
   copy .env.example .env
   ```

4. Start **Flask and Next together** (recommended):
   ```bash
   npm run dev
   ```
   On Windows you can double-click `dev-all.bat` instead (it runs `npm install` if needed, then `npm run dev`).

   Flask-only (no interactive map unless Next is already running on port 3000):
   ```bash
   python app.py
   ```
   Or `dev-flask.bat` (sets `FLASK_DEBUG=1`).

5. Open:
   ```text
   http://localhost:5000
   ```

## How It Works

- **World tick** - the scheduler advances the world state on a timed interval
- **Lore drops** - `.txt` and `.md` files in `lore/` are absorbed into future ticks
- **God panel** - queued influence flows through `pending_lore.json`
- **Story generation** - narrative synopsis and audio can be generated from recent world history
- **Interactive map** - the Next.js app serves the Leaflet-based map experience

## Key Folders

| Folder | Purpose |
|--------|---------|
| `lore/` | Incoming lore and world influence files |
| `history/` | Archived tick logs as JSON and chronicle text |
| `weekly_stories/` | Generated story outputs |
| `logs/` | Application logs |
| `conversations/` | Character talk persistence |
| `static/audio/` | Generated audio files |
| `templates/` | Flask templates |
| `app/` | Next.js App Router frontend |
| `components/` | Next.js UI components |
| `data/` | Map data and structured frontend data |

## Production Deployment

This repo is now prepared to run as one live site:

- **Flask** serves the main Aeloria experience
- **Next.js** serves the interactive map
- **Nginx** routes both behind one public entry point

### Production Files

- `Dockerfile.flask`
- `Dockerfile.next`
- `docker-compose.prod.yml`
- `deploy/nginx.conf`

### Environment

Set these in your production `.env`:

```env
ANTHROPIC_API_KEY=your_anthropic_key_here
ELEVENLABS_API_KEY=your_elevenlabs_key_here
ELEVENLABS_VOICE_ID=onwK4e9ZLuTAKqWW03F9
DISCORD_WEBHOOK_URL=
LORE_DOCS_PATH=C:\Users\Josh\Desktop\lore_docs
STYLE_GUIDE_NAME=eryndor adventure
TICK_INTERVAL_HOURS=8
API_MODEL=claude-sonnet-4-6
PORT=5000
MAP_PUBLIC_URL=/map
NEXT_PUBLIC_SITE_URL=https://your-domain.example
```

### Build And Run

```bash
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
```

Public routing:

- `/` -> Flask app
- `/map` -> Next.js map app

### Health Checks

- Flask health: `/health`
- Next health through Nginx: `/api/health-next`

### Persistence

The production compose file preserves live world data by binding these files and folders into the Flask container:

- `world_state.json`
- `pending_lore.json`
- `god_actions.json`
- `narrative_synopsis.txt`
- `history/`
- `logs/`
- `lore/`
- `weekly_stories/`
- `conversations/`
- `static/audio/`

### Recommended Next Step

Deploy this stack to a VPS or cloud VM with Docker installed, then put your domain and HTTPS proxy in front of port `80`.
