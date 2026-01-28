import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import aiohttp
import io
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# --- CẤU HÌNH WEB SERVER CHO RENDER & UPTIMEROBOT ---
app = Flask('')

@app.route('/')
def home():
    return "I am alive!"

# Đổi tên từ 'run' thành 'run_server' để không trùng với lệnh /run của bot
def run_server():
    # Render yêu cầu chạy trên port 0.0.0.0
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    # Trỏ target vào đúng tên hàm mới
    t = Thread(target=run_server)
    t.start()
# -----------------------------------------------------

# --- Initialization ---
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# --- System Config ---
DATA_FILE = "topplayers_data.json"
AUTH_FILE = "authorized_users.json"
BOT_OWNER_ID = 626404653139099648
SCP_LOGO_URL = "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ec/SCP_Foundation_logo.svg/1200px-SCP_Foundation_logo.svg.png"
DECORATION_GIF = "https://cdn.discordapp.com/attachments/1327188364885102594/1443075988580995203/fixedbulletlines.gif"

# --- JSON Management ---
def load_json(filename):
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            try: 
                data = json.load(f)
                updated = False
                for key in list(data.keys()):
                    if isinstance(data[key], list):
                        data[key] = {"players": data[key], "img_msg_id": None}
                        updated = True
                if updated:
                    save_json(filename, data)
                return data
            except: return {}
    return {}

def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def is_authorized(interaction: discord.Interaction):
    if interaction.user.id == BOT_OWNER_ID: return True
    auth = load_json(AUTH_FILE)
    gid = str(interaction.guild_id)
    if gid in auth:
        if interaction.user.id in auth[gid].get("users", []): return True
        u_roles = [r.id for r in interaction.user.roles]
        for rid in auth[gid].get("roles", []):
            if rid in u_roles: return True
    return False

# --- Image Generation ---
async def create_top_player_image(players):
    canvas_w, canvas_h = 1100, 750
    bg = Image.new('RGB', (canvas_w, canvas_h), (0, 0, 0))
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(SCP_LOGO_URL) as resp:
                if resp.status == 200:
                    logo = Image.open(io.BytesIO(await resp.read())).convert("RGBA").resize((500, 500))
                    alpha = logo.getchannel('A').point(lambda i: i * 0.15)
                    logo.putalpha(alpha)
                    bg.paste(logo, (canvas_w//2 - 250, canvas_h//2 - 220), logo)
        except: pass
        draw = ImageDraw.Draw(bg)
        try: font = ImageFont.truetype("arial.ttf", 45)
        except: font = ImageFont.load_default()
        draw.text((canvas_w//2 - 250, 40), "TOP PLAYER SUMMARY", fill=(255, 255, 255), font=font)
        for i, p in enumerate(players[:10]):
            row, col = i // 5, i % 5
            x, y = 80 + (col * 200), 150 + (row * 280)
            try:
                async with session.get(p['avatar_url']) as resp:
                    avatar = Image.open(io.BytesIO(await resp.read())).convert("RGBA").resize((150, 150))
                    draw.rectangle([x-5, y-5, x+155, y+155], outline=(255, 255, 255), width=3)
                    bg.paste(avatar, (x, y), avatar)
                    draw.text((x + 30, y + 160), f"RANK {p['top']}", fill=(255, 255, 255))
            except: continue
    img_bin = io.BytesIO()
    bg.save(img_bin, format='PNG')
    img_bin.seek(0)
    return discord.File(fp=img_bin, filename="top_scp.png")

# --- Core Logic ---
def get_embed(p):
    mythic = "<:00:1465285228812701796><:10:1465285247649185944><:20:1465285263667363850><:30:1465285281404944577>"
    legend = "<:Legend1:1465293078859612253><:Legend2:1465293093686345883><:Legend3:1465293108529856726><:Legend4:1465293122912125114>"
    stg = mythic if p.get('stage') == 'mythic' else legend
    embed = discord.Embed(title=f"Rank {p['top']} - {p['displayname']}", color=0x000000)
    embed.description = f"`⋆. 𐙚˚࿔ {p['username']} 𝜗𝜚˚⋆`"
    embed.add_field(name="════════ Information ════════", value=f"༒︎ Country: {p['country']}\n༒︎ Stage: {stg}\n༒︎ Mention: <@{p['mention_id']}>", inline=False)
    embed.set_thumbnail(url=p['avatar_url'])
    embed.set_image(url=DECORATION_GIF)
    return embed

async def update_board(channel, cid, data, edit_mode=False):
    players = data[cid]["players"]
    players.sort(key=lambda x: int(x['top']))
    
    if edit_mode:
        for p in players:
            if "msg_id" in p:
                try:
                    msg = await channel.fetch_message(p["msg_id"])
                    await msg.edit(embed=get_embed(p))
                except: pass
        
        if "img_msg_id" in data[cid] and data[cid]["img_msg_id"]:
            try:
                old_img = await channel.fetch_message(data[cid]["img_msg_id"])
                await old_img.delete()
            except: pass
        
        if players:
            new_file = await create_top_player_image(players)
            sent_img = await channel.send(file=new_file)
            data[cid]["img_msg_id"] = sent_img.id
        
        save_json(DATA_FILE, data)
        return

    try: await channel.purge(limit=100, check=lambda m: not m.pinned)
    except: pass
    
    for p in players:
        msg = await channel.send(embed=get_embed(p))
        p["msg_id"] = msg.id
        
    if players:
        img_file = await create_top_player_image(players)
        img_msg = await channel.send(file=img_file)
        data[cid]["img_msg_id"] = img_msg.id
        
    save_json(DATA_FILE, data)

# --- Bot Commands ---
class TopBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
    async def setup_hook(self):
        await self.tree.sync()

bot = TopBot()
group = app_commands.Group(name="topplayer", description="Ranking Leaderboard System")

@group.command(name="added", description="Add a new player to the leaderboard (Full Refresh)")
@app_commands.describe(
    top="The rank number (e.g., 1, 2, 3...)",
    mention="Mention the Discord user (@User)",
    displayname="Name to display on the board",
    stage="Select player rank tier (Legend or Mythic)",
    roblox_id="Roblox User ID (numeric) for Avatar fetch",
    country="Country name or flag emoji"
)
@app_commands.choices(stage=[app_commands.Choice(name="Legend", value="legend"), app_commands.Choice(name="Mythic", value="mythic")])
async def added(interaction: discord.Interaction, top: int, mention: discord.Member, displayname: str, stage: app_commands.Choice[str], roblox_id: str, country: str):
    if not is_authorized(interaction): return await interaction.response.send_message("❌ You do not have permission to use this bot.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    
    data = load_json(DATA_FILE)
    cid = str(interaction.channel_id)
    if cid not in data: data[cid] = {"players": [], "img_msg_id": None}
    
    url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={roblox_id}&size=150x150&format=Png"
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            av = (await r.json())['data'][0]['imageUrl'] if r.status == 200 else ""
            
    entry = {"top": str(top), "username": mention.name, "mention_id": mention.id, "displayname": displayname, "stage": stage.value, "roblox_id": roblox_id, "country": country, "avatar_url": av}
    
    data[cid]["players"] = [p for p in data[cid]["players"] if p['top'] != str(top)]
    data[cid]["players"].append(entry)
    
    await update_board(interaction.channel, cid, data)
    await interaction.followup.send("✅ Player added and leaderboard refreshed.")

@group.command(name="exchange", description="Swap info between 2 ranks (Edits existing messages)")
@app_commands.describe(
    rank1="The first rank to swap",
    rank2="The second rank to swap"
)
async def exchange(interaction: discord.Interaction, rank1: int, rank2: int):
    if not is_authorized(interaction): return await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    
    data = load_json(DATA_FILE)
    cid = str(interaction.channel_id)
    if cid not in data: return await interaction.followup.send("❌ No leaderboard data found.")
    
    players = data[cid]["players"]
    p1 = next((p for p in players if str(p['top']) == str(rank1)), None)
    p2 = next((p for p in players if str(p['top']) == str(rank2)), None)
    
    if p1 and p2:
        keys_to_swap = ["username", "mention_id", "displayname", "stage", "roblox_id", "country", "avatar_url"]
        for key in keys_to_swap:
            p1[key], p2[key] = p2[key], p1[key]

        save_json(DATA_FILE, data)
        await update_board(interaction.channel, cid, data, edit_mode=True)
        await interaction.followup.send(f"🔄 Successfully swapped Rank {rank1} and Rank {rank2}.")
    else:
        await interaction.followup.send(f"❌ Could not find one or both ranks.")

@group.command(name="move", description="Move a player to a new rank (Shifts others accordingly)")
@app_commands.describe(
    current_top="The player's current rank",
    new_top="The target rank to move them to"
)
async def move(interaction: discord.Interaction, current_top: int, new_top: int):
    if not is_authorized(interaction): return await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    
    data = load_json(DATA_FILE)
    cid = str(interaction.channel_id)
    if cid not in data: return await interaction.followup.send("❌ No data found.")
    
    players = data[cid]["players"]
    players.sort(key=lambda x: int(x['top']))
    
    source_idx = next((i for i, p in enumerate(players) if p['top'] == str(current_top)), None)
    dest_idx = next((i for i, p in enumerate(players) if p['top'] == str(new_top)), None)
    
    if source_idx is not None and dest_idx is not None:
        source_data = {k: v for k, v in players[source_idx].items() if k not in ["top", "msg_id"]}
        
        if source_idx > dest_idx: # Moving UP
            for i in range(source_idx, dest_idx, -1):
                prev_data = {k: v for k, v in players[i-1].items() if k not in ["top", "msg_id"]}
                for k, v in prev_data.items():
                    players[i][k] = v
        else: # Moving DOWN
            for i in range(source_idx, dest_idx):
                next_data = {k: v for k, v in players[i+1].items() if k not in ["top", "msg_id"]}
                for k, v in next_data.items():
                    players[i][k] = v
        
        for k, v in source_data.items():
            players[dest_idx][k] = v

        save_json(DATA_FILE, data)
        await update_board(interaction.channel, cid, data, edit_mode=True)
        await interaction.followup.send(f"⏩ Moved Rank {current_top} to Rank {new_top}.")
    else:
        await interaction.followup.send("❌ Rank(s) not found.")

@group.command(name="remove", description="Remove a player from the board")
@app_commands.describe(top="The rank number to remove")
async def remove(interaction: discord.Interaction, top: int):
    if not is_authorized(interaction): return await interaction.response.send_message("❌ Access Denied.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    data = load_json(DATA_FILE)
    cid = str(interaction.channel_id)
    if cid in data:
        data[cid]["players"] = [p for p in data[cid]["players"] if p['top'] != str(top)]
        await update_board(interaction.channel, cid, data)
        await interaction.followup.send(f"🗑️ Removed Rank {top}.")

@group.command(name="run", description="Manually refresh and re-post the leaderboard")
async def run(interaction: discord.Interaction):
    if not is_authorized(interaction): return await interaction.response.send_message("❌ Access Denied.")
    await interaction.response.defer(ephemeral=True)
    data = load_json(DATA_FILE)
    cid = str(interaction.channel_id)
    if cid in data:
        await update_board(interaction.channel, cid, data)
        await interaction.followup.send("✅ Leaderboard refreshed.")

@group.command(name="permissions", description="Grant bot access to a Role or User (Owner Only)")
@app_commands.describe(role="The Role to authorize", user="The User to authorize")
async def permissions(interaction: discord.Interaction, role: discord.Role = None, user: discord.Member = None):
    if interaction.user.id != BOT_OWNER_ID: return await interaction.response.send_message("⚠️ Owner Only.")
    auth = load_json(AUTH_FILE)
    gid = str(interaction.guild_id)
    if gid not in auth: auth[gid] = {"roles": [], "users": []}
    if role: auth[gid]["roles"].append(role.id)
    if user: auth[gid]["users"].append(user.id)
    save_json(AUTH_FILE, auth)
    await interaction.response.send_message("✅ Permissions updated.")

@group.command(name="removeperm", description="Revoke bot access (Owner Only)")
@app_commands.describe(role="The Role to revoke", user="The User to revoke")
async def removeperm(interaction: discord.Interaction, role: discord.Role = None, user: discord.Member = None):
    if interaction.user.id != BOT_OWNER_ID: return await interaction.response.send_message("⚠️ Owner Only.")
    auth = load_json(AUTH_FILE)
    gid = str(interaction.guild_id)
    if gid in auth:
        if role and role.id in auth[gid]["roles"]: auth[gid]["roles"].remove(role.id)
        if user and user.id in auth[gid]["users"]: auth[gid]["users"].remove(user.id)
        save_json(AUTH_FILE, auth)
    await interaction.response.send_message("🗑️ Permissions revoked.")

bot.tree.add_command(group)

# --- CHẠY WEB SERVER TRƯỚC KHI CHẠY BOT ---
keep_alive()

bot.run(TOKEN)
