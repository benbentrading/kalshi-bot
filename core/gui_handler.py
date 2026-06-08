# core/gui_handler.py
import asyncio
from core.bot_init import bot
from core.thread_bridge import get_bot_event_loop
from scripts.api_external.kalshi_api_wrapper import get_markets_for_event


async def handle_add_event(data: dict):
    event_markets_data = await asyncio.to_thread(
        get_markets_for_event,
        data["kalshi_event_ticker"]
    )
    bot.add_new_event(
        event_static_data=data,
        kalshi_markets_data=event_markets_data.get("markets", []),
    )
    print(f"added event: {data['kalshi_event_ticker']}")


async def handle_set_trading_venue(kalshi_market_ticker: str, trading_venue: str):
    mkt = bot._get_market_by_kalshi_ticker(kalshi_market_ticker)
    if mkt is None:
        print(f"market {kalshi_market_ticker} not found")
        return
    await mkt._update_trading_venue(trading_venue)


def add_event_to_bot(data: dict):
    loop = get_bot_event_loop()
    if loop is None:
        print("bot event loop not set")
        return
    asyncio.run_coroutine_threadsafe(handle_add_event(data), loop)


async def handle_remove_event(kalshi_event_ticker):
    await bot.remove_event(kalshi_event_ticker)


def remove_event_from_bot(kalshi_event_ticker: str):
    loop = get_bot_event_loop()
    if loop is None:
        print("bot event loop not set")
        return
    asyncio.run_coroutine_threadsafe(
        handle_remove_event(kalshi_event_ticker),  # if this is async
        loop
    )


def unsubscribe_all():
    bot.remove_all_markets()


def set_market_trading_venue(kalshi_market_ticker: str, trading_venue: str):
    loop = get_bot_event_loop()
    if loop is None:
        print("bot event loop not set")
        return
    asyncio.run_coroutine_threadsafe(
        handle_set_trading_venue(kalshi_market_ticker, trading_venue),
        loop
    )


async def handle_set_market_max_position_ctx(kalshi_event_ticker:str, ctx:float):
    await bot.set_market_max_position_ctx(kalshi_event_ticker, ctx)


def set_market_max_position_ctx(kalshi_market_ticker: str, ctx: float):
    loop = get_bot_event_loop()
    if loop is None:
        print("bot event loop not set")
        return
    asyncio.run_coroutine_threadsafe(
        handle_set_market_max_position_ctx(kalshi_market_ticker, ctx),
        loop
    )