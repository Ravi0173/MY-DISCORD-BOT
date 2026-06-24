import discord
from discord.ext import commands
import os
import sqlite3
import re
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# --- 1. Keep-Alive Web Server ---
app = Flask('')
@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()

# --- 2. Configuration & Setup ---
if os.path.exists('Bot.env'):
    load_dotenv(dotenv_path='Bot.env')

token = os.getenv('DISCORD_TOKEN')
if not token:
    raise ValueError("DISCORD_TOKEN not found!")

# REPLACE THIS WITH YOUR ACTUAL LOG CHANNEL ID
LOG_CHANNEL_ID = 1519287894752231444 

intents = discord.Intents.default()
intents.members = True 
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

DB_NAME = "warnings.db"

# --- 3. Database ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS warnings 
                      (user_id INTEGER PRIMARY KEY, strikes INTEGER)''')
    conn.commit()
    conn.close()

init_db()

def add_strike(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''INSERT INTO warnings (user_id, strikes) VALUES (?, 1)
                      ON CONFLICT(user_id) DO UPDATE SET strikes = strikes + 1''', (user_id,))
    cursor.execute('SELECT strikes FROM warnings WHERE user_id = ?', (user_id,))
    count = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return count

BAD_WORDS = []
for filename in ["en.txt", "hi.txt"]:
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            BAD_WORDS.extend([line.strip().lower() for line in f if line.strip()])

# --- 4. Helper: Logging ---
async def log_action(guild, title, description, color=discord.Color.red()):
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(title=title, description=description, color=color)
        await log_channel.send(embed=embed)

# --- 5. Events ---
@bot.event
async def on_ready():
    print(f'SUCCESS! Logged in as {bot.user}')

@bot.event
async def on_message(message):
    if message.author.bot: return

    # ADMIN OVERRIDE
    if message.author.guild_permissions.administrator:
        await bot.process_commands(message)
        return

    content = message.content
    censored_content = content
    found = False

    for word in BAD_WORDS:
        clean_bad_word = re.sub(r'[^a-zA-Z0-9]', '', word.lower())
        if not clean_bad_word: continue
        
        pattern_str = "[^a-zA-Z0-9]*".join(list(clean_bad_word))
        if re.search(pattern_str, content, re.IGNORECASE):
            found = True
            pattern = re.compile(pattern_str, re.IGNORECASE)
            censored_content = pattern.sub("*" * len(clean_bad_word), censored_content)

    if found:
        await message.delete()
        await message.channel.send(f"{message.author.mention} said: {censored_content}")
        
        strike_count = add_strike(message.author.id)
        
        # Moderation Actions
        if strike_count >= 15:
            await message.author.ban(reason="Repeated abusive language")
            await log_action(message.guild, "User BANNED", f"**User:** {message.author}\n**Reason:** Repeated abusive language (15+ strikes).")
        elif strike_count >= 10:
            await message.author.kick(reason="Abusive language threshold reached")
            await log_action(message.guild, "User KICKED", f"**User:** {message.author}\n**Reason:** Abusive language threshold reached (10 strikes).")
        else:
            await message.channel.send(f"Watch your language, {message.author.mention}! (Strike {strike_count})")
        
        return

    await bot.process_commands(message)

# --- 6. Commands ---
@bot.command()
async def warnings(ctx, member: discord.Member = None):
    member = member or ctx.author
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT strikes FROM warnings WHERE user_id = ?', (member.id,))
    result = cursor.fetchone()
    count = result[0] if result else 0
    conn.close()
    await ctx.send(f"{member.name} has {count} strike(s).")

bot.run(os.getenv('DISCORD_TOKEN'))