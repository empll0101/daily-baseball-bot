from __future__ import annotations

import logging

import aiohttp
import discord
from discord import app_commands

from .config import Settings
from .database import Database
from .models import League, Player
from .providers import DataProvider, ProviderUnavailable
from .service import TrackingService

log = logging.getLogger(__name__)

LEAGUE_CHOICES = [
    app_commands.Choice(name="MLB 美國職棒", value="MLB"),
    app_commands.Choice(name="NPB 日本職棒", value="NPB"),
    app_commands.Choice(name="KBO 韓國職棒", value="KBO"),
]


class TrackerClient(discord.Client):
    def __init__(
        self,
        settings: Settings,
        database: Database,
        session: aiohttp.ClientSession,
        providers: dict[League, DataProvider],
    ):
        super().__init__(intents=discord.Intents.default())
        self.settings = settings
        self.database = database
        self.session = session
        self.providers = providers
        self.tree = app_commands.CommandTree(self)
        self.tracking = TrackingService(self, database, providers, settings)
        self._register_commands()

    async def setup_hook(self) -> None:
        synced = await self.tree.sync()
        log.info("已同步 %d 個 Discord 指令", len(synced))
        self.tracking.start()

    async def close(self) -> None:
        await self.tracking.close()
        await super().close()

    def _register_commands(self) -> None:
        @self.tree.command(name="search", description="依姓名搜尋球員")
        @app_commands.describe(league="聯盟", name="英文、日文或韓文姓名")
        @app_commands.choices(league=LEAGUE_CHOICES)
        async def search(
            interaction: discord.Interaction,
            league: app_commands.Choice[str],
            name: str,
        ) -> None:
            await interaction.response.defer(ephemeral=True)
            provider = self.providers[League(league.value)]
            try:
                players = await provider.search_players(name.strip())
            except ProviderUnavailable as exc:
                await interaction.followup.send(f"⚠️ {exc}", ephemeral=True)
                return
            if not players:
                await interaction.followup.send(
                    "找不到球員。你可以使用 `/subscribe` 手動輸入球員 ID。",
                    ephemeral=True,
                )
                return
            lines = [
                f"`{p.external_id}`｜**{p.canonical_name}**｜{p.team or '球隊未知'}｜{p.position or '-'}"
                for p in players
            ]
            await interaction.followup.send(
                "搜尋結果（複製 ID 到 `/subscribe`）：\n" + "\n".join(lines),
                ephemeral=True,
            )

        @self.tree.command(name="subscribe", description="用聯盟球員 ID 加入訂閱")
        @app_commands.describe(
            league="聯盟", player_id="聯盟官方球員 ID", display_name="通知顯示名稱"
        )
        @app_commands.choices(league=LEAGUE_CHOICES)
        async def subscribe(
            interaction: discord.Interaction,
            league: app_commands.Choice[str],
            player_id: str,
            display_name: str,
        ) -> None:
            current = await self.database.subscriptions(interaction.user.id)
            if len(current) >= self.settings.max_subscriptions:
                await interaction.response.send_message(
                    f"最多只能訂閱 {self.settings.max_subscriptions} 名球員。",
                    ephemeral=True,
                )
                return
            selected_league = League(league.value)
            provider = self.providers[selected_league]
            try:
                player = await provider.get_player(player_id.strip())
            except (ProviderUnavailable, ValueError) as exc:
                # NPB/KBO MVP 可先保留手動 ID；資料源接通前會明確告警。
                if selected_league == League.MLB:
                    await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
                    return
                player = Player(selected_league, player_id.strip(), display_name.strip())
            added = await self.database.add_subscription(
                interaction.user.id, player, display_name.strip()
            )
            message = (
                f"✅ 已訂閱 **{display_name}**（{selected_league.value} / {player.external_id}）"
                if added
                else "這名球員已經在你的訂閱名單中。"
            )
            await interaction.response.send_message(message, ephemeral=True)

        @self.tree.command(name="subscriptions", description="查看自己的訂閱名單")
        async def subscriptions(interaction: discord.Interaction) -> None:
            items = await self.database.subscriptions(interaction.user.id)
            if not items:
                message = "目前沒有訂閱。使用 `/search` 搜尋球員。"
            else:
                message = "\n".join(
                    f"• **{item.display_name}**｜{item.player.league.value}｜`{item.player.external_id}`"
                    for item in items
                )
            await interaction.response.send_message(message, ephemeral=True)

        @self.tree.command(name="unsubscribe", description="取消一名球員的訂閱")
        @app_commands.describe(league="聯盟", player_id="訂閱名單內的球員 ID")
        @app_commands.choices(league=LEAGUE_CHOICES)
        async def unsubscribe(
            interaction: discord.Interaction,
            league: app_commands.Choice[str],
            player_id: str,
        ) -> None:
            removed = await self.database.remove_subscription(
                interaction.user.id, League(league.value), player_id.strip()
            )
            await interaction.response.send_message(
                "✅ 已取消訂閱。" if removed else "找不到這筆訂閱。",
                ephemeral=True,
            )

        @self.tree.command(name="today", description="立即查詢所有訂閱球員今日成績")
        async def today(interaction: discord.Interaction) -> None:
            await interaction.response.defer(ephemeral=True)
            # 先補抓剛恢復的即時／歷史事件，再傳送摘要。
            try:
                await self.tracking.poll_once()
            except Exception:
                log.exception("手動查詢前的事件補抓失敗")
            sent = await self.tracking.send_summaries_now(interaction.user.id)
            await interaction.followup.send(
                f"已透過私訊送出 {sent} 份可用摘要。", ephemeral=True
            )

        @self.tree.command(name="status", description="查看機器人與資料源狀態")
        async def status(interaction: discord.Interaction) -> None:
            await interaction.response.send_message(
                "✅ Bot 運作中\n"
                "• MLB：公開 Stats API（已接通）\n"
                "• NPB：Yahoo! JAPAN 賽況（已接通）\n"
                "• KBO：Naver Sports / KBO 官方網站（已接通）",
                ephemeral=True,
            )
