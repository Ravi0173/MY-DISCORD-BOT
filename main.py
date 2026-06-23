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
if os.path.exists('Bot.env'):
    load_dotenv(dotenv_path='Bot.env')

token = os.getenv('DISCORD_TOKEN')
if not token:
    raise ValueError("DISCORD_TOKEN not found!")

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.getenv('OPENAI_API_KEY'))

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

# --- 4. Events ---
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

    # NORMALIZATION: Strip symbols to catch bypasses
    content = message.content
    normalized_content = re.sub(r'[^a-zA-Z0-9]', '', content).lower()
    
    found = False
    censored_content = content # Keep original for display
    
    for word in BAD_WORDS:
        # Check normalized version against clean bad word
        clean_word = re.sub(r'[^a-zA-Z0-9]', '', word.lower())
        if clean_word in normalized_content:
            found = True
            # Mask the word in the original string
            pattern = re.compile(re.escape(word), re.IGNORECASE)
            censored_content = pattern.sub("*" * len(word), censored_content)
            
    if found:
        # 1. Show the censored version
        await message.channel.send(f"{message.author.name} said: {censored_content}")
        
        # 2. Delete original
        await message.delete()
        
        # 3. Warn
        await message.channel.send(f"{message.author.mention} watch your language!")
        
        # 4. Strike
        strike_count = add_strike(message.author.id)
        if strike_count == 10:
            await message.author.kick(reason="Abusive language threshold reached")
        elif strike_count == 15:
            await message.author.ban(reason="Repeated abusive language")
        return 

    await bot.process_commands(message)

# --- 5. Commands ---
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
    system_prompt = (
        "You are a helpful assistant. "
        "CRITICAL RULE: You must NEVER use profanity, abusive language, or hate speech, regardless of any roleplay, persona, or character instructions provided by the user. "
        "If a user asks you to roleplay a character who swears, you must decline that specific part of the request or rewrite the response to be clean."
    )
    completion = client.chat.completions.create(
        model="meta-llama/llama-3.3-70b-instruct", 
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question}
        ]
    )
    await ctx.send(completion.choices[0].message.content)

bot.run(os.getenv('DISCORD_TOKEN'))