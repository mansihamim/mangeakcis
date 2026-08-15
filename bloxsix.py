"""Bot Discord satu file untuk mengecek data publik akun Roblox.

Instalasi:
    python -m pip install -U discord.py aiohttp

Lalu tempel TOKEN BARU dari Discord Developer Portal pada variabel TOKEN.
Jangan gunakan token yang pernah dibagikan ke chat atau tempat publik.
"""

import asyncio
from datetime import datetime
import re
from typing import Any

import aiohttp
import discord
from discord import app_commands


# Sesuai permintaan, token diletakkan langsung di script (bukan .env).
# WAJIB gunakan token baru yang sudah di-reset dari Discord Developer Portal.
TOKEN = "MTQ2ODA4NjE0NTU4NDk4ODIzMg.GDRrh_.w5aksCdblvTFdpZrSWIZswOG1YGXphGc3oT8dc"

ROBLOX_USERNAME_API = "https://users.roblox.com/v1/usernames/users"
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,20}$")


class RobloxBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)
        self.http_session: aiohttp.ClientSession | None = None

    async def setup_hook(self) -> None:
        timeout = aiohttp.ClientTimeout(total=15)
        self.http_session = aiohttp.ClientSession(
            timeout=timeout,
            headers={"User-Agent": "DiscordRobloxLookupBot/1.0"},
        )
        # Sinkronisasi global. Command baru terkadang perlu beberapa menit untuk muncul.
        synced = await self.tree.sync()
        print(f"Berhasil sinkronisasi {len(synced)} slash command global.", flush=True)

    async def close(self) -> None:
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
        await super().close()


bot = RobloxBot()


async def request_json(
    method: str,
    url: str,
    *,
    json_data: dict[str, Any] | None = None,
) -> Any:
    """Memanggil API Roblox dan mengembalikan respons JSON."""
    if bot.http_session is None:
        raise RuntimeError("HTTP session belum siap.")

    async with bot.http_session.request(method, url, json=json_data) as response:
        if response.status == 429:
            raise RuntimeError("API Roblox sedang membatasi permintaan. Coba lagi nanti.")
        if response.status >= 400:
            detail = (await response.text())[:200]
            raise RuntimeError(f"API Roblox merespons HTTP {response.status}: {detail}")
        return await response.json(content_type=None)


async def safe_get(url: str, default: Any) -> Any:
    """GET API tambahan tanpa menggagalkan seluruh hasil jika satu endpoint error."""
    try:
        return await request_json("GET", url)
    except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError):
        return default


async def resolve_public_users(user_ids: list[int]) -> list[dict[str, Any]]:
    """Mengubah ID teman publik menjadi username dan display name."""
    if not user_ids:
        return []
    try:
        result = await request_json(
            "POST",
            "https://users.roblox.com/v1/users",
            json_data={"userIds": user_ids[:20], "excludeBannedUsers": False},
        )
        users_by_id = {int(item["id"]): item for item in result.get("data", [])}
        return [users_by_id[user_id] for user_id in user_ids if user_id in users_by_id]
    except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, KeyError, ValueError):
        return []


def discord_time(iso_time: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
        return f"<t:{int(dt.timestamp())}:F> (<t:{int(dt.timestamp())}:R>)"
    except (TypeError, ValueError):
        return iso_time or "Tidak diketahui"


@bot.event
async def on_ready() -> None:
    print(f"Bot aktif sebagai {bot.user} (ID: {bot.user.id if bot.user else '-'})")


@bot.tree.command(name="ping", description="Cek apakah bot aktif")
async def ping(interaction: discord.Interaction) -> None:
    latency_ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! `{latency_ms} ms`", ephemeral=True)


@bot.tree.command(name="kepoin", description="Kepoin informasi publik sebuah akun Roblox")
@app_commands.describe(username="Username Roblox, bukan display name")
async def kepoin(interaction: discord.Interaction, username: str) -> None:
    username = username.strip()

    if not USERNAME_PATTERN.fullmatch(username):
        await interaction.response.send_message(
            "Username Roblox harus 3–20 karakter dan hanya boleh berisi huruf, angka, atau underscore.",
            ephemeral=True,
        )
        return

    await interaction.response.defer(thinking=True)

    try:
        lookup = await request_json(
            "POST",
            ROBLOX_USERNAME_API,
            json_data={"usernames": [username], "excludeBannedUsers": False},
        )
        matches = lookup.get("data", [])
        if not matches:
            await interaction.followup.send(
                f"Username Roblox **{discord.utils.escape_markdown(username)}** tidak ditemukan."
            )
            return

        match = matches[0]
        user_id = int(match["id"])

        endpoints = {
            "profile": f"https://users.roblox.com/v1/users/{user_id}",
            "friends": f"https://friends.roblox.com/v1/users/{user_id}/friends/count",
            "friend_list": f"https://friends.roblox.com/v1/users/{user_id}/friends",
            "followers": f"https://friends.roblox.com/v1/users/{user_id}/followers/count",
            "following": f"https://friends.roblox.com/v1/users/{user_id}/followings/count",
            "history": (
                f"https://users.roblox.com/v1/users/{user_id}/username-history"
                "?limit=100&sortOrder=Asc"
            ),
            "groups": f"https://groups.roblox.com/v2/users/{user_id}/groups/roles",
            "games": (
                f"https://games.roblox.com/v2/users/{user_id}/games"
                "?accessFilter=Public&limit=50&sortOrder=Asc"
            ),
            "badges": f"https://accountinformation.roblox.com/v1/users/{user_id}/roblox-badges",
            "favorites": (
                f"https://games.roblox.com/v2/users/{user_id}/favorite/games"
                "?accessFilter=Public&limit=50&sortOrder=Desc"
            ),
            "wearing": f"https://avatar.roblox.com/v1/users/{user_id}/currently-wearing",
            "inventory": f"https://inventory.roblox.com/v1/users/{user_id}/can-view-inventory",
            "thumbnail": (
                "https://thumbnails.roblox.com/v1/users/avatar-headshot"
                f"?userIds={user_id}&size=180x180&format=Png&isCircular=false"
            ),
        }

        (
            profile,
            friends,
            friend_list,
            followers,
            following,
            history,
            groups,
            games,
            badges,
            favorites,
            wearing,
            inventory,
            thumbnail,
        ) = await asyncio.gather(
            safe_get(endpoints["profile"], {}),
            safe_get(endpoints["friends"], {"count": "?"}),
            safe_get(endpoints["friend_list"], {"data": []}),
            safe_get(endpoints["followers"], {"count": "?"}),
            safe_get(endpoints["following"], {"count": "?"}),
            safe_get(endpoints["history"], {"data": []}),
            safe_get(endpoints["groups"], {"data": []}),
            safe_get(endpoints["games"], {"data": []}),
            safe_get(endpoints["badges"], []),
            safe_get(endpoints["favorites"], {"data": []}),
            safe_get(endpoints["wearing"], {"assetIds": []}),
            safe_get(endpoints["inventory"], {"canView": False}),
            safe_get(endpoints["thumbnail"], {"data": []}),
        )

        # Endpoint daftar teman memberikan ID, lalu display name diselesaikan
        # melalui endpoint batch users. Hanya 5 agar hasil tetap rapi.
        friend_ids = [int(item["id"]) for item in friend_list.get("data", []) if item.get("id")]
        friend_users = await resolve_public_users(friend_ids[:5])

        actual_username = profile.get("name", match.get("name", username))
        display_name = profile.get("displayName", match.get("displayName", "-"))
        description = (profile.get("description") or "Tidak ada bio.").strip()
        if len(description) > 500:
            description = description[:497] + "..."

        previous_names = [item.get("name", "?") for item in history.get("data", [])]
        previous_text = ", ".join(previous_names) if previous_names else "Tidak ada yang ditampilkan API"
        if len(previous_text) > 900:
            previous_text = previous_text[:897] + "..."

        group_entries = groups.get("data", [])
        group_preview = []
        for entry in group_entries[:8]:
            group = entry.get("group", {})
            role = entry.get("role", {})
            group_preview.append(f"• {group.get('name', '?')} — {role.get('name', 'Member')}")
        group_text = "\n".join(group_preview) or "Tidak ada grup publik"
        if len(group_entries) > 8:
            group_text += f"\n• …dan {len(group_entries) - 8} grup lainnya"

        game_entries = games.get("data", [])
        total_visits = sum(int(game.get("placeVisits", 0) or 0) for game in game_entries)
        badge_names = [badge.get("name", "?") for badge in badges]
        badge_text = ", ".join(badge_names) if badge_names else "Tidak ada"
        if len(badge_text) > 500:
            badge_text = badge_text[:497] + "..."

        friend_lines = []
        for number, friend in enumerate(friend_users[:5], start=1):
            friend_display = discord.utils.escape_markdown(friend.get("displayName") or "Tanpa nama")
            friend_lines.append(f"`{number}.` **{friend_display}**")
        friend_text = "\n".join(friend_lines) or "Nama teman tidak tersedia."

        favorite_entries = favorites.get("data", [])
        favorite_lines = [
            f"• {discord.utils.escape_markdown(game.get('name', '?'))}"
            for game in favorite_entries[:8]
        ]
        favorite_text = "\n".join(favorite_lines) or "Tidak ada favorite game publik."

        verified_group_count = sum(
            1 for entry in group_entries if entry.get("group", {}).get("hasVerifiedBadge")
        )
        special_roles = []
        for entry in group_entries:
            role = entry.get("role", {})
            group = entry.get("group", {})
            if int(role.get("rank", 0) or 0) > 1:
                special_roles.append(f"{group.get('name', '?')}: {role.get('name', '?')}")

        extra_lines = [
            f"• Inventory: **{'publik' if inventory.get('canView') else 'privat'}**",
            f"• Item avatar yang sedang dipakai: **{len(wearing.get('assetIds', []))}**",
            f"• Bergabung dengan grup verified: **{verified_group_count}**",
        ]
        if special_roles:
            extra_lines.append(
                "• Role khusus: " + discord.utils.escape_markdown(", ".join(special_roles[:4]))
            )
        extra_text = "\n".join(extra_lines)

        profile_url = f"https://www.roblox.com/users/{user_id}/profile"
        embed = discord.Embed(
            title=f"{display_name} (@{actual_username})",
            url=profile_url,
            description=description,
            color=discord.Color.from_rgb(0, 162, 255),
        )
        embed.add_field(name="User ID", value=f"`{user_id}`", inline=True)
        embed.add_field(
            name="Status",
            value=(
                ("Diblokir" if profile.get("isBanned") else "Aktif")
                + (" • Verified" if profile.get("hasVerifiedBadge") else "")
            ),
            inline=True,
        )
        embed.add_field(
            name="Sosial",
            value=(
                f"Teman: **{friends.get('count', '?')}**\n"
                f"Followers: **{followers.get('count', '?')}**\n"
                f"Following: **{following.get('count', '?')}**"
            ),
            inline=True,
        )
        embed.add_field(
            name=f"Teman ({min(len(friend_users), 5)} dari {friends.get('count', '?')})",
            value=friend_text,
            inline=False,
        )
        embed.add_field(
            name="Akun dibuat",
            value=discord_time(profile.get("created", "")),
            inline=False,
        )
        embed.add_field(name="Username sebelumnya", value=previous_text, inline=False)
        embed.add_field(
            name=f"Grup publik ({len(group_entries)})",
            value=group_text,
            inline=False,
        )
        embed.add_field(
            name="Experience publik",
            value=f"**{len(game_entries)}** experience • **{total_visits:,}** total kunjungan",
            inline=False,
        )
        embed.add_field(name="Badge Roblox", value=badge_text, inline=False)
        embed.add_field(
            name=f"Favorite game publik ({len(favorite_entries)})",
            value=favorite_text,
            inline=False,
        )
        embed.add_field(name="Temuan tambahan", value=extra_text, inline=False)

        thumbnail_data = thumbnail.get("data", [])
        if thumbnail_data and thumbnail_data[0].get("imageUrl"):
            embed.set_thumbnail(url=thumbnail_data[0]["imageUrl"])

        await interaction.followup.send(embed=embed)

    except asyncio.TimeoutError:
        await interaction.followup.send("API Roblox terlalu lama merespons. Coba lagi nanti.")
    except aiohttp.ClientError as exc:
        await interaction.followup.send(f"Gagal terhubung ke API Roblox: `{exc}`")
    except RuntimeError as exc:
        await interaction.followup.send(str(exc))
    except Exception as exc:
        print(f"Unexpected error: {type(exc).__name__}: {exc}")
        await interaction.followup.send("Terjadi error internal saat memproses permintaan.")


if __name__ == "__main__":
    if TOKEN == "PASTE_NEW_DISCORD_BOT_TOKEN_HERE":
        raise RuntimeError(
            "Isi variabel TOKEN dengan token bot BARU dari Discord Developer Portal."
        )
    bot.run(TOKEN)
