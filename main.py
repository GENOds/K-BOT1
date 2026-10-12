"""K~BOT Discord bot.

Required Discord Developer Portal settings:
enable the Server Members, Presence, and Message Content privileged intents.
Set the bot token in Replit Secrets as TOKEN.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("kbot")

DATA_DIR = Path(__file__).resolve().parent
FLAG_WINS_PATH = DATA_DIR / "flag_wins.json"
MESSAGES_PATH = DATA_DIR / "messages.json"
UTC = timezone.utc

FLAGS = [
    ("🇮🇹", "italia"),
    ("🇯🇵", "giappone"),
    ("🇺🇸", "usa"),
    ("🇫🇷", "francia"),
    ("🇪🇸", "spagna"),
    ("🇩🇪", "germania"),
    ("🇬🇧", "inghilterra"),
    ("🇧🇷", "brasile"),
]


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default.copy()
    try:
        with path.open("r", encoding="utf-8") as file:
            value = json.load(file)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{path.name} is not valid JSON; refusing to overwrite it.") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} must contain a JSON object.")
    return value


def save_json(path: Path, data: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")
    temporary_path.replace(path)


flag_wins: dict[str, int] = {
    str(user_id): int(wins)
    for user_id, wins in load_json(FLAG_WINS_PATH, {}).items()
}
messages: dict[str, list[str]] = {}
for user_id, timestamps in load_json(MESSAGES_PATH, {}).items():
    if isinstance(timestamps, list):
        messages[str(user_id)] = [str(timestamp) for timestamp in timestamps]

if not FLAG_WINS_PATH.exists():
    save_json(FLAG_WINS_PATH, flag_wins)
if not MESSAGES_PATH.exists():
    save_json(MESSAGES_PATH, messages)

current_flag: str | None = None
time_online: dict[tuple[int, int], datetime] = {}

intents = discord.Intents.all()
bot = commands.Bot(
    command_prefix="?",
    intents=intents,
    help_command=None,
    description="K~BOT - KROMA® community bot",
)


def parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


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
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"


async def is_staff(interaction: discord.Interaction) -> bool:
    member = interaction.user
    return isinstance(member, discord.Member) and any(
        role.name == "STAFF" for role in member.roles
    )


async def send_ephemeral_error(
    interaction: discord.Interaction, content: str
) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)


@bot.event
async def on_ready() -> None:
    if bot.user is None:
        return

    for guild in bot.guilds:
        for member in guild.members:
            if member.joined_at is not None:
                time_online[(guild.id, member.id)] = member.joined_at.astimezone(UTC)

    synced_commands = await bot.tree.sync()
    logger.info("Logged in as %s; synced %d slash commands.", bot.user, len(synced_commands))


@bot.event
async def on_member_join(member: discord.Member) -> None:
    time_online[(member.guild.id, member.id)] = datetime.now(UTC)


@bot.event
async def on_message(message: discord.Message) -> None:
    global current_flag

    if message.author.bot:
        return

    now = datetime.now(UTC)
    user_id = str(message.author.id)
    messages[user_id] = recent_message_times(user_id, now)
    messages[user_id].append(now.isoformat())
    save_json(MESSAGES_PATH, messages)

    if current_flag is not None and message.content == current_flag:
        flag_wins[user_id] = flag_wins.get(user_id, 0) + 1
        save_json(FLAG_WINS_PATH, flag_wins)
        await message.channel.send(
            f"🏆 {message.author.mention} ha indovinato, "
            f"🏆 vittorie totali= {flag_wins[user_id]} 🏆"
        )
        current_flag = None

    await bot.process_commands(message)


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
    if leaderboard:
        lines.extend(
            f"{rank}. <@{user_id}> - {wins} wins"
            for rank, (user_id, wins) in enumerate(leaderboard, start=1)
        )
    else:
        lines.append("Nessuna vittoria ancora.")
    await ctx.send("\n".join(lines))


@bot.command(name="descrizione")
async def descrizione_command(ctx: commands.Context) -> None:
    description = (
        "KROMA® - BEYOND CLOTHING\n\n"
        "Non è solo streetwear, è attitudine.\n\n"
        "Ogni drop è limitato, ogni pezzo è studiato nei minimi dettagli.\n\n"
        "Entra nella community, resta attivo e non perderti il prossimo.\n\n"
        "— KROMA STAFF —"
    )
    try:
        await ctx.author.send(description)
    except discord.Forbidden:
        await ctx.send("❌ Non riesco a mandarti DM, aprili!")
        return
    await ctx.send("📩 Ti ho mandato la descrizione in DM!")


@bot.command(name="msg")
async def msg_command(ctx: commands.Context) -> None:
    now = datetime.now(UTC)
    user_id = str(ctx.author.id)
    messages[user_id] = recent_message_times(user_id, now)
    save_json(MESSAGES_PATH, messages)
    count = len(messages[user_id])
    await ctx.send(
        f"📩 {ctx.author.mention} hai scritto {count} messaggi negli ultimi 7 giorni"
    )


@bot.command(name="servertime")
async def servertime_command(ctx: commands.Context) -> None:
    if ctx.guild is None:
        await ctx.send("❌ Questo comando è disponibile solo nel server.")
        return

    key = (ctx.guild.id, ctx.author.id)
    joined_at = time_online.get(key)
    if joined_at is None:
        try:
            member = await ctx.guild.fetch_member(ctx.author.id)
        except discord.NotFound:
            await ctx.send("❌ Non riesco a trovare la data di ingresso.")
            return
        joined_at = member.joined_at
        if joined_at is None:
            await ctx.send("❌ Non riesco a trovare la data di ingresso.")
            return
        joined_at = joined_at.astimezone(UTC)
        time_online[key] = joined_at

    await ctx.send(
        f"⏱️ {ctx.author.mention} sei stato online per "
        f"{format_duration(joined_at)} da quando sei entrato"
    )


@bot.command(name="timeleaderboard")
async def timeleaderboard_command(ctx: commands.Context) -> None:
    if ctx.guild is None:
        await ctx.send("❌ Questo comando è disponibile solo nel server.")
        return

    entries = [
        (user_id, joined_at)
        for (guild_id, user_id), joined_at in time_online.items()
        if guild_id == ctx.guild.id
    ]
    entries.sort(key=lambda item: (item[1], item[0]))
    lines = ["⏰ TIME LEADERBOARD"]
    lines.extend(
        f"{rank}. <@{user_id}> - {format_duration(joined_at)}"
        for rank, (user_id, joined_at) in enumerate(entries[:10], start=1)
    )
    if not entries:
        lines.append("Nessun dato disponibile.")
    await ctx.send("\n".join(lines))


@bot.tree.command(name="release", description="Pubblica una nuova release.")
@app_commands.describe(
    name="Nome della release",
    category="Categoria",
    tag="Tag",
    photo="Foto della release",
)
@app_commands.check(is_staff)
async def release_command(
    interaction: discord.Interaction,
    name: str,
    category: str,
    tag: str,
    photo: discord.Attachment,
) -> None:
    if interaction.channel is None:
        await send_ephemeral_error(interaction, "❌ Canale non disponibile.")
        return

    await interaction.channel.send(
        f"—--:RELEASE:—--\n\n📝 NAME: {name}\n\n👕 CATEGORY: {category}\n\n🏷️ TAG: {tag}",
        allowed_mentions=discord.AllowedMentions.none(),
    )
    await interaction.channel.send(photo.url)
    await interaction.response.send_message("Inviato!", ephemeral=True)


@bot.tree.command(name="stafflist", description="Mostra tutti i membri dello STAFF.")
@app_commands.check(is_staff)
async def stafflist_command(interaction: discord.Interaction) -> None:
    if interaction.guild is None:
        await send_ephemeral_error(interaction, "❌ Questo comando è disponibile solo nel server.")
        return

    staff_members = []
    async for member in interaction.guild.fetch_members(limit=None):
        if any(role.name == "STAFF" for role in member.roles):
            staff_members.append(member)

    lines = [
        f"👑 {member.mention} - STAFF"
        for member in sorted(staff_members, key=lambda item: item.display_name.casefold())
    ]
    if not lines:
        lines = ["Nessun membro STAFF trovato."]
    messages_to_send: list[str] = []
    current_lines = ["—--:STAFFLIST:—--", ""]
    for line in lines:
        if len("\n".join(current_lines + [line])) > 1900:
            messages_to_send.append("\n".join(current_lines))
            current_lines = []
        current_lines.append(line)
    if current_lines:
        messages_to_send.append("\n".join(current_lines))

    for content in messages_to_send:
        await interaction.channel.send(
            content,
            allowed_mentions=discord.AllowedMentions.none(),
        )
    await interaction.response.send_message("Inviato!", ephemeral=True)


@bot.tree.command(name="say", description="Invia un messaggio nel canale.")
@app_commands.describe(testo="Testo da inviare")
@app_commands.check(is_staff)
async def say_command(interaction: discord.Interaction, testo: str) -> None:
    if interaction.channel is None:
        await send_ephemeral_error(interaction, "❌ Canale non disponibile.")
        return
    await interaction.channel.send(
        testo,
        allowed_mentions=discord.AllowedMentions.none(),
    )
    await interaction.response.send_message("Inviato!", ephemeral=True)


@bot.tree.command(name="price", description="Pubblica il prezzo di un prodotto.")
@app_commands.describe(name="Nome del prodotto", price_val="Prezzo", photo="Foto del prodotto")
@app_commands.check(is_staff)
async def price_command(
    interaction: discord.Interaction,
    name: str,
    price_val: str,
    photo: discord.Attachment,
) -> None:
    if interaction.channel is None:
        await send_ephemeral_error(interaction, "❌ Canale non disponibile.")
        return
    await interaction.channel.send(
        f"—--:PRICE:—--\n\n📝 NAME: {name}\n\n💰 PRICE: {price_val}\n\n@everyone @here",
        allowed_mentions=discord.AllowedMentions(everyone=True),
    )
    await interaction.channel.send(photo.url)
    await interaction.response.send_message("Inviato!", ephemeral=True)


@bot.tree.command(name="season", description="Annuncia una nuova stagione.")
@app_commands.describe(name="Nome della stagione", photo="Foto della stagione")
@app_commands.check(is_staff)
async def season_command(
    interaction: discord.Interaction,
    name: str,
    photo: discord.Attachment,
) -> None:
    if interaction.channel is None:
        await send_ephemeral_error(interaction, "❌ Canale non disponibile.")
        return
    await interaction.channel.send(
        f"—--: NEW SEASON :—--\n\n📝 NAME: {name}\n\n@everyone @here",
        allowed_mentions=discord.AllowedMentions(everyone=True),
    )
    await interaction.channel.send(photo.url)
    await interaction.response.send_message("Inviato!", ephemeral=True)


@bot.tree.command(name="clearbot", description="Elimina fino al numero indicato di messaggi.")
@app_commands.describe(amount="Numero massimo di messaggi da eliminare (da 1 a 100)")
async def clearbot_command(
    interaction: discord.Interaction,
    amount: app_commands.Range[int, 1, 100] = 30,
) -> None:
    try:
        await interaction.response.defer(ephemeral=True)

        if (
            not isinstance(interaction.user, discord.Member)
            or not interaction.user.guild_permissions.manage_messages
        ):
            await interaction.followup.send("Non hai permessi", ephemeral=True)
            return

        if not await is_staff(interaction):
            await interaction.followup.send(
                "❌ Solo gli utenti con il ruolo STAFF possono usare questo comando.",
                ephemeral=True,
            )
            return

        if interaction.channel is None:
            await interaction.followup.send(
                "Non ho permessi per cancellare qui",
                ephemeral=True,
            )
            return

        try:
            deleted = await interaction.channel.purge(limit=amount)
        except discord.Forbidden:
            await interaction.followup.send(
                "Non ho permessi per cancellare qui",
                ephemeral=True,
            )
            return
        except discord.HTTPException as error:
            error_text = str(error).lower()
            is_fourteen_day_bulk_delete_error = (
                error.code == 50034
                or "14 days" in error_text
                or "two weeks" in error_text
            )
            if not is_fourteen_day_bulk_delete_error:
                raise

            logger.warning(
                "Bulk purge hit Discord's 14-day limit; deleting messages individually.",
                exc_info=True,
            )
            deleted = []
            async for message in interaction.channel.history(limit=amount):
                try:
                    await message.delete()
                    deleted.append(message)
                except discord.NotFound:
                    continue
                await asyncio.sleep(1)

        await interaction.followup.send(
            f"Puliti {len(deleted)} messaggi",
            ephemeral=True,
        )
    except discord.Forbidden:
        logger.exception("Discord denied the /clearbot operation.")
        try:
            await interaction.followup.send(
                "Non ho permessi per cancellare qui",
                ephemeral=True,
            )
        except Exception:
            logger.exception("Could not send the /clearbot permission error.")
    except Exception:
        logger.exception("Unexpected error while running /clearbot.")
        try:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Errore durante la pulizia dei messaggi.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "Errore durante la pulizia dei messaggi.",
                    ephemeral=True,
                )
        except Exception:
            logger.exception("Could not send the /clearbot error response.")


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    if isinstance(error, app_commands.CheckFailure):
        await send_ephemeral_error(
            interaction, "❌ Solo gli utenti con il ruolo STAFF possono usare questo comando."
        )
        return

    logger.error(
        "Slash command failed: %s",
        error,
        exc_info=(type(error), error, error.__traceback__),
    )
    await send_ephemeral_error(interaction, "❌ Si è verificato un errore durante il comando.")


token = os.getenv("TOKEN")
if not token:
    raise RuntimeError("Missing Discord bot token. Add it as the Replit secret TOKEN.")

keep_alive()
bot.run(token)
