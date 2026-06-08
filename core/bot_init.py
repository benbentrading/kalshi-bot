################################
#    scripts/bot_init.py       #
################################

import asyncio
from core.classes.bot import Bot
from core.thread_bridge import set_socketio, set_bot_event_loop
from scripts.api_external.boltodds_wrapper import BoltClient
from scripts.api_external.kalshi_ws_wrapper import KalshiWsClient
from scripts.api_external.kalshi_api_wrapper import request_queue

# DEFINE GLOBAL BOT OBJECT
bot = Bot()

async def start_bot(flask_socketio=None, flask_app=None):
    print("bot starting...")

    if flask_socketio and flask_app:
        set_socketio(flask_socketio, flask_app)

    set_bot_event_loop(asyncio.get_event_loop())
    request_queue.start(asyncio.get_event_loop())

    # set ws clients
    boltodds_client = BoltClient(on_message=bot.handle_boltodds_data)
    kalshi_ws_client = KalshiWsClient(on_message=bot.handle_kalshi_ws_data)
    boltodds_client.start()
    kalshi_ws_client.start()
    bot.set_clients(kalshi_ws_client, boltodds_client)

    # set kalshi batch request loop tick


    await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(start_bot())