#############
#  IMPORTS  #
#############
import websockets
import os
from dotenv import load_dotenv
import asyncio
import requests
import json
from pprint import pprint
from threading import Lock, Thread
import time
from queue import Queue, Empty
from dataclasses import dataclass, field
from typing import List

# local
from scripts.utils import get_unix_timestamp

load_dotenv()


###############
#  CONSTANTS  #
###############
BOLTODDS_API_KEY = os.getenv("BOLTODDS_API_KEY")
queue_lock = Lock() # safe reads/writes to the queue
VEGAS_ODDS_SOURCE = "fanduel"

###############
#   CLASSES   #
###############

@dataclass
class BoltClient:
    def __init__(self, on_message: callable = None):
        self.on_message = on_message

        self.command_queue = asyncio.Queue()
        self.ready = asyncio.Event()

        self.running = False
        self.task = None
        self.websocket = None
        self.started = False
        self.last_subscribe: int = 0
        
        self.game_ids: List[str] = []
        self.markets: List[str] = []
        self.leagues: List[str] = []


    # ---------- PUBLIC API ----------

    def start(self):
        if not self.task or self.task.done():
            self.running = True
            self.task = asyncio.create_task(self._run())
            print("BoltClient started")

    def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
        print("BoltClient stopped")


    def subscribe(self, game_ids:list, markets:list, leagues:list):
        """Send (or update) a subscription on the live socket."""
        self.game_ids = game_ids if isinstance(game_ids, list) else [game_ids]
        self.markets = markets if isinstance(markets, list) else [markets]
        self.leagues = leagues if isinstance(leagues, list) else [leagues]
        five_min_ago_unix = get_unix_timestamp(minutes_ago=5)

        if self.started == False or self.last_subscribe < five_min_ago_unix: # first start
            print(f"subscribing to {self.game_ids} {self.markets}")
            msg = {
                "action": "subscribe",
                "filters": {
                    "sports": self.leagues,
                    "sportsbooks": [VEGAS_ODDS_SOURCE],
                    "games": self.game_ids,
                    "markets": self.markets
                }
            }
            pprint(msg, sort_dicts=False)
            self.command_queue.put_nowait(msg)
        else:
            asyncio.create_task(self._reconnect())

        self.started = True
        self.last_subscribe = get_unix_timestamp()


    async def _reconnect(self):
        """Close current connection — _run will reconnect with updated game_ids/markets."""
        await asyncio.sleep(0.5)
        if self.websocket:
            await self.websocket.close()
            await self._send_current_subscribe()
        

    # ---------- INTERNALS ----------

    async def _run(self):
        uri = f"wss://spro.agency/api?key={BOLTODDS_API_KEY}"

        while self.running:
            try:
                async with websockets.connect(
                    uri,
                    max_size=None,
                    ping_interval=20,
                    ping_timeout=30
                ) as websocket:

                    self.websocket = websocket
                    print("Connected to Bolt Odds WebSocket")

                    self.ready.clear()

                    # give server time to finish auth handshake
                    await asyncio.sleep(0.25)
                    self.ready.set()

                    # Send initial subscription
                    await self._send_current_subscribe()

                    recv_task = asyncio.create_task(self._recv_loop(websocket))
                    send_task = asyncio.create_task(self._send_loop(websocket))

                    done, pending = await asyncio.wait(
                        [recv_task, send_task],
                        return_when=asyncio.FIRST_EXCEPTION
                    )

                    for task in pending:
                        task.cancel()

            except Exception as e:
                print("WebSocket error:", e)

            if self.running:
                print("reconnecting in 1 seconds...")
                await asyncio.sleep(1)


    async def _send_current_subscribe(self):
        msg = {
            "action": "subscribe",
            "filters": {
                "sports": self.leagues,
                "sportsbooks": [VEGAS_ODDS_SOURCE],
                "games": self.game_ids,
                "markets": self.markets
            }
        }
        pprint(msg, sort_dicts=False)
        await self.command_queue.put(msg)


    async def _send_loop(self, websocket):
        while self.running:
            try:
                cmd = await self.command_queue.get()
                # print(f"boltodds sending: {cmd}")
                pprint(cmd, sort_dicts=False)
                await websocket.send(json.dumps(cmd))
            except websockets.exceptions.ConnectionClosed as e:
                print(f"boltodds send loop connection closed: {e}")
                break
            except Exception as e:
                print(f"boltodds send loop error: {e}")
                break


    async def _recv_loop(self, websocket):
        while self.running:
            try:
                message = await websocket.recv()
                try:
                    data = json.loads(message)
                    if self.on_message:
                        for item in data:
                            self.on_message(item)
                except json.JSONDecodeError:
                    print("Non-JSON message:", message)
            except websockets.exceptions.ConnectionClosed as e:
                print(f"boltodds recv loop connection closed: {e}")
                break
            except Exception as e:
                print(f"boltodds recv loop error: {type(e).__name__}: {e}")
                break


##########################
#   REST API FUNCTIONS   #
##########################

def get_info():
    response = requests.get(f"https://spro.agency/api/get_info?key={BOLTODDS_API_KEY}")
    pprint(response.text)


def get_games(league:str) -> dict:
    """
    gets all available games to connect to
    need to filter by sport for it to even be legible
    """
    response = requests.get(f"https://spro.agency/api/get_games?key={BOLTODDS_API_KEY}")
    
    # error handling
    if response.status_code != 200:
        print(f"error in get_games(league={league})")
        raise Exception(response.text)
    
    games:dict = json.loads(response.text)

    filtered_games = {
        k: v for k, v in games.items()
        if v.get("sport") == league
    }

    return filtered_games


def get_markets(league:str, sportsbook:str) -> dict:
    path = f"https://spro.agency/api/get_markets?key={BOLTODDS_API_KEY}&sports={league}&sportsbooks={sportsbook}"
    response = requests.get(path)
    data = json.loads(response.text)
    return data

###############
#   PARSERS   #
###############




#################
#   EXECUTION   #
#################
async def main():
    games = ['Los Angeles Dodgers vs Philadelphia Phillies, 2026-05-31, 04',
             'Seattle Mariners vs Arizona Diamondbacks, 2026-05-31, 04']

    market = "Team Total"

    client = BoltClient(on_message=pprint)
    client.start()

    await asyncio.sleep(3)

    client.subscribe(game_ids=games, markets=[market])

    # keep the program alive
    while True:
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
    # pprint(get_info())
    # pprint(get_markets("MLB", VEGAS_ODDS_SOURCE))
    # pprint(get_games("MLB").keys())