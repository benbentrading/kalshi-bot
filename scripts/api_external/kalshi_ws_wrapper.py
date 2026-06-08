################################
#  scripts/kalshi_ws.py        #
#  cxn to kalshi ws via class  #
################################

#############
#  IMPORTS  #
#############
import os
from dotenv import load_dotenv
import json
from pprint import pprint
import asyncio
import websockets
import scripts.api_external.kalshi_api_wrapper

load_dotenv()
env = "prod" # ws can always use prod
load_dotenv(f".env.{env}", override=True)


###############
#  CONSTANTS  #
###############
KALSHI_WS_BASE_URL = os.getenv("KALSHI_WS_BASE_URL")


###############
#  FUNCTIONS  #
###############
class KalshiWsClient:
    def __init__(self, on_message: callable = None):
        self.on_message = on_message

        self.command_queue = asyncio.Queue()
        self.ready = asyncio.Event()

        self.running = False
        self.task = None
        self.websocket = None

        self.market_tickers = []
        self.CHANNELS = ["ticker", "trade", "market_positions"]
        self.channel_sids = {}

    # ---------- PUBLIC API ----------

    def start(self):
        if not self.task or self.task.done():
            self.running = True
            self.task = asyncio.create_task(self._run())
            print("KalshiWsClient started")


    def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
        print("KalshiWsClient stopped")


    def subscribe(self, market_tickers):
        """Subscribe to a list of market tickers across all market channels."""
        self.market_tickers = market_tickers
        # print(f"SUBSCRIBING TO {self.market_tickers}")

        sub_msg = {
            "id": 1,
            "cmd": "subscribe",
            "send_initial_snapshot": True,
            "params": {
                "channels": self.CHANNELS,
                "market_tickers": self.market_tickers
            }
        }
        self.command_queue.put_nowait(sub_msg)

    def resubscribe(self, market_tickers: list):
        """Unsubscribe all, then resubscribe with new tickers (or just unsubscribe if empty)."""
        
        # build unsubscribe message if we have active sids
        sids = [
            sid for channel, sid in self.channel_sids.items()
            if channel in set(self.CHANNELS)
        ]
        if sids:
            unsub_msg = {
                "id": 999,
                "cmd": "unsubscribe",
                "params": {"sids": sids}
            }
            self.command_queue.put_nowait(unsub_msg)
            self.channel_sids = {}

        self.market_tickers = market_tickers

        # only resubscribe if tickers provided
        if market_tickers:
            sub_msg = {
                "id": 1,
                "cmd": "subscribe",
                "send_initial_snapshot": True,
                "params": {
                    "channels": self.CHANNELS,
                    "market_tickers": self.market_tickers
                }
            }
            self.command_queue.put_nowait(sub_msg)
        else:
            print("no tickers — unsubscribed only")

    def unsubscribe_all(self):
        """Unsubscribe from all market channels using stored sids."""
        sids = [
            sid for channel, sid in self.channel_sids.items()
            if channel in set(self.CHANNELS)  # excludes "fill"
        ]

        if not sids:
            # print("UNSUBSCRIBE: no sids stored, skipping")
            self.market_tickers = []
            return

        unsub_msg = {
            "id": 999,
            "cmd": "unsubscribe",
            "params": {
                "sids": sids
            }
        }
        self.command_queue.put_nowait(unsub_msg)

        print(f"UNSUBSCRIBED sids {sids} for markets: {self.market_tickers}")

        # clear after building message
        self.channel_sids = {}
        self.market_tickers = []


    def unsubscribe_market(self, market_ticker: str):
        """Remove a single market by unsubscribing all, then resubscribing without it."""
        self.market_tickers = [t for t in self.market_tickers if t != market_ticker]
        self.unsubscribe_all()

        if self.market_tickers:
            self.subscribe(self.market_tickers)


    # ---------- INTERNALS ----------

    async def _run(self):
        ws_path = "/trade-api/ws/v2"
        auth_headers = scripts.api_external.kalshi_api_wrapper.generate_kalshi_headers("GET", ws_path, env_override="prod")

        while self.running:
            try:
                async with websockets.connect(
                    KALSHI_WS_BASE_URL,
                    additional_headers=auth_headers,
                    max_size=None,
                    ping_interval=20,
                    ping_timeout=30
                ) as websocket:

                    self.websocket = websocket
                    self.channel_sids = {}  # reset sids on each new connection
                    print("Connected to Kalshi WebSocket")

                    self.ready.clear()
                    await asyncio.sleep(0.25)
                    self.ready.set()

                    # subscribe to fill channel on connect (account-level, persistent)
                    fill_update_msg = {
                        "id": 5,
                        "cmd": "subscribe",
                        "params": {
                            "channels": ["fill"],
                        }
                    }
                    await self.command_queue.put(fill_update_msg)

                    recv_task = asyncio.create_task(self._recv_loop(websocket))
                    send_task = asyncio.create_task(self._send_loop(websocket))

                    done, pending = await asyncio.wait(
                        [recv_task, send_task],
                        return_when=asyncio.FIRST_EXCEPTION
                    )

                    for task in pending:
                        task.cancel()

            except Exception as e:
                print("kalshi websocket error:", e)
                print(f"Error Type : {type(e).__name__}")

            if self.running:
                print("Reconnecting in 5 seconds...")
                await asyncio.sleep(5)


    async def _send_loop(self, websocket):
        while self.running:
            cmd = await self.command_queue.get()
            await websocket.send(json.dumps(cmd))
            # print("Sent:", cmd)


    async def _recv_loop(self, websocket):
        while self.running:
            message = await websocket.recv()
            try:
                data = json.loads(message)

                # capture sids from server subscribe confirmations
                if data.get("type") == "subscribed":
                    msg = data.get("msg", {})
                    channel = msg.get("channel")
                    sid = msg.get("sid")
                    if channel and sid:
                        self.channel_sids[channel] = sid

                if self.on_message:
                    self.on_message(data)

            except json.JSONDecodeError:
                print("Non-JSON message:", message)

