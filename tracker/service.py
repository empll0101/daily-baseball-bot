from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import discord

from .config import Settings
from .database import Database
from .models import EventKind, League, Subscription, TrackingEvent
from .providers import DataProvider, ProviderUnavailable

TAIPEI = ZoneInfo("Asia/Taipei")
log = logging.getLogger(__name__)


class TrackingService:
    def __init__(
        self,
        client: discord.Client,
        database: Database,
        providers: dict[League, DataProvider],
        settings: Settings,
    ):
        self.client = client
        self.database = database
        self.providers = providers
        self.settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run(), name="tracking-service")

    async def close(self) -> None:
        self._stop.set()
        if self._task:
            await self._task

    async def run(self) -> None:
        await self.client.wait_until_ready()
        log.info("追蹤服務已啟動")
        while not self._stop.is_set():
            try:
                await self.poll_once()
                await self.send_daily_summaries_if_due()
            except Exception:
                log.exception("追蹤迴圈發生未預期錯誤")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.settings.poll_interval_seconds
                )
            except TimeoutError:
                pass

    async def poll_once(self) -> None:
        subscriptions = await self.database.subscriptions()
        now = datetime.now(UTC)
        last_value = await self.database.get_meta("last_poll_at")
        last_poll = datetime.fromisoformat(last_value) if last_value else now
        cutoff = now - timedelta(days=self.settings.backfill_days)
        start_time = max(last_poll, cutoff)

        grouped: dict[League, list[Subscription]] = defaultdict(list)
        for subscription in subscriptions:
            grouped[subscription.player.league].append(subscription)

        for league, league_subscriptions in grouped.items():
            provider = self.providers[league]
            player_ids = {item.player.external_id for item in league_subscriptions}
            try:
                events = await provider.collect_events(
                    player_ids,
                    (start_time.astimezone(TAIPEI) - timedelta(days=1)).date(),
                    now.astimezone(TAIPEI).date(),
                )
            except ProviderUnavailable as exc:
                log.warning("%s 資料源無法使用：%s", league, exc)
                await self._send_degraded_once(league_subscriptions, league, str(exc))
                continue
            for event in events:
                if event.occurred_at < cutoff and event.kind not in {EventKind.GAME_FINAL}:
                    continue
                await self.database.store_event(event)
                for subscription in league_subscriptions:
                    if (
                        subscription.player.external_id == event.player_id
                        and event.occurred_at >= subscription.created_at
                    ):
                        await self._deliver(subscription, event)

        await self.database.set_meta("last_poll_at", now.isoformat())

    async def _deliver(
        self, subscription: Subscription, event: TrackingEvent
    ) -> None:
        if not await self.database.claim_delivery(subscription.user_id, event.key):
            return
        try:
            user = self.client.get_user(subscription.user_id) or await self.client.fetch_user(
                subscription.user_id
            )
            embed = discord.Embed(
                title=f"⚾ {subscription.display_name}｜{event.title}",
                description=event.body,
                colour=_league_colour(event.league),
                timestamp=event.occurred_at,
            )
            embed.set_footer(text=f"{event.league.value}｜比賽 {event.game_id}")
            await user.send(embed=embed)
        except Exception:
            await self.database.release_delivery(subscription.user_id, event.key)
            raise

    async def _send_degraded_once(
        self,
        subscriptions: list[Subscription],
        league: League,
        reason: str,
    ) -> None:
        day = datetime.now(TAIPEI).date().isoformat()
        users = {item.user_id for item in subscriptions}
        for user_id in users:
            key = f"degraded:{league.value}:{day}"
            if not await self.database.claim_delivery(user_id, key):
                continue
            try:
                user = self.client.get_user(user_id) or await self.client.fetch_user(user_id)
                await user.send(
                    f"⚠️ **{league.value} 資料暫時無法更新**\n{reason}\n"
                    "系統不會捏造數據；恢復後會依補發規則處理。"
                )
            except Exception:
                await self.database.release_delivery(user_id, key)
                log.exception("無法傳送資料源告警")

    async def send_daily_summaries_if_due(self) -> None:
        now = datetime.now(TAIPEI)
        scheduled = now.replace(
            hour=self.settings.daily_summary_hour,
            minute=self.settings.daily_summary_minute,
            second=0,
            microsecond=0,
        )
        if now < scheduled:
            return
        day_key = now.date().isoformat()
        if await self.database.get_meta("daily_summary_date") == day_key:
            return
        # 摘要涵蓋台灣時間當日 00:00 到發送當下已結束的賽事。
        subscriptions = await self.database.subscriptions()
        for subscription in subscriptions:
            provider = self.providers[subscription.player.league]
            delivery_key = (
                f"daily:{day_key}:{subscription.user_id}:"
                f"{subscription.player.league.value}:{subscription.player.external_id}"
            )
            if not await self.database.claim_delivery(subscription.user_id, delivery_key):
                continue
            try:
                summary = await provider.daily_summary(
                    subscription.player, now.date(), now.date()
                )
                user = self.client.get_user(subscription.user_id) or await self.client.fetch_user(
                    subscription.user_id
                )
                await user.send(
                    f"📊 **{subscription.display_name}｜{day_key} 每日彙整**\n{summary}"
                )
            except ProviderUnavailable as exc:
                await self.database.release_delivery(subscription.user_id, delivery_key)
                log.warning("每日摘要無法取得：%s", exc)
            except Exception:
                await self.database.release_delivery(subscription.user_id, delivery_key)
                log.exception("每日摘要發送失敗")
        await self.database.set_meta("daily_summary_date", day_key)

    async def send_summaries_now(self, user_id: int) -> int:
        now = datetime.now(TAIPEI)
        subscriptions = await self.database.subscriptions(user_id)
        user = self.client.get_user(user_id) or await self.client.fetch_user(user_id)
        sent = 0
        for subscription in subscriptions:
            provider = self.providers[subscription.player.league]
            try:
                summary = await provider.daily_summary(
                    subscription.player, now.date(), now.date()
                )
            except ProviderUnavailable as exc:
                await user.send(f"⚠️ **{subscription.display_name}**：{exc}")
                continue
            await user.send(
                f"📊 **{subscription.display_name}｜{now.date().isoformat()} 今日成績**\n{summary}"
            )
            sent += 1
        return sent


def _league_colour(league: League) -> discord.Colour:
    return {
        League.MLB: discord.Colour.blue(),
        League.NPB: discord.Colour.red(),
        League.KBO: discord.Colour.teal(),
    }[league]
