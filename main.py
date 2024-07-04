from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import pathlib
import random
import typing

import pytz
from dotenv import load_dotenv

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext import tasks

load_dotenv()
discord.utils.setup_logging()
logger = logging.getLogger()

# Set to True to sync the commands tree with the Discord API
SYNCING_TREE = False

TIMEZONE_FILE = pathlib.Path(__file__).absolute().parent / "data" / "timezones.json"
if not TIMEZONE_FILE.exists():  # Create the file if it doesn't exist
    TIMEZONE_FILE.parent.mkdir(exist_ok=True)
    with TIMEZONE_FILE.open("w") as f_:
        json.dump({}, f_)


class Timezone(commands.Cog):
    def __init__(self, bot: Bot):
        """
        Cog to manage timezones.

        :param bot: The bot instance.
        """
        self.bot = bot
        self.timezone_file_lock = asyncio.Lock()
        self.colour_generator = self._colour_generator()
        self.time_message_cache: dict[int, discord.Message] = {}

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self.populate_time_message_cache()
        self.time_message_updater_task.start()

    async def cog_load(self) -> None:
        if self.bot.is_ready():
            await self.on_ready()

    @tasks.loop(seconds=11.75, reconnect=False)
    async def time_message_updater_task(self) -> None:
        """
        Task to update the time message.
        """
        for guild_id in list(self.time_message_cache.keys()):
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                await self.remove_time_message(guild_id)
                continue

            try:
                time_message = self.time_message_cache[guild_id]
                if time_message.channel.permissions_for(guild.me).send_messages:
                    embed = await self.create_time_message_embed(guild)
                    await time_message.edit(embed=embed)
            except Exception:
                logger.exception("Failed to update time message for guild %d.", guild_id)

    async def save_timezone(self, guild_id: int, user_id: int, timezone: str) -> None:
        """
        Save the timezone for a user.

        :param guild_id: The guild ID.
        :param user_id: The user ID.
        :param timezone: The timezone.
        """
        async with self.timezone_file_lock:
            with TIMEZONE_FILE.open("r") as f:
                data = json.load(f)
            if str(guild_id) not in data:
                data[str(guild_id)] = {
                    "timezones": {},
                }
            data[str(guild_id)]["timezones"][str(user_id)] = timezone
            with TIMEZONE_FILE.open("w") as f:
                json.dump(data, f)

    async def get_timezone(
        self, guild_id: int, user_id: int | None = None
    ) -> pytz.BaseTzInfo | dict[int, pytz.BaseTzInfo] | None:
        """
        Get the timezone for a user.

        :param guild_id: The guild ID.
        :param user_id: The user ID. If not provided, the timezone for everyone in the guild is returned.
        :return: The timezone if previously set, else None.
        """
        async with self.timezone_file_lock:
            with TIMEZONE_FILE.open("r") as f:
                data = json.load(f)

        if user_id is None:
            if str(guild_id) not in data:
                return {}

            timezones = {}
            for user_id, timezone in data[str(guild_id)]["timezones"].items():
                try:
                    timezones[int(user_id)] = pytz.timezone(timezone)
                except pytz.UnknownTimeZoneError:
                    logger.warning("Invalid timezone %s for user %d.", timezone, user_id)
                    del data[str(guild_id)]["timezones"][str(user_id)]
                    async with self.timezone_file_lock:
                        with TIMEZONE_FILE.open("w") as f:
                            json.dump(data, f)
            return timezones

        if str(guild_id) not in data:
            return None

        user_timezone = data[str(guild_id)]["timezones"].get(str(user_id), None)
        if user_timezone:
            try:
                return pytz.timezone(user_timezone)
            except pytz.UnknownTimeZoneError:  # Somehow the timezone is invalid
                logger.warning("Invalid timezone %s for user %d.", user_timezone, user_id)
                del data[str(guild_id)]["timezones"][str(user_id)]
                async with self.timezone_file_lock:
                    with TIMEZONE_FILE.open("w") as f:
                        json.dump(data, f)
        return None

    async def remove_timezone(self, guild_id: int, user_id: int) -> None:
        """
        Remove the timezone for a user.

        :param guild_id: The guild ID.
        :param user_id: The user ID.
        """
        async with self.timezone_file_lock:
            with TIMEZONE_FILE.open("r") as f:
                data = json.load(f)
            if str(guild_id) in data and str(user_id) in data[str(guild_id)]["timezones"]:
                del data[str(guild_id)]["timezones"][str(user_id)]
                with TIMEZONE_FILE.open("w") as f:
                    json.dump(data, f)

    async def populate_time_message_cache(self) -> None:
        """
        Populate the time message cache.
        """
        async with self.timezone_file_lock:
            with TIMEZONE_FILE.open("r") as f:
                data = json.load(f)

        for guild_id, guild_data in data.items():
            if "time_message" in guild_data:
                channel_id, message_id = guild_data["time_message"]
                try:
                    channel = self.bot.get_channel(channel_id)
                    if channel is None:
                        channel = await self.bot.fetch_channel(channel_id)

                    message = await channel.fetch_message(message_id)
                    self.time_message_cache[int(guild_id)] = message
                except Exception:
                    logger.warning("Time message not found for guild %s.", guild_id, exc_info=True)
                    await self.remove_time_message(int(guild_id))

    async def get_time_message(self, guild_id: int) -> tuple[int, int] | None:
        """
        Get the time message channel and the message ID.
        :param guild_id: The guild ID.
        :return: The time message channel and the message ID if exists, else None.
        """
        async with self.timezone_file_lock:
            with TIMEZONE_FILE.open("r") as f:
                data = json.load(f)
        return data.get(str(guild_id), {}).get("time_message", None)

    async def save_time_message(self, guild_id: int, channel_id: int, message_id: int) -> None:
        """
        Save the time message channel and the message ID.

        :param guild_id: The guild ID.
        :param channel_id: The channel ID.
        :param message_id: The message ID.
        """
        async with self.timezone_file_lock:
            with TIMEZONE_FILE.open("r") as f:
                data = json.load(f)
            if str(guild_id) not in data:
                data[str(guild_id)] = {
                    "timezones": {},
                }
            data[str(guild_id)]["time_message"] = (channel_id, message_id)
            with TIMEZONE_FILE.open("w") as f:
                json.dump(data, f)

    async def remove_time_message(self, guild_id: int) -> None:
        """
        Remove the time message channel and the message ID.

        :param guild_id: The guild ID.
        """
        async with self.timezone_file_lock:
            with TIMEZONE_FILE.open("r") as f:
                data = json.load(f)
            if str(guild_id) in data and "time_message" in data[str(guild_id)]:
                del data[str(guild_id)]["time_message"]
                with TIMEZONE_FILE.open("w") as f:
                    json.dump(data, f)
        self.time_message_cache.pop(guild_id, None)

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    async def timezone_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """
        Autocomplete function for timezones.

        :param interaction: The interaction that triggered the autocomplete.
        :param current: The current input.
        :return: A list of timezone choices.
        """
        current = current.casefold().strip()
        all_timezones = sorted([timezone for timezone in pytz.common_timezones if current in timezone.casefold()])
        return [app_commands.Choice(name=timezone, value=timezone) for timezone in all_timezones[:25]]

    @commands.guild_only()
    @commands.hybrid_group()
    async def timezone(self, ctx: commands.Context) -> None:
        """
        Manage your timezone.
        """
        await ctx.reply(
            f"Run `{ctx.prefix}{self.timezone_set.qualified_name}` to set your timezone.",
            ephemeral=True,
        )

    @commands.guild_only()
    @timezone.command(name="set")
    @app_commands.autocomplete(timezone=timezone_autocomplete)
    async def timezone_set(self, ctx: commands.Context, timezone: str, *, user: discord.User | None = None) -> None:
        """
        Set your timezone.

        :param timezone: Your current timezone.
        :param user: The user to set the timezone. (Only available to staffs)
        """
        if user is None:
            user = ctx.author
        else:
            if not ctx.author.guild_permissions.manage_guild and ctx.author != user:
                await ctx.reply(
                    "You do not have permission to set the timezone for others.",
                    ephemeral=True,
                )
                return

        timezone = timezone.casefold().strip()
        try:
            tz = pytz.timezone(timezone)
        except pytz.UnknownTimeZoneError:
            await ctx.reply(
                "Invalid timezone.\nPlease provide a valid TZ identifier from "
                "[here](<https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List>).",
                ephemeral=True,
            )
            return

        logger.info("Setting timezone for %s (%d) to %s.", user, user.id, timezone)
        await self.save_timezone(ctx.guild.id, user.id, timezone)

        time_now_string = datetime.datetime.now(tz).strftime("%b %d, %Y %H:%M:%S %Z").strip()
        await ctx.reply(
            f"{user.mention}'s timezone is set to {tz.zone}. The current date and time is {time_now_string}.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.guild_only()
    @timezone.command(name="current")
    async def timezone_current(self, ctx: commands.Context) -> None:
        """
        Check your current timezone.
        """
        tz = await self.get_timezone(ctx.guild.id, ctx.author.id)
        if tz is None:
            await ctx.reply("You have not set your timezone yet.", ephemeral=True)
            return

        time_now_string = datetime.datetime.now(tz).strftime("%b %d, %Y %H:%M:%S %Z").strip()
        await ctx.reply(f"Your timezone is set to {tz.zone}. The current date and time is {time_now_string}.")

    @commands.guild_only()
    @timezone.command(name="clear")
    async def timezone_clear(self, ctx: commands.Context, *, user: discord.User | None = None) -> None:
        """
        Clear your timezone.

        :param user: The user to clear. (Only available to staffs)
        """
        if user is None:
            user = ctx.author
        else:
            if not ctx.author.guild_permissions.manage_guild and ctx.author != user:
                await ctx.reply(
                    "You do not have permission to clear the timezone for others.",
                    ephemeral=True,
                )
                return

        logger.info("Clearing timezone for %s (%d).", user, ctx.author.id)
        await self.remove_timezone(ctx.guild.id, user.id)
        await ctx.reply(
            f"{user.mention}'s timezone has been cleared.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.guild_only()
    @commands.hybrid_command()
    @app_commands.autocomplete(timezone=timezone_autocomplete)
    async def timein(self, ctx: commands.Context, timezone: str) -> None:
        """
        Get the current time in a timezone.
        """
        timezone = timezone.casefold().strip()
        try:
            tz = pytz.timezone(timezone)
        except pytz.UnknownTimeZoneError:
            await ctx.reply(
                "Invalid timezone.\nPlease provide a valid TZ identifier from "
                "[here](<https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List>).",
                ephemeral=True,
            )
            return

        time_now_string = datetime.datetime.now(tz).strftime("%b %d, %Y %H:%M:%S %Z").strip()
        await ctx.reply(f"The current date and time in {tz.zone} is {time_now_string}.")

    @commands.guild_only()
    @commands.hybrid_command()
    async def timeat(self, ctx: commands.Context, user: discord.Member) -> None:
        """
        Get the current time of a user.

        :param user: The user to get the time.
        """
        tz = await self.get_timezone(ctx.guild.id, user.id)
        if tz is None:
            await ctx.reply(f"{user} has not set their timezone yet.", ephemeral=True)
            return

        time_now_string = datetime.datetime.now(tz).strftime("%b %d, %Y %H:%M:%S %Z").strip()
        await ctx.reply(f"The current date and time for {user} is {time_now_string}.")

    @commands.guild_only()
    @commands.hybrid_command()
    async def time(self, ctx: commands.Context) -> None:
        """
        Get everyone's time in the server.
        """
        embed = await self.create_time_message_embed(ctx.guild, show_last_updated=False)
        await ctx.reply(embed=embed)

    @staticmethod
    def _colour_generator() -> typing.Generator[tuple[int, int, int], None, None]:
        """
        Generate a smooth random colour by gradually transitioning to a randomly chosen target colour.
        """

        # Set initial color
        current_color = (
            random.uniform(0, 1),
            random.uniform(0, 1),
            random.uniform(0, 1),
        )

        step_count = 10

        while True:
            step = 0

            # Randomly choose a new target color
            target_color = (
                random.uniform(0, 1),
                random.uniform(0, 1),
                random.uniform(0, 1),
            )

            # Transition to the target color gradually
            for i in range(step_count):
                step += 1
                # Interpolate between the current color and the target color
                interpolated_color = tuple(
                    (c1 + (c2 - c1) * (step / step_count)) for c1, c2 in zip(current_color, target_color)
                )
                # Yield the interpolated color
                yield tuple(int(max(0, min(255, c * 255))) for c in interpolated_color)

            # Update the current color to the target color
            current_color = target_color

    def get_colour(self) -> discord.Colour:
        return discord.Colour.from_rgb(*next(self.colour_generator))

    async def create_time_message_embed(self, guild: discord.Guild, *, show_last_updated: bool = True) -> discord.Embed:
        """
        Create the time message for a guild.

        :param guild: The guild for the time message.
        :param show_last_updated: Whether to show the last updated time.
        :return: An embed containing the time message.
        """
        timezones = await self.get_timezone(guild.id)

        time_now = datetime.datetime.now()
        time_text = ""

        if not timezones:
            time_text += "No one has set their timezone."
        else:
            users_by_timezones: dict[datetime.datetime, list[tuple[int, pytz.BaseTzInfo]]] = {}
            for user_id, tz in timezones.items():
                naive_time = time_now.astimezone(tz).replace(tzinfo=None)
                if naive_time not in users_by_timezones:
                    users_by_timezones[naive_time] = [(user_id, tz)]
                else:
                    users_by_timezones[naive_time].append((user_id, tz))

            users_by_timezones_sorted = sorted(
                users_by_timezones.items(),
                key=lambda x: (x[0], len(x[1])),
            )
            for naive_time, user_time in users_by_timezones_sorted:
                time_text += f"**{naive_time.strftime('%b %d, %Y %I:%M:%S %p')}:**\n"
                time_text += " ".join(f"<@{user_id}>" for user_id, tz in user_time) + "\n\n"

        time_text = time_text.rstrip()

        if show_last_updated:
            time_text += f"\n\n*Last Updated: <t:{int(time_now.timestamp())}:f>*"

        embed = discord.Embed(
            title="What's the time?",
            description=time_text.strip(),
            colour=self.get_colour(),
        )
        return embed

    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    @commands.hybrid_group(name="timemessage")
    async def time_message(self, ctx: commands.Context) -> None:
        """
        Manage the persistent time message.
        """
        await ctx.reply(
            f"Run `{ctx.prefix}{self.time_message_send.qualified_name}` to send a new persistent "
            "time message (will invalidate the old one if exists).",
            ephemeral=True,
        )

    # noinspection PyIncorrectDocstring
    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    @time_message.command(name="send")
    async def time_message_send(self, ctx: commands.Context, *, channel: discord.TextChannel | None = None) -> None:
        """
        Send a new persistent time message.

        :param channel: The channel to send the message in. If not provided, the message is sent in the current channel.
        """
        if channel is None:
            channel = ctx.channel

        if ctx.guild.id in self.time_message_cache:
            try:
                await self.time_message_cache[ctx.guild.id].delete()
            except Exception:
                logger.warning(
                    "Failed to delete time message for guild %d.",
                    ctx.guild.id,
                    exc_info=True,
                )

        embed = await self.create_time_message_embed(ctx.guild)
        try:
            message = await channel.send(embed=embed)
        except discord.HTTPException:
            await ctx.reply("Failed to send the persistent time message.", ephemeral=True)
            return

        await self.save_time_message(ctx.guild.id, channel.id, message.id)
        self.time_message_cache[ctx.guild.id] = message
        await ctx.reply(f"Persistent time message sent in {channel.mention}.")

        if channel.permissions_for(ctx.guild.me).manage_messages:
            await message.pin()

    @commands.has_guild_permissions(manage_guild=True)
    @commands.guild_only()
    @time_message.command(name="clear")
    async def time_message_clear(self, ctx: commands.Context) -> None:
        """
        Clear the persistent time message.
        """
        if ctx.guild.id not in self.time_message_cache:
            await ctx.reply("No persistent time message exists.", ephemeral=True)
            return

        try:
            await self.time_message_cache[ctx.guild.id].delete()
        except Exception:
            logger.warning(
                "Failed to delete time message for guild %d.",
                ctx.guild.id,
                exc_info=True,
            )

        await self.remove_time_message(ctx.guild.id)
        await ctx.reply("Persistent time message cleared.")


class Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True

        super().__init__([], intents=intents)  # No prefix

    async def setup_hook(self) -> None:
        await self.add_cog(Timezone(self))
        if SYNCING_TREE:
            await self.tree.sync()

    async def on_ready(self):
        logging.info("Logged in as %s (%d).", self.user, self.user.id)


_bot = Bot()
_bot.run(os.environ["DISCORD_BOT_TOKEN"])
