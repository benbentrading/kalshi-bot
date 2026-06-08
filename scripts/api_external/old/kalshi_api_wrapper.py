###################################
#  scripts/kalshi_api_wrapper.py  #
#  fetching kalshi odds and       #
#  placing trades on kalshi       #
###################################

#############
#  IMPORTS  #
#############
import os
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

# dev environ vars
DEV_KALSHI_API_BASE_URL= os.getenv("DEV_KALSHI_API_BASE_URL")
DEV_KALSHI_ACCESS_KEY= os.getenv("DEV_KALSHI_ACCESS_KEY")
DEV_KALSHI_PRIVATE_KEY_FILE_PATH= os.getenv("DEV_KALSHI_PRIVATE_KEY_FILE_PATH")
DEV_KALSHI_WS_BASE_URL= os.getenv("DEV_KALSHI_WS_BASE_URL")

# prod environ vats
PROD_KALSHI_API_BASE_URL= os.getenv("PROD_KALSHI_API_BASE_URL")
PROD_KALSHI_ACCESS_KEY= os.getenv("PROD_KALSHI_ACCESS_KEY")
PROD_KALSHI_PRIVATE_KEY_FILE_PATH= os.getenv("PROD_KALSHI_PRIVATE_KEY_FILE_PATH")
PROD_KALSHI_WS_BASE_URL= os.getenv("PROD_KALSHI_WS_BASE_URL")


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
    current_time = datetime.datetime.now(datetime.timezone.utc)  # better to be explicit with UTC
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
    # Get the signed headers
    path_without_query = f"/trade-api/v2{api_path.split('?')[0]}"
    headers = generate_kalshi_headers(method, path_without_query, env_override=env_override)

    # Build the full URL
    url = KALSHI_API_BASE_URL + api_path

    # Send the request
    if method.upper() == "GET":
        response = requests.get(url, headers=headers, json=payload)
    elif method.upper() == "POST":
        response = requests.post(url, headers=headers, json=payload)
    elif method.upper() in ("DELETE", "DEL"):
        response = requests.delete(url, headers=headers, json=payload)
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")

    return response


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
    
    # parse and return data
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
        - if both are not none, fill just filter by ticker
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
    
    # error handling
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
        - if both are not none, fill just filter by ticker
    """

    path = "/portfolio/positions?"

    # add parameters
    if ticker != None:
        path += f"ticker={ticker}&"
    elif event_ticker != None:
        path += f"event_ticker={event_ticker}&"

    # call kalshi api
    response = send_api_request(method="GET", api_path=path)
    
    # error handling
    if response.status_code != 200:
        raise Exception(response)
    
    # parse response and return data
    positions_dict = json.loads(response.text)
    return positions_dict


def get_portfolio_fills(
    ticker:str=None,
    order_id:str=None,
    time_frame_mins_ago:int=0,
) -> dict:
    """
    gets all executed trades (order fills)
    if both order_id and ticker are not none, will filter by order_id
    """

    path = "/portfolio/fills?"

    # add parameters
    if order_id != None:
        path += f"ticker={ticker}&"
    elif ticker != None:
        path += f"event_ticker={event_ticker}&"

    min_ts = 0
    if time_frame_mins_ago > 0:
        min_ts = get_unix_timestamp(time_frame_mins_ago)
        path += f"min_ts={min_ts}&"

    # call kalshi api
    response = send_api_request(method="GET", api_path=path)
    
    # error handling
    if response.status_code != 200:
        raise Exception(response)
    
    # parse response and return data
    fills_dict = json.loads(response.text)
    return fills_dict


def get_order():
    """
    TODO implement
    """


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

    # error handling
    if response.status_code != 200:
        raise Exception(response.text)
    
    # parse and return data
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

    # error handling
    if response.status_code != 200:
        raise Exception(response)
    
    # parse and return data
    markets_info = json.loads(response.text)

    return markets_info    


def get_market_information(market_ticker:str) -> dict:
    """
    gets data about a market from its ticker
    this is very general and will be used for any web UI i make in the future
    """

    path = f"/markets/{market_ticker}"
    response = send_api_request(method="GET", api_path=path)

    # error handling
    if response.status_code != 200:
        raise Exception(response)
    
    # parse and return data
    market_info = json.loads(response.text)
    return market_info


def get_market_order_book(market_ticker:str) -> dict:
    """
    gets the live order book for a specific ticker
    """

    path = f"/markets/{market_ticker}/orderbook"
    response = send_api_request(method="GET", api_path=path)

    # error handling
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

    # get trade history for given market
    response = send_api_request(method="GET", api_path=path)

    # error handling
    if response.status_code != 200:
        raise Exception(response)

    # parse and return data
    trades_dict = json.loads(response.text)
    return trades_dict


#################################
#  FUNCTIONS: post/del methods  #
#  includes put/cancel orders   #
#################################

def place_order(
    market_ticker: str,
    side: str,
    ctx: int,
    bid_px: int,
) -> dict:
    path = "/portfolio/orders"

    payload = {
        "ticker": market_ticker,
        "side": side,
        "action": "buy",
        "count": ctx,
        "type": "limit",
        "yes_price" if side == "yes" else "no_price": bid_px,
        "cancel_order_on_pause": False,
    }

    response = send_api_request(method="POST", api_path=path, payload=payload)

    if response.status_code != 201:
        print(f"error in place_order() status={response.status_code}")
        print(response.text)
        raise Exception(response)

    order_response_dict = json.loads(response.text)

    print(f"{market_ticker} {side} | {ctx} ctx @ {bid_px} created in {env}")
    return order_response_dict.get("order", order_response_dict)


def amend_order(
    order_id: str,
    market_ticker: str,
    ctx: int,
    bid_px: int,
    side: str,
) -> dict:
    path = f"/portfolio/orders/{order_id}/amend"

    payload = {
        "ticker": market_ticker,
        "side": side,
        "action": "buy",
        "count": ctx,
        "yes_price" if side == "yes" else "no_price": bid_px,
    }

    response = send_api_request(method="POST", api_path=path, payload=payload)

    if response.status_code != 200:
        error_dict = json.loads(response.text)
        if error_dict["code"] != "AMEND_ORDER_NO_OP":
            print(f"error in amend_order() status={response.status_code}")
            print(error_dict)
            raise Exception(response)

    print(f"{market_ticker} {side} | amended in {env} to {ctx} ctx @ {bid_px}")

    order_response_dict = json.loads(response.text)
    return order_response_dict.get("order", order_response_dict)


def cancel_order(order_id: str, market_ticker:str="", side:str="") -> dict:
    # temporary debug — call this before cancel
    resting = get_portfolio_orders(status="resting")
    resting_ids = [o["order_id"] for o in resting.get("orders", [])]
    
    path = f"/portfolio/orders/{order_id}"

    response = send_api_request(method="DELETE", api_path=path)
    response_text = json.loads(response.text)

    if response.status_code != 200:
        print(f"{market_ticker} {side} | FAILED TO CANCEL in {env}")
        print(f"error in cancel_order() status={response.status_code}")
        pprint(response_text)
        raise Exception(response)
    
    print(f"{market_ticker} {side} | canceled in {env}")

    return response_text


if __name__ == "__main__":
    ticker = "KXMLBGAME-26MAY211840ATLMIA-ATL"
    order = place_order(
        market_ticker=ticker,
        side="yes",
        ctr_count=10,
        bid_px=10
    )
    order_id = order.get("order_id")
    print(f"placed: {order_id} | status: {order.get('status')} | px: {order.get('yes_price_dollars')}")

    time.sleep(2)

    amended = amend_order(
        order_id=order_id,
        market_ticker=ticker,
        count=5,
        bid_px=5,
        side="yes"
    )
    print(f"amended: px={amended.get('yes_price_dollars')} | remaining={amended.get('remaining_count_fp')}")

    time.sleep(2)

    # cancelled = cancel_order(order_id=order_id)
    # print(f"cancelled: {cancelled}")