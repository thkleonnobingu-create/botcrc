import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import aiohttp
import io
import re
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# --- CẤU HÌNH WEB SERVER (GIỮ BOT CHẠY 24/7 TRÊN RENDER) ---
app = Flask('')

@app.route('/')
def home():
    return "Bot Leaderboard is Online & Syncing!"

def run_server():
    # Render thường sử dụng cổng 8080 hoặc môi trường PORT
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_server)
    t.daemon = True
    t.start()

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
                # Tự động nâng cấp cấu trúc dữ liệu cũ lên cấu trúc mới (dict có img_msg_id)
                updated = False
                for key in list(data.keys()):
                    if isinstance(data[key], list):
                        data[key] = {"players": data[key], "img_msg_id": None}
                        updated = True
                if updated: save_json(filename, data)
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
                    # Làm mờ logo SCP làm nền (watermark)
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
                    if resp.status == 200:
                        avatar = Image.open(io.BytesIO(await resp.read())).convert("RGBA").resize((150, 150))
                        draw.rectangle([x-5, y-5, x+155, y+155], outline=(255, 255, 255), width=3)
                        bg.paste(avatar, (x, y), avatar)
                        draw.text((x + 30, y + 160), f"RANK {p['top']}", fill=(255, 255, 255))
            except: continue

    img_bin = io.BytesIO()
    bg.save(img_bin, format='PNG')
    img_bin.seek(0)
    return discord.File(fp=img_bin, filename="top_summary.png")

# --- Core Logic ---
def get_embed(p):
    mythic = "<:00:1465285228812701796><:10:1465285247649185944><:20:1465285263667363850><:30:1465285281404944577>"
    legend = "<:Legend1:1465293078859612253><:Legend2:1465293093686345883><:Legend3:1465293108529856726><:Legend4:1465293122912125114>"
    stg_type = p.get('stage', 'legend')
    stg_icon = mythic if stg_type == 'mythic' else legend
    
    embed = discord.Embed(title=f"Rank {p['top']} - {p['displayname']}", color=0x000000)
    embed.description = f"`⋆. 𐙚˚࿔ {p['username']} 𝜗𝜚˚⋆`"
    embed.add_field(name="════════ Information ════════", value=f"༒︎ Country: {p['country']}\n༒︎ Stage: {stg_icon}\n༒︎ Mention: <@{p['mention_id']}>", inline=False)
    embed.set_thumbnail(url=p['avatar_url'])
    embed.set_image(url=DECORATION_GIF)
    
    # Metadata lưu trữ ẩn trong Footer để phục vụ lệnh Sync (/run)
    embed.set_footer(text=f"RID:{p['roblox_id']} | STG:{stg_type}")
    return embed

async def update_board(channel, cid, data, edit_mode=False):
    players = data[cid]["players"]
    # Sắp xếp theo thứ tự Rank tăng dần
    players.sort(key=lambda x: int(x['top']))
    
    if edit_mode:
        # Chỉ chỉnh sửa các tin nhắn hiện có mà không xóa/gửi lại
        for p in players:
            if "msg_id" in p:
                try:
                    msg = await channel.fetch_message(p["msg_id"])
                    await msg.edit(embed=get_embed(p))
                except: pass
        save_json(DATA_FILE, data)
        return

    # Gửi bảng mới: Xóa các tin nhắn cũ của bot trong channel
    try: 
        await channel.purge(limit=100, check=lambda m: not m.pinned and m.author == channel.guild.me)
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
        # Sync các slash commands khi khởi động
        await self.tree.sync()

bot = TopBot()
group = app_commands.Group(name="topplayer", description="Leaderboard System")

@group.command(name="added", description="Thêm Rank mới hoặc ghi đè Rank cũ")
@app_commands.choices(stage=[
    app_commands.Choice(name="Legend", value="legend"), 
    app_commands.Choice(name="Mythic", value="mythic")
])
async def added(interaction: discord.Interaction, top: int, mention: discord.Member, displayname: str, stage: app_commands.Choice[str], roblox_id: str, country: str):
    if not is_authorized(interaction): 
        return await interaction.response.send_message("❌ Bạn không có quyền thực hiện lệnh này.", ephemeral=True)
        
    await interaction.response.defer(ephemeral=True)
    data = load_json(DATA_FILE)
    cid = str(interaction.channel_id)
    
    if cid not in data: 
        data[cid] = {"players": [], "img_msg_id": None}
    
    # Lấy Avatar từ Roblox API
    url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={roblox_id}&size=150x150&format=Png"
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            if r.status == 200:
                result = await r.json()
                av = result['data'][0]['imageUrl']
            else:
                av = ""
                
    entry = {
        "top": str(top), 
        "username": mention.name, 
        "mention_id": mention.id, 
        "displayname": displayname, 
        "stage": stage.value, 
        "roblox_id": roblox_id, 
        "country": country, 
        "avatar_url": av
    }
    
    # Xóa bản ghi cũ nếu trùng Rank
    data[cid]["players"] = [p for p in data[cid]["players"] if p['top'] != str(top)]
    data[cid]["players"].append(entry)
    
    await update_board(interaction.channel, cid, data)
    await interaction.followup.send(f"✅ Đã thêm Rank {top}.")

@group.command(name="run", description="Đồng bộ lại dữ liệu từ tin nhắn và cập nhật Avatar mới")
async def run_cmd(interaction: discord.Interaction):
    if not is_authorized(interaction): 
        return await interaction.response.send_message("❌ Lệnh bị từ chối.")
        
    await interaction.response.defer(ephemeral=True)
    
    cid = str(interaction.channel_id)
    data = load_json(DATA_FILE)
    if cid not in data: 
        data[cid] = {"players": [], "img_msg_id": None}

    # --- BƯỚC 1: QUÉT TIN NHẮN ĐỂ KHÔI PHỤC DATA ---
    scanned_players = []
    async for message in interaction.channel.history(limit=50):
        if message.author == bot.user and len(message.embeds) > 0:
            emb = message.embeds[0]
            if emb.title and "Rank" in emb.title:
                try:
                    # Regex để bóc tách thông tin từ Embed
                    rank = re.search(r"Rank (\d+)", emb.title).group(1)
                    dname = emb.title.split(" - ")[1].strip()
                    uname = emb.description.replace("`⋆. 𐙚˚࿔ ", "").replace(" 𝜗𝜚˚⋆`", "").strip()
                    m_id = re.search(r"<@(\d+)>", emb.fields[0].value).group(1)
                    ctry = re.search(r"Country: (.+)", emb.fields[0].value).group(1).split('\n')[0].strip()
                    
                    # Lấy metadata ẩn từ Footer
                    rid = re.search(r"RID:(.+) \|", emb.footer.text).group(1).strip()
                    stg = re.search(r"STG:(.+)", emb.footer.text).group(1).strip()
                    
                    scanned_players.append({
                        "top": rank, "username": uname, "mention_id": int(m_id),
                        "displayname": dname, "stage": stg, "roblox_id": rid,
                        "country": ctry, "avatar_url": emb.thumbnail.url,
                        "msg_id": message.id
                    })
                except: continue
    
    if scanned_players:
        data[cid]["players"] = scanned_players

    # --- BƯỚC 2: CẬP NHẬT AVATAR MỚI NHẤT TỪ ROBLOX ---
    players = data[cid]["players"]
    user_ids = [p["roblox_id"] for p in players if p.get("roblox_id")]
    if user_ids:
        ids_str = ",".join(user_ids)
        url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={ids_str}&size=150x150&format=Png"
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as r:
                if r.status == 200:
                    results = (await r.json())['data']
                    for res in results:
                        for p in players:
                            if str(p["roblox_id"]) == str(res["targetId"]):
                                p["avatar_url"] = res["imageUrl"]
    
    save_json(DATA_FILE, data)
    await update_board(interaction.channel, cid, data) 
    await interaction.followup.send("✅ Đã đồng bộ dữ liệu, cập nhật Avatar và làm mới bảng thành công!")

@group.command(name="edit", description="Sửa thông tin cụ thể của một Rank")
@app_commands.choices(stage=[
    app_commands.Choice(name="Legend", value="legend"), 
    app_commands.Choice(name="Mythic", value="mythic")
])
async def edit(interaction: discord.Interaction, top: int, mention: discord.Member = None, displayname: str = None, stage: app_commands.Choice[str] = None, roblox_id: str = None, country: str = None):
    if not is_authorized(interaction): return await interaction.response.send_message("❌ No permission.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    
    data = load_json(DATA_FILE)
    cid = str(interaction.channel_id)
    p = next((x for x in data.get(cid, {}).get("players", []) if x['top'] == str(top)), None)
    
    if not p: return await interaction.followup.send("❌ Không tìm thấy Rank này trong dữ liệu.")
    
    if mention: p["username"], p["mention_id"] = mention.name, mention.id
    if displayname: p["displayname"] = displayname
    if stage: p["stage"] = stage.value
    if country: p["country"] = country
    if roblox_id:
        p["roblox_id"] = roblox_id
        url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={roblox_id}&size=150x150&format=Png"
        async with aiohttp.ClientSession() as s:
            async with s.get(url) as r:
                if r.status == 200: 
                    p["avatar_url"] = (await r.json())['data'][0]['imageUrl']
                    
    save_json(DATA_FILE, data)
    await update_board(interaction.channel, cid, data, edit_mode=True)
    await interaction.followup.send(f"✅ Đã cập nhật Rank {top}.")

@group.command(name="exchange", description="Hoán đổi vị trí giữa 2 Rank")
async def exchange(interaction: discord.Interaction, rank1: int, rank2: int):
    if not is_authorized(interaction): return await interaction.response.send_message("❌ Lệnh bị từ chối.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    
    data = load_json(DATA_FILE); cid = str(interaction.channel_id)
    players = data.get(cid, {}).get("players", [])
    p1 = next((p for p in players if str(p['top']) == str(rank1)), None)
    p2 = next((p for p in players if str(p['top']) == str(rank2)), None)
    
    if p1 and p2:
        # Đổi thông tin trừ Rank và msg_id
        keys = ["username", "mention_id", "displayname", "stage", "roblox_id", "country", "avatar_url"]
        for k in keys: p1[k], p2[k] = p2[k], p1[k]
        save_json(DATA_FILE, data)
        await update_board(interaction.channel, cid, data, edit_mode=True)
        await interaction.followup.send(f"🔄 Đã tráo đổi Rank {rank1} và {rank2}.")
    else: 
        await interaction.followup.send("❌ Không tìm thấy đủ 2 Rank để hoán đổi.")

@group.command(name="remove", description="Xóa một Rank khỏi bảng")
async def remove(interaction: discord.Interaction, top: int):
    if not is_authorized(interaction): return await interaction.response.send_message("❌ Denied.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    
    data = load_json(DATA_FILE); cid = str(interaction.channel_id)
    if cid in data:
        data[cid]["players"] = [p for p in data[cid]["players"] if p['top'] != str(top)]
        await update_board(interaction.channel, cid, data)
        await interaction.followup.send(f"🗑️ Đã xóa Rank {top}.")

@group.command(name="permissions", description="Cấp quyền quản trị bot (Chỉ Owner)")
async def permissions(interaction: discord.Interaction, role: discord.Role = None, user: discord.Member = None):
    if interaction.user.id != BOT_OWNER_ID: return await interaction.response.send_message("⚠️ Chỉ Owner mới có quyền này.")
    
    auth = load_json(AUTH_FILE); gid = str(interaction.guild_id)
    if gid not in auth: auth[gid] = {"roles": [], "users": []}
    
    if role: auth[gid]["roles"].append(role.id)
    if user: auth[gid]["users"].append(user.id)
    
    save_json(AUTH_FILE, auth)
    await interaction.response.send_message("✅ Đã cập nhật quyền hạn.")

@group.command(name="removeperm", description="Xóa quyền quản trị bot (Chỉ Owner)")
async def removeperm(interaction: discord.Interaction, role: discord.Role = None, user: discord.Member = None):
    if interaction.user.id != BOT_OWNER_ID: return await interaction.response.send_message("⚠️ Chỉ Owner mới có quyền này.")
    
    auth = load_json(AUTH_FILE); gid = str(interaction.guild_id)
    if gid in auth:
        if role and role.id in auth[gid].get("roles", []): auth[gid]["roles"].remove(role.id)
        if user and user.id in auth[gid].get("users", []): auth[gid]["users"].remove(user.id)
        save_json(AUTH_FILE, auth)
        await interaction.response.send_message("🗑️ Đã thu hồi quyền hạn.")

bot.tree.add_command(group)

if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
