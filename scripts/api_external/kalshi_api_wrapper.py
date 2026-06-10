###################################
#  scripts/kalshi_api_wrapper.py  #
#  fetching kalshi odds and       #
#  placing trades on kalshi       #
###################################

#############
#  IMPORTS  #
#############
import os
import uuid
import threading
import asyncio
from concurrent.futures import Future as ThreadFuture
from dotenv import load_dotenv
import requests
import datetime
import json
from pprint import pprint
import time

from scripts.utils import load_private_key_from_file, sign_pss_text, get_unix_timestamp

load_dotenv()  # loads .env automatically
env = os.getenv("APP_ENV", "dev").lower()   # fallback to "dev" if missing
load_dotenv(f".env.{env}", override=True)


###############
#  CONSTANTS  #
###############
# flex constants (dev or prod based on env var)
KALSHI_API_BASE_URL = os.getenv("KALSHI_API_BASE_URL")
KALSHI_PRIVATE_KEY_FILE_PATH = os.getenv("KALSHI_PRIVATE_KEY_FILE_PATH")
KALSHI_ACCESS_KEY = os.getenv("KALSHI_ACCESS_KEY")
KALSHI_SUBACCOUNT = int(os.getenv("KALSHI_SUBACCOUNT", 0))

# dev environ vars
DEV_KALSHI_API_BASE_URL= os.getenv("DEV_KALSHI_API_BASE_URL")
DEV_KALSHI_ACCESS_KEY= os.getenv("DEV_KALSHI_ACCESS_KEY")
DEV_KALSHI_PRIVATE_KEY_FILE_PATH= os.getenv("DEV_KALSHI_PRIVATE_KEY_FILE_PATH")
DEV_KALSHI_WS_BASE_URL= os.getenv("DEV_KALSHI_WS_BASE_URL")

# prod environ vars
PROD_KALSHI_API_BASE_URL= os.getenv("PROD_KALSHI_API_BASE_URL")
PROD_KALSHI_ACCESS_KEY= os.getenv("PROD_KALSHI_ACCESS_KEY")
PROD_KALSHI_PRIVATE_KEY_FILE_PATH= os.getenv("PROD_KALSHI_PRIVATE_KEY_FILE_PATH")
PROD_KALSHI_WS_BASE_URL= os.getenv("PROD_KALSHI_WS_BASE_URL")


# api limits
MAX_READ_CREDITS_PER_SECOND = 300
MAX_WRITE_CREDITS_PER_SECOND = 300
CREDITS_PER_READ_CALL = 10
CREDITS_PER_WRITE_CALL = 25


#####################
#  FUNCTIONS: core  #
#####################
def generate_kalshi_headers(method:str, api_path:str, env_override:str = None) -> dict:
    """
    Generates the authentication headers required for Kalshi API requests.
    Loads private key, creates timestamp, signs the message, and returns headers.
    """

    # get private key from file
    curr_env = env if env_override is None else env_override
    private_key_path = PROD_KALSHI_PRIVATE_KEY_FILE_PATH if curr_env == "prod" \
        else DEV_KALSHI_PRIVATE_KEY_FILE_PATH

    private_key = load_private_key_from_file(private_key_path)

    # generate timestamp (in milliseconds)
    current_time = datetime.datetime.now(datetime.timezone.utc)
    timestamp_ms = int(current_time.timestamp() * 1000)
    timestamp_str = str(timestamp_ms)

    # strip query parameters from path before signing
    msg_string = timestamp_str + method + api_path

    # create signature
    sig = sign_pss_text(private_key, msg_string)

    # form and return headers
    access_key = PROD_KALSHI_ACCESS_KEY if curr_env == "prod" else DEV_KALSHI_ACCESS_KEY
    headers = {
        'KALSHI-ACCESS-KEY': access_key,
        'KALSHI-ACCESS-SIGNATURE': sig,
        'KALSHI-ACCESS-TIMESTAMP': timestamp_str
    }

    return headers


def send_api_request(method: str, api_path: str, payload: dict = None, env_override:str=None) -> requests.Response:
    """
    Universal function for sending API requests to Kalshi.
    Uses generate_kalshi_headers() for authentication.
    """
    # get the signed headers
    path_without_query = f"/trade-api/v2{api_path.split('?')[0]}"
    headers = generate_kalshi_headers(method, path_without_query, env_override=env_override)

    # build the full URL
    url = KALSHI_API_BASE_URL + api_path

    # send the request
    if method.upper() == "GET":
        response = requests.get(url, headers=headers, json=payload)
    elif method.upper() == "POST":
        response = requests.post(url, headers=headers, json=payload)
    elif method.upper() in ("DELETE", "DEL"):
        response = requests.delete(url, headers=headers, json=payload)
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")

    return response


##################################
#  TOKEN BUCKET RATE LIMITER     #
##################################

class TokenBucket:
    """
    Token bucket for rate limiting API calls.

    Fills at `rate` credits/second up to `capacity`.
    consume(n) waits asynchronously until n credits are available,
    then deducts them — no call is ever dropped, just delayed.
    """

    def __init__(self, capacity: float, rate: float):
        self._capacity = capacity       # max credits (burst ceiling)
        self._rate = rate               # credits added per second
        self._tokens = capacity         # start full
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    async def consume(self, credits: float) -> None:
        """
        Waits until `credits` tokens are available, then deducts them.
        Sleeps in small increments so the event loop stays responsive.
        """
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= credits:
                    self._tokens -= credits
                    return
                # how long until we have enough
                deficit = credits - self._tokens
                wait_secs = deficit / self._rate
                print(f"[rate limiter] waiting {wait_secs:.3f}s for {credits} write credits")
                await asyncio.sleep(wait_secs)


##################################
#  BATCH QUEUE                   #
#  batches place/cancel calls    #
#  into single api requests.     #
#  amend stays direct — no batch #
#  endpoint exists on kalshi.    #
##################################

class KalshiBatchQueue:
    """
    Sits between Order objects and the Kalshi API for place and cancel calls.

    Order.place_on_venue / cancel_on_venue call the module-level place_order
    and cancel_order functions via asyncio.to_thread (i.e. in a worker thread).
    Those functions enqueue a request + ThreadFuture and block on future.result()
    until the tick loop fires the batch and resolves each future individually.

    Deduplication:
      - place:  keyed by (market_ticker, side) — latest params win
      - cancel: keyed by order_id — idempotent, same future reused if duplicate

    Rate limiting:
      - Separate token buckets for writes (place/cancel) using constants from
        the top of this file. Each batch flush consumes CREDITS_PER_WRITE_CALL
        credits before firing. If the bucket is empty the flush waits — no
        calls are ever dropped.

    amend_order bypasses the queue entirely — no batch endpoint on Kalshi.
    """

    TICK_INTERVAL = 0.1  # seconds (10Hz)

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop = None

        # pending queues — dict preserves insertion order, deduplication by key
        self._place_queue:  dict[tuple, dict] = {}  # (market_ticker, side) -> item
        self._cancel_queue: dict[str, dict]   = {}  # order_id -> item
        self._lock = threading.Lock()

        # token buckets — one per credit pool
        # initialised in start() once the event loop is known
        self._write_bucket: TokenBucket = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._write_bucket = TokenBucket(
            capacity=MAX_WRITE_CREDITS_PER_SECOND,
            rate=MAX_WRITE_CREDITS_PER_SECOND,
        )
        asyncio.run_coroutine_threadsafe(self._tick_loop(), self._loop)
        print("KalshiBatchQueue started")


    #####################
    #  enqueue methods  #
    #####################

    def enqueue_place(self, market_ticker: str, side: str, ctx: float, bid_px: int) -> dict:
        """
        Enqueues a place request and blocks the calling thread until the tick
        loop resolves it. Returns the raw response dict from Kalshi (V2 shape).
        If a place for this (market_ticker, side) is already queued this tick,
        the params are overwritten with the latest values.
        """
        key = (market_ticker, side)

        with self._lock:
            existing = self._place_queue.get(key)
            if existing:
                existing["ctx"] = ctx
                existing["bid_px"] = bid_px
                existing["client_order_id"] = str(uuid.uuid4())
                future = existing["future"]
            else:
                future = ThreadFuture()
                self._place_queue[key] = {
                    "client_order_id": str(uuid.uuid4()),
                    "market_ticker": market_ticker,
                    "side": side,
                    "ctx": ctx,
                    "bid_px": bid_px,
                    "future": future,
                }

        return future.result()  # blocks until tick resolves


    def enqueue_cancel(self, order_id: str, market_ticker: str = "", side: str = "") -> dict:
        """
        Enqueues a cancel request and blocks until resolved.
        Returns the raw response dict from Kalshi.
        Duplicate cancel for the same order_id within one tick is a no-op —
        the original future is reused.
        """
        with self._lock:
            existing = self._cancel_queue.get(order_id)
            if existing:
                future = existing["future"]
            else:
                future = ThreadFuture()
                self._cancel_queue[order_id] = {
                    "order_id": order_id,
                    "market_ticker": market_ticker,
                    "side": side,
                    "future": future,
                }

        return future.result()  # always outside the lock


    #################
    #  tick / flush #
    #################

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(self.TICK_INTERVAL)
            await asyncio.gather(
                self._flush_places(),
                self._flush_cancels(),
            )


    async def _flush_places(self) -> None:
        with self._lock:
            if not self._place_queue:
                return
            batch = dict(self._place_queue)
            self._place_queue.clear()

        # consume write credits before firing — waits if bucket is low
        await self._write_bucket.consume(CREDITS_PER_WRITE_CALL)

        print(f"[batch] placing {len(batch)} orders")

        orders_payload = []
        for item in batch.values():
            yes_px = item["bid_px"] if item["side"] == "yes" else (100 - item["bid_px"])
            orders_payload.append({
                "ticker": item["market_ticker"],
                "client_order_id": item["client_order_id"],
                "side": "bid" if item["side"] == "yes" else "ask",
                "count": str(item["ctx"]),
                "price": f"{yes_px / 100:.2f}",
                "time_in_force": "good_till_canceled",
                "self_trade_prevention_type": "taker_at_cross",
                "cancel_order_on_pause": False,
            })

        try:
            response = await asyncio.to_thread(
                send_api_request,
                method="POST",
                api_path="/portfolio/events/orders/batched",
                payload={"orders": orders_payload},
            )

            if response.status_code != 201:
                err = f"batch place failed: status={response.status_code} {response.text}"
                print(err)
                for item in batch.values():
                    item["future"].set_exception(Exception(err))
                return

            response_orders = json.loads(response.text).get("orders", [])

            # positional match — response order matches request order
            items = list(batch.values())
            for item, result in zip(items, response_orders):
                if result.get("error"):
                    err = result["error"]
                    print(f"batch place error {item['market_ticker']} {item['side']}: {err}")
                    item["future"].set_exception(Exception(str(err)))
                else:
                    print(f"{item['market_ticker']} {item['side']} | "
                          f"{item['ctx']} ctx @ {item['bid_px']} placed (batch) in {env}")
                    item["future"].set_result(result)

        except Exception as e:
            for item in batch.values():
                if not item["future"].done():
                    item["future"].set_exception(e)


    async def _flush_cancels(self) -> None:
        with self._lock:
            if not self._cancel_queue:
                return
            batch = dict(self._cancel_queue)
            self._cancel_queue.clear()

        # consume write credits before firing — waits if bucket is low
        await self._write_bucket.consume(CREDITS_PER_WRITE_CALL)

        print(f"[batch] canceling {len(batch)} orders")

        orders_payload = [{"order_id": oid} for oid in batch]

        try:
            response = await asyncio.to_thread(
                send_api_request,
                method="DELETE",
                api_path="/portfolio/orders/batched",
                payload={"orders": orders_payload},
            )

            if response.status_code != 200:
                err = f"batch cancel failed: status={response.status_code} {response.text}"
                print(err)
                for item in batch.values():
                    item["future"].set_exception(Exception(err))
                return

            response_orders = json.loads(response.text).get("orders", [])

            # build lookup by order_id
            result_by_oid = {r["order"]["order_id"]: r for r in response_orders}

            for order_id, item in batch.items():
                result = result_by_oid.get(order_id)

                if result is None:
                    item["future"].set_exception(Exception(
                        f"no response entry for order_id {order_id}"
                    ))
                    continue

                if result.get("error"):
                    err = result["error"]
                    print(f"batch cancel error {item['market_ticker']} {item['side']}: {err}")
                    item["future"].set_exception(Exception(str(err)))
                else:
                    print(f"{item['market_ticker']} {item['side']} | canceled (batch) in {env}")
                    item["future"].set_result(result.get("order", result))

        except Exception as e:
            for item in batch.values():
                if not item["future"].done():
                    item["future"].set_exception(e)


# module-level singleton — imported and started in bot_init.py
request_queue = KalshiBatchQueue()


#################################
#  FUNCTIONS: get portfolio data  #
#################################

def get_portfolio_balance():
    """
    gets portfolio cash/value
    """
    path = "/portfolio/balance"
    response = send_api_request(method="GET", api_path=path)

    if response.status_code != 200:
        print(f"error in scripts/get_portfolio_balance: {response.text}")
        raise Exception(response.text)

    portfolio = json.loads(response.text)
    return portfolio


def get_portfolio_orders(
    ticker:str=None,
    event_ticker:str=None,
    status:str=None,
) -> dict:
    """
    gets all orders under the account
    parameters are filters for the query
    filter by EITHER ticker or event ticker (not both)
        - if both are not none, will just filter by ticker
    - filter by status
    """

    path = "/portfolio/orders?"

    if ticker != None:
        path += f"ticker={ticker}&"
    elif event_ticker != None:
        path += f"event_ticker={event_ticker}&"
    if status != None:
        path += f"status={status}&"

    response = send_api_request(method="GET", api_path=path)

    if response.status_code != 200:
        raise Exception(response)

    orders_dict = json.loads(response.text)
    return orders_dict


def get_portfolio_positions(
    ticker:str=None,
    event_ticker:str=None,
) -> dict:
    """
    gets all open positions under the account
    parameters are filters for the query
    filter by EITHER ticker or event ticker (not both)
        - if both are not none, will just filter by ticker
    """

    path = "/portfolio/positions?"

    if ticker != None:
        path += f"ticker={ticker}&"
    elif event_ticker != None:
        path += f"event_ticker={event_ticker}&"

    response = send_api_request(method="GET", api_path=path)

    if response.status_code != 200:
        raise Exception(response)

    positions_dict = json.loads(response.text)
    return positions_dict


def get_portfolio_fills(
    ticker: str = None,
    order_id: str = None,
    time_frame_mins_ago: int = 0,
    subaccount: int = None,
) -> dict:
    path = "/portfolio/fills?"

    if order_id is not None:
        path += f"order_id={order_id}&"
    elif ticker is not None:
        path += f"ticker={ticker}&"
    if subaccount is not None:
        path += f"subaccount={subaccount}&"
    if time_frame_mins_ago > 0:
        min_ts = get_unix_timestamp(time_frame_mins_ago)
        path += f"min_ts={min_ts}&"

    response = send_api_request(method="GET", api_path=path)

    if response.status_code != 200:
        raise Exception(response)

    return json.loads(response.text)


def get_portfolio_settlements(
    ticker: str = None,
    event_ticker: str = None,
    min_ts: int = None,
    max_ts: int = None,
) -> dict:
    """
    gets settlement history for the account
    filter by ticker or event_ticker (not both)
    filter by time range with min_ts / max_ts (unix timestamps)
    """

    path = "/portfolio/settlements?"

    if ticker is not None:
        path += f"ticker={ticker}&"
    elif event_ticker is not None:
        path += f"event_ticker={event_ticker}&"
    if min_ts is not None:
        path += f"min_ts={min_ts}&"
    if max_ts is not None:
        path += f"max_ts={max_ts}&"

    response = send_api_request(method="GET", api_path=path)

    if response.status_code != 200:
        raise Exception(response)

    settlements_dict = json.loads(response.text)
    return settlements_dict


def create_subaccount() -> dict:
    path = "/portfolio/subaccounts"
    response = send_api_request(method="POST", api_path=path, payload={})

    if response.status_code not in (200, 201):
        raise Exception(response.text)

    return json.loads(response.text)


def transfer_to_subaccount(amount_cents: int, from_subaccount: int, to_subaccount: int) -> dict:
    path = "/portfolio/subaccounts/transfer"
    payload = {
        "client_transfer_id": str(uuid.uuid4()),
        "from_subaccount": from_subaccount,
        "to_subaccount": to_subaccount,
        "amount_cents": amount_cents,
    }
    response = send_api_request(method="POST", api_path=path, payload=payload)

    if response.status_code not in (200, 201):
        raise Exception(response.text)

    return json.loads(response.text)


def get_subaccount_balances() -> dict:
    """
    gets balances for all subaccounts including primary (0).
    """
    path = "/portfolio/subaccounts/balances"
    response = send_api_request(method="GET", api_path=path)

    if response.status_code != 200:
        raise Exception(response.text)

    return json.loads(response.text)


################################
#  FUNCTIONS: get event data   #
#    (event data from league)  #
################################

def get_events_in_series(series_ticker:str, open_only:bool=True) -> dict:
    """
    for a league and market type (e.g. total/spread)
    """

    path = f"/events?series_ticker={series_ticker}"

    if open_only == True:
        path += "&status=open"

    response = send_api_request(method="GET", api_path=path)

    if response.status_code != 200:
        raise Exception(response.text)

    markets_info = json.loads(response.text)
    return markets_info


################################
#  FUNCTIONS: get market data  #
#    (ticker specific data)    #
################################

def get_markets_for_event(event_ticker:str) -> dict:
    """
    from an event (game), get all of the corresponding markets (o/u, ml, spread at diff levels, etc)
    """

    path = f"/markets?event_ticker={event_ticker}"
    response = send_api_request(method="GET", api_path=path)

    if response.status_code != 200:
        raise Exception(response)

    markets_info = json.loads(response.text)
    return markets_info


def get_market_information(market_ticker:str) -> dict:
    """
    gets data about a market from its ticker
    """

    path = f"/markets/{market_ticker}"
    response = send_api_request(method="GET", api_path=path)

    if response.status_code != 200:
        raise Exception(response)

    market_info = json.loads(response.text)
    return market_info


def get_market_order_book(market_ticker:str) -> dict:
    """
    gets the live order book for a specific ticker
    """

    path = f"/markets/{market_ticker}/orderbook"
    response = send_api_request(method="GET", api_path=path)

    if response.status_code != 200:
        raise Exception(response)

    order_book_dict = json.loads(response.text)
    return order_book_dict


def get_market_trade_history(
        market_ticker:str,
        trades_count_limit:int=100,
        time_frame_minutes:int=0
) -> dict:
    """
    gets past trades in a specific market
    """

    min_ts = 0
    if time_frame_minutes > 0:
        min_ts = get_unix_timestamp(minutes_ago=time_frame_minutes)

    path = f"/markets/trades?ticker={market_ticker}&limit={trades_count_limit}"
    if min_ts > 0:
        path += f"&min_ts={min_ts}"

    response = send_api_request(method="GET", api_path=path)

    if response.status_code != 200:
        raise Exception(response)

    trades_dict = json.loads(response.text)
    return trades_dict


#################################
#  FUNCTIONS: post/del methods  #
#  includes put/cancel orders   #
#################################

def place_order(
    market_ticker: str,
    side: str,
    ctx: float,
    bid_px: int,
) -> dict:
    """
    Enqueues a place request onto the batch queue and blocks until the tick
    loop fires it. Returns the raw response dict from Kalshi (V2 shape).
    Called via asyncio.to_thread from Order.place_on_venue.
    """
    return request_queue.enqueue_place(
        market_ticker=market_ticker,
        side=side,
        ctx=ctx,
        bid_px=bid_px,
    )


def amend_order(
    order_id: str,
    market_ticker: str,
    ctx: float,
    bid_px: int,
    side: str,
) -> dict | None:
    """
    Amends an existing resting order directly (no batch endpoint on Kalshi).
    Returns the raw response dict from Kalshi, or None on AMEND_ORDER_NO_OP.
    Raises on all other errors.
    Called via asyncio.to_thread from Order.amend_on_venue.
    """
    path = f"/portfolio/orders/{order_id}/amend"

    payload = {
        "ticker": market_ticker,
        "side": side,
        "action": "buy",
        "count_fp": str(ctx),
        "yes_price" if side == "yes" else "no_price": bid_px,
    }

    response = send_api_request(method="POST", api_path=path, payload=payload)

    if response.status_code != 200:
        error_dict = json.loads(response.text)
        error_code = error_dict.get("error", {}).get("code")

        if error_code == "AMEND_ORDER_NO_OP":
            print(f"{market_ticker} {side} | amend no-op — skipping")
            return None

        print(f"error in amend_order() status={response.status_code}")
        print(error_dict)
        raise Exception(response)

    print(f"{market_ticker} {side} | amended in {env} to {ctx} ctx @ {bid_px}")

    order_response_dict = json.loads(response.text)
    return order_response_dict.get("order", order_response_dict)


def cancel_order(order_id: str, market_ticker:str="", side:str="") -> dict:
    """
    Enqueues a cancel request onto the batch queue and blocks until the tick
    loop fires it. Returns the raw response dict from Kalshi.
    Called via asyncio.to_thread from Order.cancel_on_venue.
    """
    return request_queue.enqueue_cancel(
        order_id=order_id,
        market_ticker=market_ticker,
        side=side,
    )




if __name__ == "__main__":

    # create subaccount (do once)
    # result = create_subaccount()
    # pprint(result)

    result = transfer_to_subaccount(
        amount_cents=50000,
        from_subaccount=2,
        to_subaccount=0
    )

    pprint(get_subaccount_balances())