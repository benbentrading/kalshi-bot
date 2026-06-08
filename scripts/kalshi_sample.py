###################################
#  kalshi_sample.py               #
#  Advanced API application       #
#  sample — NYC weather markets   #
###################################
#
#  Demonstrates:
#    1. Query market data for today's NYC high temperature markets
#    2. Query the orderbook for the first open market
#    3. Place a 1-unit limit order and immediately cancel it
#

#############
#  IMPORTS  #
#############
import os
import datetime
import json
import time
from pprint import pprint

import requests
from dotenv import load_dotenv

from scripts.utils import load_private_key_from_file, sign_pss_text

load_dotenv()
env = os.getenv("APP_ENV", "dev").lower()
env = "dev"
load_dotenv(f".env.{env}", override=True)


###############
#  CONSTANTS  #
###############
KALSHI_API_BASE_URL          = os.getenv("KALSHI_API_BASE_URL")

DEV_KALSHI_ACCESS_KEY        = os.getenv("DEV_KALSHI_ACCESS_KEY")
DEV_KALSHI_PRIVATE_KEY_FILE_PATH = os.getenv("DEV_KALSHI_PRIVATE_KEY_FILE_PATH")

PROD_KALSHI_ACCESS_KEY       = os.getenv("PROD_KALSHI_ACCESS_KEY")
PROD_KALSHI_PRIVATE_KEY_FILE_PATH = os.getenv("PROD_KALSHI_PRIVATE_KEY_FILE_PATH")

# NYC high temperature series — tracks daily high at Central Park per NWS
NYC_WEATHER_SERIES = "KXHIGHNY"


#####################
#  FUNCTIONS: core  #
#####################

def generate_kalshi_headers(method: str, api_path: str) -> dict:
    """
    Generates signed authentication headers for Kalshi API requests.
    Signs: timestamp_ms + METHOD + /trade-api/v2<path_without_query>
    """
    private_key_path = PROD_KALSHI_PRIVATE_KEY_FILE_PATH if env == "prod" \
        else DEV_KALSHI_PRIVATE_KEY_FILE_PATH

    private_key = load_private_key_from_file(private_key_path)

    current_time = datetime.datetime.now(datetime.timezone.utc)
    timestamp_ms = int(current_time.timestamp() * 1000)
    timestamp_str = str(timestamp_ms)

    msg_string = timestamp_str + method + api_path
    sig = sign_pss_text(private_key, msg_string)

    access_key = PROD_KALSHI_ACCESS_KEY if env == "prod" else DEV_KALSHI_ACCESS_KEY
    return {
        "KALSHI-ACCESS-KEY": access_key,
        "KALSHI-ACCESS-SIGNATURE": sig,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_str,
    }


def send_api_request(method: str, api_path: str, payload: dict = None) -> requests.Response:
    """
    Sends an authenticated request to the Kalshi API.
    Strips query params from api_path before signing (Kalshi requirement).
    """
    path_without_query = f"/trade-api/v2{api_path.split('?')[0]}"
    headers = generate_kalshi_headers(method, path_without_query)
    url = KALSHI_API_BASE_URL + api_path

    if method.upper() == "GET":
        response = requests.get(url, headers=headers)
    elif method.upper() == "POST":
        response = requests.post(url, headers=headers, json=payload)
    elif method.upper() in ("DELETE", "DEL"):
        response = requests.delete(url, headers=headers, json=payload)
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")

    return response


###########################
#  STEP 1: market data    #
###########################

def get_nyc_weather_markets() -> list[dict]:
    """
    Queries all open markets in the KXHIGHNY series (highest temp in NYC today).
    Returns the list of market dicts, sorted by ticker.
    """
    path = f"/markets?series_ticker={NYC_WEATHER_SERIES}&status=open"
    response = send_api_request(method="GET", api_path=path)

    if response.status_code != 200:
        print(f"error fetching NYC weather markets: {response.status_code}")
        print(response.text)
        raise Exception(response.text)

    markets = json.loads(response.text).get("markets", [])
    print(f"\n=== NYC Weather Markets ({len(markets)} open) ===")
    for m in markets:
        print(f"  {m['ticker']} | {m.get('title', '')} | "
              f"yes_bid={m.get('yes_bid')} yes_ask={m.get('yes_ask')} | "
              f"volume={m.get('volume_fp', 0)}")

    return markets


###########################
#  STEP 2: orderbook      #
###########################

def get_orderbook(market_ticker: str) -> dict:
    """
    Queries the live orderbook for a specific market ticker.
    Returns the orderbook dict with yes/no bid and ask levels.
    """
    path = f"/markets/{market_ticker}/orderbook"
    response = send_api_request(method="GET", api_path=path)

    if response.status_code != 200:
        print(f"error fetching orderbook for {market_ticker}: {response.status_code}")
        print(response.text)
        raise Exception(response.text)

    orderbook = json.loads(response.text).get("orderbook", {})
    print(f"\n=== Orderbook: {market_ticker} ===")
    print(f"  yes bids: {orderbook.get('yes', [])[:5]}")   # top 5 levels
    print(f"  no bids:  {orderbook.get('no', [])[:5]}")

    return orderbook


###################################
#  STEP 3a: place 1-unit order    #
###################################

def place_order(market_ticker: str, side: str, bid_px: int) -> dict:
    """
    Places a single 1-unit limit order on the given market.
    bid_px is in integer cents (e.g. 45 = $0.45).
    Returns the created order dict.
    """
    path = "/portfolio/orders"
    payload = {
        "ticker": market_ticker,
        "side": side,
        "action": "buy",
        "count": 1,
        "type": "limit",
        "yes_price" if side == "yes" else "no_price": bid_px,
        "cancel_order_on_pause": False,
    }

    response = send_api_request(method="POST", api_path=path, payload=payload)

    if response.status_code != 201:
        print(f"error placing order on {market_ticker}: {response.status_code}")
        print(response.text)
        raise Exception(response.text)

    order = json.loads(response.text).get("order", {})
    print(f"\n=== Order Placed ===")
    print(f"  order_id: {order.get('order_id')}")
    print(f"  ticker:   {order.get('ticker')}")
    print(f"  side:     {order.get('side')}")
    print(f"  status:   {order.get('status')}")
    print(f"  yes_price: {order.get('yes_price_dollars')} | no_price: {order.get('no_price_dollars')}")
    print(f"  remaining: {order.get('remaining_count_fp')}")

    return order


###################################
#  STEP 3b: cancel the order      #
###################################

def cancel_order(order_id: str) -> dict:
    """
    Cancels an existing resting order by order_id.
    Returns the cancelled order dict.
    """
    path = f"/portfolio/orders/{order_id}"
    response = send_api_request(method="DELETE", api_path=path)

    if response.status_code != 200:
        print(f"error cancelling order {order_id}: {response.status_code}")
        print(response.text)
        raise Exception(response.text)

    cancelled = json.loads(response.text).get("order", {})
    print(f"\n=== Order Cancelled ===")
    print(f"  order_id: {cancelled.get('order_id')}")
    print(f"  status:   {cancelled.get('status')}")
    print(f"  reduced_by: {cancelled.get('reduced_by_fp')}")

    return cancelled


##############
#  MAIN      #
##############

if __name__ == "__main__":

    # ------------------------------------------------------------------ #
    #  STEP 1 — query open markets in the NYC high temperature series     #
    # ------------------------------------------------------------------ #
    markets = get_nyc_weather_markets()

    if not markets:
        print("no open NYC weather markets found — market may be closed for the day")
        exit(0)

    # use the first open market (sorted by ticker, lowest threshold first)
    target_market = sorted(markets, key=lambda m: m["ticker"])[0]
    ticker = target_market["ticker"]
    print(f"\ntarget market: {ticker}")

    # ------------------------------------------------------------------ #
    #  STEP 2 — query the orderbook for that market                       #
    # ------------------------------------------------------------------ #
    orderbook = get_orderbook(ticker)

    # ------------------------------------------------------------------ #
    #  STEP 3 — place a 1-unit limit order, then immediately cancel it    #
    #                                                                      #
    #  We bid 1 cent on the yes side — deliberately far from the market   #
    #  so it rests rather than filling before we can cancel it.           #
    # ------------------------------------------------------------------ #
    order = place_order(
        market_ticker=ticker,
        side="yes",
        bid_px=1,           # $0.01 — well below market, guaranteed to rest
    )

    order_id = order.get("order_id")
    order_status = order.get("status")
    remaining = float(order.get("remaining_count_fp", 0))

    # only cancel if the order is actually resting (not immediately filled)
    if order_status == "resting" and remaining > 0:
        # brief pause to confirm resting state before cancel
        time.sleep(0.5)
        cancelled = cancel_order(order_id)
    else:
        print(f"\norder filled immediately (status={order_status}) — no cancel needed")

    print("\ndone.")
