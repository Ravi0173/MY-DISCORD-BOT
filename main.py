import discord
from discord.ext import commands
import os
import sqlite3
import re
from dotenv import load_dotenv
from openai import OpenAI
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

# --- 2. Setup ---
# Only load .env if it exists (local development)
if os.path.exists('Bot.env'):
    load_dotenv(dotenv_path='Bot.env')

# Check if keys exist
token = os.getenv('DISCORD_TOKEN')
if not token:
    raise ValueError("DISCORD_TOKEN not found! Ensure it is set in your Render environment variables.")

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.getenv('OPENAI_API_KEY'))

intents = discord.Intents.default()
intents.members = True 
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Configuration
DB_NAME = "warnings.db"

# --- 3. Database Initialization ---
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

# --- 4. Load Words ---
def get_bad_words():
    combined_list = []
    files = ["en.txt", "hi.txt"]
    for filename in files:
        if os.path.exists(filename):
            with open(filename, "r", encoding="utf-8") as f:
                combined_list.extend([line.strip().lower() for line in f if line.strip()])
    return combined_list

BAD_WORDS = get_bad_words()

# --- 5. Events ---
@bot.event
async def on_ready():
    print(f'SUCCESS! Logged in as {bot.user}')

@bot.event
async def on_message(message):
    if message.author.bot: return

    # Censor Logic
    content = message.content
    found = False
    
    for word in BAD_WORDS:
        if word.lower() in content.lower():
            pattern = re.compile(re.escape(word), re.IGNORECASE)
            content = pattern.sub("*" * len(word), content)
            found = True
            
    if found:
        await message.delete()
        await message.channel.send(f"{message.author.mention} said: {content}")
        
        strike_count = add_strike(message.author.id)
        
        if strike_count >= 15:
            await message.author.ban(reason="Repeated abusive language")
        elif strike_count >= 10:
            await message.author.kick(reason="Abusive language threshold reached")
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

@bot.command()
async def ask(ctx, *, question):
    completion = client.chat.completions.create(
        model="meta-llama/llama-3.3-70b-instruct", 
        messages=[{"role": "user", "content": question}]
    )
    await ctx.send(completion.choices[0].message.content)

bot.run(os.getenv('DISCORD_TOKEN'))