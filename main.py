"""K~BOT + KOIN SYSTEM - Unico bot finale."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("kbot")

DATA_DIR = Path(__file__).resolve().parent
FLAG_WINS_PATH = DATA_DIR / "flag_wins.json"
MESSAGES_PATH = DATA_DIR / "messages.json"
KOIN_PATH = DATA_DIR / "koin_data.json"
MISSIONS_PATH = DATA_DIR / "missions.json"
MUSIC_FILE = DATA_DIR / "music.mp3"
# === LINK EUROPAPA - NON SERVE FILE EXTRA ===
MUSIC_URL = "https://www.youtube.com/watch?v=vwQMhow5-o8" # Joost Klein - Europapa
UTC = timezone.utc
ROME_TZ = ZoneInfo("Europe/Rome")

FLAGS = [
    ("🇮🇹", "italia"), ("🇯🇵", "giappone"), ("🇺🇸", "usa"),
    ("🇫🇷", "francia"), ("🇪🇸", "spagna"), ("🇩🇪", "germania"),
    ("🇬🇧", "inghilterra"), ("🇧🇷", "brasile"),
]

ROLE_STAFF = "STAFF"
ROLE_PRICES = {"ELITE": 3000, "GOD": 5000, "RICH": 10000}

def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default.copy()
    try:
        with path.open("r", encoding="utf-8") as file:
            value = json.load(file)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path.name} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} must contain a JSON object.")
    return value

def save_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
    tmp.replace(path)

flag_wins: dict[str, int] = {str(k): int(v) for k, v in load_json(FLAG_WINS_PATH, {}).items()}
messages: dict[str, list[str]] = {}
for uid, ts in load_json(MESSAGES_PATH, {}).items():
    if isinstance(ts, list):
        messages[str(uid)] = [str(t) for t in ts]

koin_data: dict[str, int] = {}
raw_koin = load_json(KOIN_PATH, {})
for k, v in raw_koin.items():
    try:
        if isinstance(v, dict): koin_data[str(k)] = int(v.get("coins", 0))
        else: koin_data[str(k)] = int(v)
    except: pass

missions_data: dict[str, Any] = load_json(MISSIONS_PATH, {})

if not FLAG_WINS_PATH.exists(): save_json(FLAG_WINS_PATH, flag_wins)
if not MESSAGES_PATH.exists(): save_json(MESSAGES_PATH, messages)
if not KOIN_PATH.exists(): save_json(KOIN_PATH, koin_data)
if not MISSIONS_PATH.exists(): save_json(MISSIONS_PATH, missions_data)

current_flag: str | None = None
time_online: dict[tuple[int, int], datetime] = {}
voice_join_time: dict[int, datetime] = {}
voice_clients_music: dict[int, discord.VoiceClient] = {}
last_midnight_bonus_date: str | None = None

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="?", intents=intents, help_command=None, description="K~BOT - KROMA®")

def parse_timestamp(v: str) -> datetime | None:
    try:
        p = datetime.fromisoformat(v)
    except: return None
    if p.tzinfo is None: p = p.replace(tzinfo=UTC)
    return p.astimezone(UTC)

def recent_message_times(user_id: str, now: datetime) -> list[str]:
    cutoff = now - timedelta(days=7)
    recent = []
    for value in messages.get(user_id, []):
        parsed = parse_timestamp(value)
        if parsed is not None and parsed >= cutoff:
            recent.append(parsed.isoformat())
    return recent

def format_duration(started_at: datetime) -> str:
    seconds = max(0, int((datetime.now(UTC) - started_at).total_seconds()))
    h, r = divmod(seconds, 3600)
    m = r // 60
    return f"{h}h {m}m"

# --- KOIN HELPERS ---
def get_koins(user_id: int | str) -> int:
    return koin_data.get(str(user_id), 0)

def set_koins(user_id: int | str, amount: int):
    koin_data[str(user_id)] = max(0, int(amount))
    save_json(KOIN_PATH, koin_data)

def add_koins(user_id: int | str, amount: int) -> int:
    uid = str(user_id)
    koin_data[uid] = max(0, get_koins(uid) + int(amount))
    save_json(KOIN_PATH, koin_data)
    return koin_data[uid]

def get_today_rome_str() -> str:
    return datetime.now(ROME_TZ).strftime("%Y-%m-%d")

def get_user_mission_day(uid: str, date_str: str) -> dict[str, Any]:
    if uid not in missions_data:
        missions_data[uid] = {}
    if date_str not in missions_data[uid]:
        missions_data[uid][date_str] = {
            "messages": 0,
            "voice_seconds": 0,
            "pings": 0,
            "completed": {"msg35": False, "voice30": False, "ping5": False}
        }
    return missions_data[uid][date_str]

def save_missions():
    save_json(MISSIONS_PATH, missions_data)

def get_audio_source():
    if MUSIC_FILE.exists():
        return discord.FFmpegPCMAudio(str(MUSIC_FILE))
    if MUSIC_URL:
        if "youtube.com" in MUSIC_URL or "youtu.be" in MUSIC_URL:
            try:
                import yt_dlp
                ydl_opts = {"format":"bestaudio/best","quiet":True,"no_warnings":True,"noplaylist":True}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(MUSIC_URL, download=False)
                    if "entries" in info: info = info["entries"][0]
                    url = info.get("url") or info["formats"][-1]["url"]
                    return discord.FFmpegPCMAudio(url, before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5", options="-vn")
            except Exception as e:
                logger.warning(f"yt-dlp errore: {e}")
        return discord.FFmpegPCMAudio(MUSIC_URL, before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5", options="-vn")
    return None

async def is_staff(interaction: discord.Interaction) -> bool:
    member = interaction.user
    return isinstance(member, discord.Member) and any(r.name == ROLE_STAFF for r in member.roles)

async def send_ephemeral_error(interaction: discord.Interaction, content: str) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)

# --- SHOP VIEW ---
class ShopView(discord.ui.View):
    def __init__(self): super().__init__(timeout=180)

    async def buy_role(self, interaction: discord.Interaction, role_name: str, price: int):
        coins = get_koins(interaction.user.id)
        if coins < price:
            await interaction.response.send_message(f"Non hai abbastanza KOINS! Hai {coins} ma servono {price}.", ephemeral=True)
            return
        role = discord.utils.get(interaction.guild.roles, name=role_name)
        if not role:
            await interaction.response.send_message(f"Ruolo {role_name} non esiste. Crealo su Discord.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.response.send_message(f"Hai già {role_name}!", ephemeral=True)
            return
        add_koins(interaction.user.id, -price)
        try:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(f"Hai comprato **{role_name}** per {price} KOINS! 🪙 Saldo: {get_koins(interaction.user.id)}", ephemeral=True)
        except discord.Forbidden:
            add_koins(interaction.user.id, price)
            await interaction.response.send_message("Non ho permessi per dare il ruolo. Metti il mio ruolo sopra a ELITE/GOD/RICH.", ephemeral=True)

    @discord.ui.button(label="ELITE - 3000 KOINS", style=discord.ButtonStyle.primary)
    async def buy_elite(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.buy_role(interaction, "ELITE", 3000)

    @discord.ui.button(label="GOD - 5000 KOINS", style=discord.ButtonStyle.danger)
    async def buy_god(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.buy_role(interaction, "GOD", 5000)

    @discord.ui.button(label="RICH - 10000 KOINS", style=discord.ButtonStyle.success)
    async def buy_rich(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.buy_role(interaction, "RICH", 10000)

@bot.event
async def on_ready() -> None:
    if bot.user is None: return
    for guild in bot.guilds:
        for member in guild.members:
            if member.joined_at is not None:
                time_online[(guild.id, member.id)] = member.joined_at.astimezone(UTC)
    synced = await bot.tree.sync()
    logger.info(f"Logged {bot.user} - {len(synced)} commands")
    if not passive_income.is_running():
        passive_income.start()
    if not voice_time_tracker.is_running():
        voice_time_tracker.start()
    if not midnight_bonus.is_running():
        midnight_bonus.start()

@bot.event
async def on_member_join(member: discord.Member) -> None:
    time_online[(member.guild.id, member.id)] = datetime.now(UTC)

@bot.event
async def on_message(message: discord.Message) -> None:
    global current_flag
    if message.author.bot: return
    now = datetime.now(UTC)
    uid = str(message.author.id)
    messages[uid] = recent_message_times(uid, now)
    messages[uid].append(now.isoformat())
    save_json(MESSAGES_PATH, messages)

    # --- MISSIONI ---
    today = get_today_rome_str()
    day_data = get_user_mission_day(uid, today)
    day_data["messages"] += 1
    if len(message.mentions) > 0:
        day_data["pings"] += len(message.mentions)

    rewards = []
    if not day_data["completed"]["msg35"] and day_data["messages"] >= 35:
        day_data["completed"]["msg35"] = True
        add_koins(uid, 30)
        rewards.append("✅ Missione **35 messaggi** completata! +30 KOINS")
    if not day_data["completed"]["ping5"] and day_data["pings"] >= 5:
        day_data["completed"]["ping5"] = True
        add_koins(uid, 100)
        rewards.append("✅ Missione **Pinga 5 persone** completata! +100 KOINS")
    save_missions()
    for r in rewards:
        try: await message.channel.send(f"{message.author.mention} {r}")
        except: pass

    if current_flag is not None and message.content == current_flag:
        flag_wins[uid] = flag_wins.get(uid, 0) + 1
        save_json(FLAG_WINS_PATH, flag_wins)
        await message.channel.send(f"🏆 {message.author.mention} ha indovinato, 🏆 vittorie totali= {flag_wins[uid]} 🏆")
        current_flag = None
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    now = datetime.now(UTC)
    uid = member.id
    # tracking vocale per missioni
    if before.channel is None and after.channel is not None:
        voice_join_time[uid] = now
    elif before.channel is not None and after.channel is None:
        start = voice_join_time.pop(uid, None)
        if start:
            sec = int((now - start).total_seconds())
            day_data = get_user_mission_day(str(uid), get_today_rome_str())
            day_data["voice_seconds"] += sec
            save_missions()
    elif before.channel and after.channel and before.channel.id!= after.channel.id:
        start = voice_join_time.get(uid)
        if start:
            sec = int((now - start).total_seconds())
            day_data = get_user_mission_day(str(uid), get_today_rome_str())
            day_data["voice_seconds"] += sec
        voice_join_time[uid] = now
        save_missions()

    # --- MUSICA SMART EUROPAPA ---
    channel = after.channel or before.channel
    if channel is None: return
    humans = [m for m in channel.members if not m.bot]
    guild_id = channel.guild.id
    try:
        vc = discord.utils.get(bot.voice_clients, guild=channel.guild)
        if len(humans) == 1:
            if vc is None or not vc.is_connected():
                try:
                    vc = await channel.connect()
                    voice_clients_music[guild_id] = vc
                except Exception as e:
                    logger.warning(f"Connessione fallita: {e}")
                    return
            if vc and not vc.is_playing():
                audio = get_audio_source()
                if not audio: return
                source = discord.PCMVolumeTransformer(audio, volume=1.0)
                vc.play(source, after=lambda e: logger.info(f"Fine musica: {e}") if e else None)
            else:
                if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
                    vc.source.volume = 1.0
        elif len(humans) >= 2:
            if vc and vc.is_connected() and vc.channel and vc.channel.id == channel.id:
                if vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
                    vc.source.volume = 0.15
        elif len(humans) == 0:
            if vc and vc.is_connected() and vc.channel and vc.channel.id == channel.id:
                await vc.disconnect()
                voice_clients_music.pop(guild_id, None)
    except Exception as e:
        logger.exception(f"Errore musica: {e}")

# --- TASK 10 KOINS AL MINUTO IN VOCALE ---
@tasks.loop(minutes=1)
async def passive_income():
    changed = False
    for guild in bot.guilds:
        for vc in guild.voice_channels:
            for member in vc.members:
                if member.bot: continue
                koin_data[str(member.id)] = get_koins(member.id) + 10
                changed = True
    if changed:
        save_json(KOIN_PATH, koin_data)

@tasks.loop(seconds=30)
async def voice_time_tracker():
    now = datetime.now(UTC)
    today = get_today_rome_str()
    for uid, start in list(voice_join_time.items()):
        sec = int((now - start).total_seconds())
        if sec < 10: continue
        day_data = get_user_mission_day(str(uid), today)
        day_data["voice_seconds"] += sec
        voice_join_time[uid] = now
        if not day_data["completed"]["voice30"] and day_data["voice_seconds"] >= 1800:
            day_data["completed"]["voice30"] = True
            add_koins(str(uid), 45)
            try:
                user = bot.get_user(uid) or await bot.fetch_user(uid)
                if user: await user.send("✅ Missione **30 minuti in vocale** completata! +45 KOINS")
            except: pass
        save_missions()

@tasks.loop(minutes=1)
async def midnight_bonus():
    global last_midnight_bonus_date
    now_rome = datetime.now(ROME_TZ)
    if now_rome.hour == 0 and now_rome.minute == 0:
        today_str = now_rome.strftime("%Y-%m-%d")
        if last_midnight_bonus_date == today_str: return
        last_midnight_bonus_date = today_str
        count = 0
        for guild in bot.guilds:
            for member in guild.members:
                if member.bot: continue
                add_koins(member.id, 100)
                count += 1
        for guild in bot.guilds:
            channel = guild.system_channel or (guild.text_channels[0] if guild.text_channels else None)
            if channel:
                try:
                    await channel.send(f"🌙 **BONUS MEZZANOTTE!** 00:00 ITA - **100 KOINS** a tutti! 🪙 ({count} utenti)")
                except: pass

# --- COMANDI PREFIX ORIGINALI ---
@bot.command(name="flag")
async def flag_command(ctx: commands.Context) -> None:
    global current_flag
    flag_emoji, country = random.choice(FLAGS)
    current_flag = country
    await ctx.send(flag_emoji)

@bot.command(name="topflag")
async def topflag_command(ctx: commands.Context) -> None:
    leaderboard = sorted(flag_wins.items(), key=lambda item: (-item[1], int(item[0])))[:10]
    lines = ["🏆 TOP FLAG LEADERBOARD 🏆"]
    if leaderboard: lines.extend(f"{rank}. <@{uid}> - {wins} wins" for rank, (uid, wins) in enumerate(leaderboard, 1))
    else: lines.append("Nessuna vittoria ancora.")
    await ctx.send("\n".join(lines))

@bot.command(name="descrizione")
async def descrizione_command(ctx: commands.Context) -> None:
    desc = "KROMA® - BEYOND CLOTHING\n\nNon è solo streetwear, è attitudine.\n\nOgni drop è limitato, ogni pezzo è studiato nei minimi dettagli.\n\nEntra nella community, resta attivo e non perderti il prossimo.\n\n— KROMA STAFF —"
    try: await ctx.author.send(desc)
    except discord.Forbidden:
        await ctx.send("❌ Non riesco a mandarti DM, aprili!"); return
    await ctx.send("📩 Ti ho mandato la descrizione in DM!")

@bot.command(name="msg")
async def msg_command(ctx: commands.Context) -> None:
    now = datetime.now(UTC); uid = str(ctx.author.id)
    messages[uid] = recent_message_times(uid, now); save_json(MESSAGES_PATH, messages)
    await ctx.send(f"📩 {ctx.author.mention} hai scritto {len(messages[uid])} messaggi negli ultimi 7 giorni")

@bot.command(name="servertime")
async def servertime_command(ctx: commands.Context) -> None:
    if ctx.guild is None: await ctx.send("❌ Solo nel server."); return
    key = (ctx.guild.id, ctx.author.id); joined_at = time_online.get(key)
    if joined_at is None:
        try: member = await ctx.guild.fetch_member(ctx.author.id)
        except: await ctx.send("❌ Non trovo data ingresso."); return
        joined_at = member.joined_at
        if joined_at is None: await ctx.send("❌ Non trovo data ingresso."); return
        joined_at = joined_at.astimezone(UTC); time_online[key] = joined_at
    await ctx.send(f"⏱️ {ctx.author.mention} sei stato online per {format_duration(joined_at)}")

@bot.command(name="timeleaderboard")
async def timeleaderboard_command(ctx: commands.Context) -> None:
    if ctx.guild is None: await ctx.send("❌ Solo nel server."); return
    entries = [(uid, ja) for (gid, uid), ja in time_online.items() if gid == ctx.guild.id]
    entries.sort(key=lambda i: (i[1], i[0]))
    lines = ["⏰ TIME LEADERBOARD"]
    lines.extend(f"{r}. <@{uid}> - {format_duration(ja)}" for r, (uid, ja) in enumerate(entries[:10], 1))
    if not entries: lines.append("Nessun dato.")
    await ctx.send("\n".join(lines))

# --- SLASH ORIGINALI ---
@bot.tree.command(name="release", description="Pubblica una nuova release.")
@app_commands.describe(name="Nome della release", category="Categoria", tag="Tag", photo="Foto della release")
@app_commands.check(is_staff)
async def release_command(interaction: discord.Interaction, name: str, category: str, tag: str, photo: discord.Attachment) -> None:
    if interaction.channel is None: await send_ephemeral_error(interaction, "❌ Canale non disponibile."); return
    await interaction.channel.send(f"—--:RELEASE:—--\n\n📝 NAME: {name}\n\n👕 CATEGORY: {category}\n\n🏷️ TAG: {tag}", allowed_mentions=discord.AllowedMentions.none())
    await interaction.channel.send(photo.url)
    await interaction.response.send_message("Inviato!", ephemeral=True)

@bot.tree.command(name="stafflist", description="Mostra tutti i membri dello STAFF.")
@app_commands.check(is_staff)
async def stafflist_command(interaction: discord.Interaction) -> None:
    if interaction.guild is None: await send_ephemeral_error(interaction, "❌ Solo nel server."); return
    staff_members = []
    async for member in interaction.guild.fetch_members(limit=None):
        if any(role.name == ROLE_STAFF for role in member.roles): staff_members.append(member)
    lines = [f"👑 {m.mention} - STAFF" for m in sorted(staff_members, key=lambda i: i.display_name.casefold())]
    if not lines: lines = ["Nessun STAFF."]
    msgs, cur = [], ["—--:STAFFLIST:—--", ""]
    for line in lines:
        if len("\n".join(cur + [line])) > 1900: msgs.append("\n".join(cur)); cur = []
        cur.append(line)
    if cur: msgs.append("\n".join(cur))
    for c in msgs: await interaction.channel.send(c, allowed_mentions=discord.AllowedMentions.none())
    await interaction.response.send_message("Inviato!", ephemeral=True)

@bot.tree.command(name="say", description="Invia un messaggio nel canale.")
@app_commands.describe(testo="Testo da inviare")
@app_commands.check(is_staff)
async def say_command(interaction: discord.Interaction, testo: str) -> None:
    if interaction.channel is None: await send_ephemeral_error(interaction, "❌ Canale non disponibile."); return
    await interaction.channel.send(testo, allowed_mentions=discord.AllowedMentions.none())
    await interaction.response.send_message("Inviato!", ephemeral=True)

@bot.tree.command(name="price", description="Pubblica il prezzo di un prodotto.")
@app_commands.describe(name="Nome del prodotto", price_val="Prezzo", photo="Foto del prodotto")
@app_commands.check(is_staff)
async def price_command(interaction: discord.Interaction, name: str, price_val: str, photo: discord.Attachment) -> None:
    if interaction.channel is None: await send_ephemeral_error(interaction, "❌ Canale non disponibile."); return
    await interaction.channel.send(f"—--:PRICE:—--\n\n📝 NAME: {name}\n\n💰 PRICE: {price_val}\n\n@everyone @here", allowed_mentions=discord.AllowedMentions(everyone=True))
    await interaction.channel.send(photo.url)
    await interaction.response.send_message("Inviato!", ephemeral=True)

@bot.tree.command(name="season", description="Annuncia una nuova stagione.")
@app_commands.describe(name="Nome della stagione", photo="Foto della stagione")
@app_commands.check(is_staff)
async def season_command(interaction: discord.Interaction, name: str, photo: discord.Attachment) -> None:
    if interaction.channel is None: await send_ephemeral_error(interaction, "❌ Canale non disponibile."); return
    await interaction.channel.send(f"—--: NEW SEASON :—--\n\n📝 NAME: {name}\n\n@everyone @here", allowed_mentions=discord.AllowedMentions(everyone=True))
    await interaction.channel.send(photo.url)
    await interaction.response.send_message("Inviato!", ephemeral=True)

@bot.tree.command(name="clearbot", description="Elimina fino al numero indicato di messaggi.")
@app_commands.describe(amount="Numero massimo di messaggi da eliminare (da 1 a 100)")
async def clearbot_command(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100] = 30) -> None:
    try:
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.user, discord.Member) or not interaction.user.guild_permissions.manage_messages:
            await interaction.followup.send("Non hai permessi", ephemeral=True); return
        if not await is_staff(interaction):
            await interaction.followup.send("❌ Solo STAFF.", ephemeral=True); return
        if interaction.channel is None:
            await interaction.followup.send("Non ho permessi qui", ephemeral=True); return
        try: deleted = await interaction.channel.purge(limit=amount)
        except discord.Forbidden:
            await interaction.followup.send("Non ho permessi qui", ephemeral=True); return
        except discord.HTTPException as error:
            txt = str(error).lower()
            if error.code!= 50034 and "14 days" not in txt and "two weeks" not in txt: raise
            deleted = []
            async for msg in interaction.channel.history(limit=amount):
                try: await msg.delete(); deleted.append(msg)
                except: pass
                await asyncio.sleep(1)
        await interaction.followup.send(f"Puliti {len(deleted)} messaggi", ephemeral=True)
    except Exception:
        logger.exception("clearbot error")
        try:
            if interaction.response.is_done(): await interaction.followup.send("Errore durante pulizia.", ephemeral=True)
            else: await interaction.response.send_message("Errore durante pulizia.", ephemeral=True)
        except: pass

# --- NUOVI COMANDI KOIN ---
@bot.tree.command(name="pay", description="Paga un utente in KOINS")
@app_commands.describe(username="Utente a cui inviare", numero="Quantità")
async def pay_command(interaction: discord.Interaction, username: discord.Member, numero: int):
    if numero <= 0: await interaction.response.send_message("Numero non valido.", ephemeral=True); return
    if username.bot: await interaction.response.send_message("Non puoi pagare un bot.", ephemeral=True); return
    if username.id == interaction.user.id: await interaction.response.send_message("Non puoi pagare te stesso.", ephemeral=True); return
    if get_koins(interaction.user.id) < numero:
        await interaction.response.send_message(f"Non hai abbastanza soldi. Hai {get_koins(interaction.user.id)} KOINS.", ephemeral=True); return
    add_koins(interaction.user.id, -numero)
    add_koins(username.id, numero)
    await interaction.response.send_message(f"{interaction.user.mention} ha pagato **{numero} KOINS** a {username.mention} 🪙")

@bot.tree.command(name="portafoglio", description="Vedi il portafoglio")
@app_commands.describe(username="Utente da controllare")
async def portafoglio_command(interaction: discord.Interaction, username: discord.Member = None):
    target = username or interaction.user
    coins = get_koins(target.id)
    await interaction.response.send_message(f"🪙—-: PORTAFOGLIO DI {target.display_name.upper()} :—-🪙\n\nKOINS: \"{coins}\"")

@bot.tree.command(name="kshop", description="Apri lo shop dei ruoli")
async def kshop_command(interaction: discord.Interaction):
    embed = discord.Embed(title="🪙BENVENUTO NELLO SHOP🪙", description="Ruolo **\"ELITE\" 3000 KOINS**\nRuolo **\"GOD\" 5000 KOINS**\nRuolo **\"RICH\" 10000 KOINS**\n\nClicca un bottone sotto per comprare!", color=0xFFD700)
    await interaction.response.send_message(embed=embed, view=ShopView())

@bot.tree.command(name="koinsadd", description="[STAFF] Aggiungi KOINS")
@app_commands.describe(username="Utente", amount="Quantità")
@app_commands.check(is_staff)
async def koinsadd_command(interaction: discord.Interaction, username: discord.Member, amount: int):
    if amount <= 0: await send_ephemeral_error(interaction, "Importo non valido."); return
    new = add_koins(username.id, amount)
    await interaction.response.send_message(f"Aggiunti {amount} KOINS a {username.mention}. Nuovo saldo: {new} 🪙", ephemeral=True)

@bot.tree.command(name="koinsremove", description="[STAFF] Rimuovi KOINS")
@app_commands.describe(username="Utente", amount="Quantità")
@app_commands.check(is_staff)
async def koinsremove_command(interaction: discord.Interaction, username: discord.Member, amount: int):
    if amount <= 0: await send_ephemeral_error(interaction, "Importo non valido."); return
    new = max(0, get_koins(username.id) - amount)
    set_koins(username.id, new)
    await interaction.response.send_message(f"Rimossi {amount} KOINS a {username.mention}. Nuovo saldo: {new} 🪙", ephemeral=True)

@bot.tree.command(name="koinsgiveaway", description="[STAFF] Giveaway KOINS random")
@app_commands.describe(amount="Quantità da regalare")
@app_commands.check(is_staff)
async def koinsgiveaway_command(interaction: discord.Interaction, amount: int):
    if amount <= 0: await send_ephemeral_error(interaction, "Importo non valido."); return
    if interaction.guild is None: await send_ephemeral_error(interaction, "Solo nel server."); return
    members = [m for m in interaction.guild.members if not m.bot]
    if not members: await send_ephemeral_error(interaction, "Nessun membro."); return
    winner = random.choice(members)
    add_koins(winner.id, amount)
    try:
        await winner.send(f"HAI VINTO UN GIVEAWAY DI KROMA, AGGIUNTI \"{amount}\" KOINS AL TUO CONTO!")
        dm_ok = "DM inviato"
    except: dm_ok = "DM chiusi, ma KOINS aggiunti lo stesso"
    await interaction.response.send_message(f"Giveaway di {amount} KOINS vinto da {winner.mention}! {dm_ok} 🪙", ephemeral=True)

# --- NUOVE AGGIUNTE MISSIONI + BONUS ---
@bot.tree.command(name="missioni", description="Vedi le tue missioni giornaliere")
async def missioni_command(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    today = get_today_rome_str()
    day_data = get_user_mission_day(uid, today)
    embed = discord.Embed(title="📅 MISSIONI GIORNALIERE", description=f"Reset a mezzanotte ITA - Oggi: {today}", color=0x00FF00)
    embed.add_field(name=f"{'✅' if day_data['completed']['msg35'] else '❌'} Invia 35 messaggi (30 KOINS)", value=f"{min(day_data['messages'], 35)}/35", inline=False)
    embed.add_field(name=f"{'✅' if day_data['completed']['voice30'] else '❌'} Stai 30 min in vocale (45 KOINS)", value=f"{day_data['voice_seconds']//60}/30 min", inline=False)
    embed.add_field(name=f"{'✅' if day_data['completed']['ping5'] else '❌'} Pinga 5 persone (100 KOINS)", value=f"{min(day_data['pings'], 5)}/5", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="topkoins", description="Classifica più ricchi")
async def topkoins_command(interaction: discord.Interaction):
    if not koin_data:
        await interaction.response.send_message("Nessuno ha KOINS.", ephemeral=True)
        return
    leaderboard = sorted(koin_data.items(), key=lambda x: -x[1])[:10]
    lines = ["🪙 **TOP KOINS** 🪙\n"]
    for rank, (uid, coins) in enumerate(leaderboard, 1):
        lines.append(f"{rank}. <@{uid}> - {coins} KOINS")
    await interaction.response.send_message("\n".join(lines))

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, app_commands.CheckFailure):
        await send_ephemeral_error(interaction, "❌ Solo gli utenti con il ruolo STAFF possono usare questo comando.")
        return
    logger.error("Slash command failed: %s", error, exc_info=(type(error), error, error.__traceback__))
    await send_ephemeral_error(interaction, "❌ Errore durante il comando.")

token = os.getenv("TOKEN")
if not token: raise RuntimeError("Missing TOKEN")
bot.run(token)