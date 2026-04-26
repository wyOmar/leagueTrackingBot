

# 🚀 Installation & Setup

Welcome to the League Tracker (FeedWatch) Bot! 


## Prerequisites
* **Python 3.11+**
* **MongoDB** (A free MongoDB Atlas cluster works perfectly)
* **Discord Bot Token** (from the Discord Developer Portal)
* **Riot Games API Key** (from the Riot Developer Portal)

---

## Step-by-Step Setup

### 1. Clone & Install Dependencies
Clone the repository to your local machine or server, then install the required Python packages.

```bash
git clone [https://github.com/yourusername/leagueTrackingBot.git](https://github.com/yourusername/leagueTrackingBot.git)
cd leagueTrackingBot
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Create a `.env` file in the root directory (you can copy `.env.example` if it exists) and fill in your credentials:

```env
DISCORD_TOKEN=your_discord_bot_token
RIOT_API_KEY=your_riot_api_key
MONGO_URI=your_mongodb_connection_string
MONGO_DB_NAME=league_tracker
LOG_LEVEL=INFO
```

### 3. Fetch Game Assets (Required)
Run the included update script to securely fetch the latest patch data and champion images from Riot's DataDragon CDN. 

```bash
python scripts/update_assets.py
```
*Note: This will automatically build an `assets/champion/` directory, populate it with `.png` files, and drop the latest `champion.json` into your root folder.*

### 4. Discord Developer Portal & Invite Setup
Before inviting the bot, you need to configure a few things in the Discord Developer Portal so it has the right permissions to auto-create dashboard channels and read server member lists.

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and select your application.
2. Go to the **Bot** tab, scroll down to **Privileged Gateway Intents**, and toggle on the **Server Members Intent**. *(Note: You can leave Presence and Message Content turned OFF, as this bot relies entirely on slash commands!)*
3. Go to the **Installation** tab.
4. Check the `bot` and `applications.commands` scopes.
5. Under **Bot Permissions**, check the following:
   - Manage Roles
   - Manage Channels
   - Send Messages
   - Embed Links
   - Attach Files
   - Read Message History
   - Use External Emojis
6. Copy the generated URL at the bottom and use it to invite the bot to your server.

### 5. Cache Assets Locally (.gitignore)
If you plan to fork this repository or push your own changes, you must ensure Riot's assets are not committed to your version control. 

Open the `.gitignore` file in the root directory and verify these lines are present:

```text
# Ignore downloaded Riot assets to prevent DMCA issues
assets/champion/
champion.json
```
This ensures your downloaded images act as a local cache on your server and will never be tracked by Git.

### 6. Start the Bot
Once your assets are downloaded, your `.env` is configured, and the bot is in your server, you are ready to start tracking!

```bash
python main.py
```

> **A Quick Note on Slash Commands:** > When running the bot for the very first time, Discord can take up to an hour to register global slash commands across all servers. If you are actively developing and want your commands to update instantly, check out the "DEVELOPMENT SYNC" comments inside `bot.py` to sync directly to your personal test server!
