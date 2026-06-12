#########################
#  core/classes/bot.py  #
#########################

import asyncio
import time
import re
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, Callable, List
from pprint import pprint
import traceback
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

# local
from core.classes.market import Market
import scripts.utils as utils
from scripts.api_external.kalshi_api_wrapper import get_portfolio_positions
from core.thread_bridge import emit_ui_update
from scripts.db_wrapper.db_operations import (
    insert_event, get_unsettled_traded_tickers, insert_settlement
)
from scripts.api_external.kalshi_api_wrapper import get_portfolio_settlements, KALSHI_SUBACCOUNT


# CONSTANTS
LEAGUE_IDS, MARKET_TYPES = utils.load_universe()
DEFAULT_MAX_POSITION_CTX = 10.0
DEFAULT_MAX_SKEW_BELOW_VEGAS = 0.03
DEFAULT_MAX_SKEW_ABOVE_VEGAS = 0.00
BOLTODDS_MAX_LEAGUES = 1
BOLTODDS_MAX_MARKET_TYPES = 1


@dataclass
class Bot:
    # id/info about game the bot is trading
    kalshi_event_ticker: str = ""
    boltodds_event_id:str = ""
    markets: Dict = field(default_factory=dict)
    markets_by_boltodds: Dict = field(default_factory=dict)
    events: Dict = field(default_factory=dict)
    
    # flag for whether the bot should be actively trading or not
    ws_subscribed: bool = False

    # ws client refreences
    kalshi_ws_client = None
    boltodds_client = None

    # settings
    default_max_position_ctx = DEFAULT_MAX_POSITION_CTX
    default_max_skew_below_vegas = DEFAULT_MAX_SKEW_BELOW_VEGAS
    default_max_skew_above_vegas = DEFAULT_MAX_SKEW_ABOVE_VEGAS

    # -------- ws declarations --------#
    def set_clients(self, kalshi_ws_client=None, boltodds_client=None):
        """
        defines ws client objects (to send data)
        """
        self.kalshi_ws_client = kalshi_ws_client
        self.boltodds_client = boltodds_client


    def _subscribe_tickers_ws(self, kalshi_market_tickers: list,
                               boltodds_ids: list, boltodds_market_types: list,
                               boltodds_leagues:list):
        if self.kalshi_ws_client:
            self.kalshi_ws_client.resubscribe(kalshi_market_tickers)

        if self.boltodds_client:
            self.boltodds_client.subscribe(game_ids=boltodds_ids, markets=boltodds_market_types, leagues=boltodds_leagues)

    # ----- misc functions --------#
    def _write(self, text:str) -> None:
        """ for printing to terminal """
        current_unix = int(time.time())
        print(f"from BOT: {text}")
        print(f"(at {current_unix})")
        print("-----------------------")


    # -------- bot settings getters/setters ----------- #
    def set_default_max_position_ctx(self, ctx:float):
        if ctx <= 0:
            print(f"cannot set default max position ctx below zero")
            return
        
        self.default_max_position_ctx = ctx


    def get_default_max_position_ctx(self):
        return self.default_max_position_ctx


    def set_max_vegas_skews(self, skew_below:float=None, skew_above:float=None):
        if skew_below is not None:
            self.default_max_skew_below_vegas = skew_below
        if skew_above is not None:
            self.default_max_skew_above_vegas = skew_above


    def get_max_vegas_skews(self):
        return self.default_max_skew_below_vegas, self.default_max_skew_above_vegas
    

    def handle_set_setting(self, key:str, value:str) -> None:
        if key == "max_skew_below":
            self.set_max_vegas_skews(skew_below=value)
        elif key == "max_skew_above":
            self.set_max_vegas_skews(skew_above=value)
        elif key == "default_max_position_ctx":
            self.set_default_max_position_ctx(value)


    # -------- markets functions ----------- #
    def remove_all_markets(self):
        "to unsubscribe from all markets"
        ws_subscribed = False
        self.markets.clear()

        # unsubscribe from ws
        self.kalshi_ws_client.unsubscribe_all()
        self.boltodds_client.subscribe(game_ids=[], markets=[], leagues=[])


    def _get_market_by_kalshi_ticker(self, kalshi_ticker:str) -> Market|None:
        return self.markets.get(kalshi_ticker)


    def _get_market_by_boltodds_ticker(self, boltodds_ticker:str) -> Market:
        return self.markets_by_boltodds.get(boltodds_ticker)


    def _set_markets_new_event(self, event_static_data:dict, kalshi_markets_data:list) -> list[Market]:
        """
        sets new markets to subscribe to ws objects and trade
        """

        market_type = event_static_data["market_type"]
        market_is_strike = MARKET_TYPES[market_type]["is_strike"]
        market_is_team = MARKET_TYPES[market_type]["is_team"]

        boltodds_market_type = MARKET_TYPES[market_type]["boltodds"]
        boltodds_league_id = LEAGUE_IDS[event_static_data["league"]]["boltodds"]
        boltodds_ticker_root = event_static_data["boltodds_id"] + "/" + boltodds_market_type

        market_objs = []
        for kalshi_mkt_dict in kalshi_markets_data:
            kalshi_market_ticker = kalshi_mkt_dict["ticker"]
            # create boltodds ticker
            boltodds_ticker = boltodds_ticker_root
            team_is_p1 = None
            if market_is_team:
                ticker_last_part = kalshi_market_ticker.split("-")[-1]
                ticker_last_part_team = re.sub(r'\d+', '', ticker_last_part)
                kalshi_p1_abbr = event_static_data["kalshi_p1_abbr"]
                team_is_p1 = kalshi_p1_abbr == ticker_last_part_team
                mkt_boltodds_name = event_static_data["boltodds_p1_name" if team_is_p1 else "boltodds_p2_name"]
                boltodds_ticker += ("/" + mkt_boltodds_name)
            if market_is_strike:
                boltodds_ticker += ("/" + str(kalshi_mkt_dict["floor_strike"]))
            
            market_obj = Market(
                # settings
                max_skew_below_vegas=self.default_max_skew_below_vegas,
                max_skew_above_vegas=self.default_max_skew_above_vegas,

                # static data
                is_team=market_is_team,
                team_is_p1 = team_is_p1 if market_is_team else None,
                is_strike=market_is_strike,

                # kalshi static
                kalshi_ticker=kalshi_market_ticker,
                kalshi_event_ticker=event_static_data["kalshi_event_ticker"],
                kalshi_league_id=event_static_data["kalshi_league_id"],
                kalshi_market_type=event_static_data["kalshi_market_type"],   # fixed: removed trailing comma in key
                kalshi_p1_abbr=event_static_data["kalshi_p1_abbr"],
                kalshi_p2_abbr=event_static_data["kalshi_p2_abbr"],
                kalshi_p1_name=event_static_data["kalshi_p1_name"],
                kalshi_p2_name=event_static_data["kalshi_p2_name"],

                # boltodds static
                boltodds_id=event_static_data["boltodds_id"],
                boltodds_market_type=boltodds_market_type,
                boltodds_market_ticker=boltodds_ticker,
                boltodds_league_id=boltodds_league_id,   # fixed: pull from data
                boltodds_p1_name=event_static_data["boltodds_p1_name"],       # fixed: was dboluplicated
                boltodds_p2_name=event_static_data["boltodds_p2_name"],

                game_description=f"{kalshi_mkt_dict['title']} - {kalshi_mkt_dict['yes_sub_title']}?",
                rules_primary=kalshi_mkt_dict["rules_primary"],
                strike_type=kalshi_mkt_dict["strike_type"],
                floor_strike=kalshi_mkt_dict.get("floor_strike", None),

                kalshi_yes_best_bid=float(kalshi_mkt_dict["yes_bid_dollars"]),
                kalshi_no_best_bid=float(kalshi_mkt_dict["no_bid_dollars"]),
                kalshi_last_px=kalshi_mkt_dict["last_price_dollars"],
                kalshi_last_update=utils.get_unix_timestamp(minutes_ago=0),

                max_position_ctx=DEFAULT_MAX_POSITION_CTX
            )

            # store market object by refernece in lookup table(s)
            market_objs.append(market_obj)
            self.markets[kalshi_market_ticker] = market_obj
            self.markets_by_boltodds[boltodds_ticker] = market_obj

        return market_objs


    async def _set_positions_new_event(self, event_ticker:str) -> None:
        print("SETTING NEW POSITIONS")
        
        positions = await asyncio.to_thread(
            get_portfolio_positions,
            event_ticker=event_ticker
        )

        market_positions = positions["market_positions"]
        for pos in market_positions:
            kalshi_market_ticker = pos["ticker"]
            mkt:Market = self._get_market_by_kalshi_ticker(kalshi_market_ticker)
            
            if mkt is None:
                continue

            mkt.handle_market_positions(pos)


    def get_all_markets_dicts_list(self) -> list[dict]:
        """
        EXTERNAL FUNCTION
        gets all kalshi market objects, puts in dict form
        """

        markets_list = []
        for m in self.markets.values():
            markets_list.append(m.to_dict())

        return sorted(markets_list, key=lambda m: m["kalshi_ticker"])


    def _get_markets_for_boltodds_ws_data(self, bo_data:dict) -> Market:
        """
        this method returns the market to update when receiving boltodds line update
        takes into account game id, market, and strike (if there)
        TODO would like to rebuild the kalshi ticker from the data, but oh well
        """

        markets_objs_list = []

        # format boltodds ticker
        boltodds_id = bo_data["game"]
        outcomes = bo_data["outcomes"]

        for _, v in outcomes.items():
            boltodds_market_type = v["outcome_name"]
            market_team = v["outcome_target"]

            # find if market is a team market
            market_type = utils.get_market_type_by_boltodds_market_type(boltodds_market_type)
            market_is_team = MARKET_TYPES[market_type]["is_team"]
            market_is_strike = MARKET_TYPES[market_type]["is_strike"]

            # create boltodds ticker
            boltodds_ticker = boltodds_id + "/" + boltodds_market_type
            
            if market_type in ["spread", "f5_spread"]:
                # logic for determining target team (always the minus line ... 
                # as kalshi spread mkts always xyz team "win by more")
                outcome_line = float(v["outcome_line"])
                if outcome_line < 0:
                    boltodds_ticker += "/" + market_team
                    boltodds_ticker += "/" + str(-outcome_line)
                else: # if spread line is positive, it is actually a bid market for other team
                    bo_home = bo_data["home_team"]
                    bo_away = bo_data["away_team"]
                    inverse_team = bo_home if market_team == bo_away else bo_away
                    boltodds_ticker += "/" + inverse_team
                    boltodds_ticker += "/" + str(v["outcome_line"])
            
            else: # market type is not spread
                if market_is_team:
                    boltodds_ticker += ("/" + market_team)
                if market_is_strike:
                    boltodds_ticker += "/" + str(v["outcome_line"])

            # append market objs to list
            market_obj:Market = self._get_market_by_boltodds_ticker(boltodds_ticker)

            markets_objs_list.append(market_obj)


        return markets_objs_list


    def get_markets(self) -> Dict[str, Market]:
        return self.markets
    

    def get_all_markets_kalshi_tickers(self) -> list[str]:
        return list(self.markets.keys())        


    def set_market_max_position_ctx(self, kalshi_market_ticker:str, ctx:float) -> None:
        """
        sets max_position_ctx on a market
        called through GUI
        """
        mkt = self._get_market_by_kalshi_ticker(kalshi_market_ticker)

        if mkt is None:
            print(f"attempted to change max_position_ctx for mkt {kalshi_market_ticker}, not found")
            return
        
        mkt.handle_set_max_position_ctx(ctx)


    def cancel_all_kalshi_orders(self) -> None:
        """
        cancels all orders outstanding on kalshi
        i.e. sets all markets trading venue to None
        """
        for ticker, mkt in self.markets.items():
            mkt: Market
            mkt.handle_trading_venue_update("none")


    async def reconcile_settlements(self) -> None:
        """
        called on startup or manually from GUI.
        fetches settlements for any traded markets not yet in the db.
        idempotent — safe to call multiple times.
        """
        since_ts_ms = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)
        unsettled_tickers = get_unsettled_traded_tickers(since_ts_ms=since_ts_ms)

        if not unsettled_tickers:
            print("[reconcile_settlements] nothing to reconcile")
            return

        print(f"[reconcile_settlements] reconciling {len(unsettled_tickers)} tickers")

        for ticker in unsettled_tickers:
            try:
                result = await asyncio.to_thread(get_portfolio_settlements, ticker=ticker)
                for s in result.get("settlements", []):
                    insert_settlement(s)
                print(f"[reconcile_settlements] {ticker} done")
            except Exception as e:
                print(f"[reconcile_settlements] error on {ticker}: {e}")

        print(f"[reconcile_settlements] complete")

    # ----- events: getters/setters -------- #
    def get_all_events_list(self) -> dict:
        events_list = []
        for k, evt in self.events.items():
            events_list.append({
                "kalshi_event_ticker": k,
                "boltodds": evt["boltodds"],
                "kalshi_market_tickers": [
                    mkt.kalshi_ticker for mkt in evt["market_objects"]
                ]
            })

        return events_list


    def get_events_boltodds_leagues(self) -> list:
        return list({
            evt["boltodds"]["league"]
            for evt in self.events.values()
        })


    def get_events_boltodds_market_types(self) -> list:
        return list({
            evt["boltodds"]["market_type"]
            for evt in self.events.values()
        })


    def add_new_event(self, event_static_data:dict, kalshi_markets_data:list) -> None:
        """
        sets a new event; this function is called from GUI
        """

        boltodds_league = event_static_data["boltodds_league_id"]
        boltodds_market_type = event_static_data["boltodds_market_type"]

        # VALIDATE whether can subscribe
        events_leagues = self.get_events_boltodds_leagues()
        if boltodds_league not in events_leagues and (len(events_leagues) + 1) > BOLTODDS_MAX_LEAGUES:
            print(f"boltodds leagues count will be exceeded. cannot add event.")
            return
        
        events_market_types = self.get_events_boltodds_market_types()
        if boltodds_market_type not in events_market_types and \
        (len(events_market_types)) + 1 > BOLTODDS_MAX_MARKET_TYPES:
            print(f"boltodds market types count will be exceeded. cannot add event.")
            return
    

        # create markets array from kalshi data passed
        market_objs = self._set_markets_new_event(
            event_static_data,
            kalshi_markets_data,
        )

        # set events
        kalshi_event_ticker = event_static_data["kalshi_event_ticker"]
        self.events[kalshi_event_ticker] = {
            "kalshi_event_ticker": kalshi_event_ticker,
            "boltodds": {
                "game_id": event_static_data["boltodds_id"],
                "league": boltodds_league,
                "market_type": boltodds_market_type
            },
            "market_type": event_static_data["market_type"],
            "league": event_static_data["league"],
            "market_objects": market_objs
        }

        # call kalshi to get exisitng market positions
        asyncio.create_task(self._set_positions_new_event(event_ticker=kalshi_event_ticker))

        # update subscriptions
        self._resubscribe_events()

        # log event creation to db
        insert_event(
            "add",
            kalshi_event_ticker=event_static_data["kalshi_event_ticker"],
            boltodds_id=event_static_data["boltodds_id"],
            market_type=event_static_data["market_type"],
            league=event_static_data["league"]
        )


    def remove_event(self, kalshi_event_ticker:str) -> None:
        """
        removed event from bot, cancels outstanding orders, etc
        """
        if kalshi_event_ticker not in list(self.events.keys()):
            print(f"attempted to remove event {kalshi_event_ticker}, not in bot.events (doing nothing)")

        # first, remove from events and refresh ws subscriptions so no new data comes in
        event_dict = self.events.pop(kalshi_event_ticker)
        
        market_objs = event_dict["market_objects"]
        for mkt in market_objs:
            mkt:Market
            mkt.handle_trading_venue_update("none") # set venue to none, cancels ordres on kalshi
            
            self.markets.pop(mkt.kalshi_ticker, None)
            self.markets_by_boltodds.pop(mkt.boltodds_market_ticker, None)

        self._resubscribe_events()

        insert_event(
            "remove",
            kalshi_event_ticker=kalshi_event_ticker,
            boltodds_id=event_dict["boltodds"]["game_id"],
            market_type=event_dict["market_type"],
            league=event_dict["league"]
        )


    def _resubscribe_events(self) -> None:
        """
        gets current events/markets, resubscribe to kalshi ws and boltodds
        """

        kalshi_market_tickers = list(self.markets.keys())
        boltodds_game_ids = []
        boltodds_market_types = []
        market_objects = []
        boltodds_leagues = []
        for k, evt in self.events.items():
            boltodds_game_id = evt["boltodds"]["game_id"]
            boltodds_market_type = evt["boltodds"]["market_type"]
            boltodds_league = evt["boltodds"]["league"]
            if boltodds_game_id not in boltodds_game_ids:
                boltodds_game_ids.append(boltodds_game_id)
            if boltodds_market_type not in boltodds_market_types:
                boltodds_market_types.append(boltodds_market_type)
            if boltodds_league not in boltodds_leagues:
                boltodds_leagues.append(boltodds_league)
        
        self._subscribe_tickers_ws(
            kalshi_market_tickers=kalshi_market_tickers,
            boltodds_ids=boltodds_game_ids,
            boltodds_market_types=boltodds_market_types,
            boltodds_leagues=boltodds_leagues
        )


    def set_market_trading_venue(self, kalshi_market_ticker:str, trading_venue:str) -> None:
        """
        sets the trading venue for kalshi market ticker (called from bot_loop via website GUI)
        """
        mkt = self._get_market_by_kalshi_ticker(kalshi_market_ticker)
        mkt.handle_trading_venue_update(trading_venue)


    # ------ kalshi websocket handlers (update state) --------#
    def _handle_kalshi_ws_ticker(self, msg:dict) -> None:
        """ updates market object, handles 'ticker' event """
        ticker = msg.get("market_ticker")
        
        # stale ticker check
        if ticker not in list(self.markets.keys()):
            print(f"ignored stale ticker event received for {ticker} market")
            return
        
        mkt = self._get_market_by_kalshi_ticker(ticker)

        # update market state
        mkt.kalshi_yes_best_bid = float(msg["yes_bid_dollars"])
        mkt.kalshi_no_best_bid = round(1 - float(msg["yes_ask_dollars"]),2)
        mkt.kalshi_yes_best_bid_ctx = float(msg["yes_bid_size_fp"])
        mkt.kalshi_no_best_bid_ctx = float(msg["yes_ask_size_fp"])
        mkt.kalshi_last_px = float(msg["price_dollars"])
        mkt.kalshi_volume = float(msg["volume_fp"])
        mkt.kalshi_last_update = msg["ts_ms"] # in ms

        # update order prices based on new market data
        mkt.handle_data_update()

        # emit new information to trades webpage via websocket
        mkt_dict = mkt.to_dict()
        emit_ui_update("market_update", mkt_dict)


    def _handle_kalshi_ws_trade(self, msg:dict) -> None:
        ticker = msg.get("market_ticker")
        mkt = self._get_market_by_kalshi_ticker(ticker)

        if mkt is None:
            print(f"received kalshi ws trade for unknown market {ticker}")

        old_last_px = mkt.kalshi_last_px
        
        # update market state
        mkt.kalshi_last_px = float(msg["yes_price_dollars"])
        mkt.kalshi_last_trade_time = int(msg["ts_ms"])


        # emit new information to UI via websocket
        mkt_dict = mkt.to_dict()
        emit_ui_update("market_update", mkt_dict)


    def _handle_kalshi_ws_fill(self, msg: dict) -> None:
        print("=== KALSHI ORDER FILL ===")
        pprint(msg, sort_dicts=False)
        
        ticker = msg["market_ticker"]
        mkt = self._get_market_by_kalshi_ticker(ticker)

        if mkt is None:
            print(f"received fill for {mkt}, but not recognized in Market objects (doing nothing)")
            return

        print(f"in bot._handle_kalshi_ws_fill() ... market filled: {mkt.kalshi_ticker}")


        mkt.handle_fill(msg)

    
    def _handle_kalshi_ws_market_positions(self, msg:dict) -> None:
        """
        handles "market positions" ws object
        provides position on startup and when position changes (on fill)
        """
        ticker = msg["market_ticker"]
        mkt = self._get_market_by_kalshi_ticker(ticker)

        if mkt is None:
            print(f"received market_position for {mkt}, but not recognized in Market objects (doing nothing)")
            return
        
        mkt.handle_market_positions(msg)


    def _handle_kalshi_ws_market_lifecycle(self, msg: dict) -> None:
        """
        handles market_lifecycle_v2 ws events.
        on settled/canceled: stops trading, flags the market, records settlement.
        market stays in bot.events for UI visibility and settlement tracking.
        """
        ticker = msg.get("market_ticker")
        status = msg.get("status")

        if ticker is None or status is None:
            return

        mkt = self._get_market_by_kalshi_ticker(ticker)
        if mkt is None:
            print(f"[lifecycle] received {status} for unknown market {ticker} — ignoring")
            return

        print(f"[lifecycle] {ticker} → {status}")

        if status == "settled":
            mkt.is_settled = True
            mkt.handle_trading_venue_update("none")
            asyncio.create_task(self._reconcile_single_ticker(ticker))
            emit_ui_update("market_update", mkt.to_dict())

        elif status in ("canceled", "voided"):
            mkt.is_canceled = True
            mkt.handle_trading_venue_update("none")
            emit_ui_update("market_update", mkt.to_dict())

        elif status == "closed":
            # market stopped accepting new orders but not yet settled
            # cancel resting orders but don't flag as settled yet
            mkt.handle_trading_venue_update("none")
            emit_ui_update("market_update", mkt.to_dict())


    async def _reconcile_single_ticker(self, ticker: str) -> None:
        """
        fetches and stores settlement record for a single ticker.
        called immediately when lifecycle event fires for a settled market.
        """
        try:
            result = await asyncio.to_thread(get_portfolio_settlements, ticker=ticker)
            for s in result.get("settlements", []):
                insert_settlement(s)
            print(f"[lifecycle] settlement recorded for {ticker}")
        except Exception as e:
            print(f"[lifecycle] error reconciling {ticker}: {e}")


    def handle_kalshi_ws_data(self, kalshi_data: dict) -> None:
        data_type = kalshi_data.get("type")
        data_msg = kalshi_data.get("msg")

        try:
            if data_type == "ticker":
                self._handle_kalshi_ws_ticker(data_msg)
            elif data_type == "trade":
                self._handle_kalshi_ws_trade(data_msg)
            elif data_type == "fill":
                self._handle_kalshi_ws_fill(data_msg)
            elif data_type == "market_position":
                self._handle_kalshi_ws_market_positions(data_msg)
            elif data_type == "subscribed":
                self._write(f"subscribed to kalshi data. channels: {data_msg.get('channel')}")
            elif data_type == "unsubscribed":
                self._write(f"unsubscribed from kalshi channels")
            elif data_type == "ok":
                tickers = kalshi_data.get("market_tickers", [])
                self._write(f"kalshi ok ack for {len(tickers)} markets")
            elif data_type == "market_lifecycle_v2":
                self._handle_kalshi_ws_market_lifecycle(data_msg)
            else:
                print(f"received kalshi ws data with type {data_type} (doing nothing)")

        except Exception as e:
            print(f"error handling kalshi ws data (type={data_type}):")
            print(f"raw message: {kalshi_data}")
            traceback.print_exc()
            # swallow exception — WS stays connected


    # ------ boltodds websocket handlers (update state) --------#
    def _handle_boltodds_odds_update(self, msg:dict) -> None:
        """
        updates market boltodds_... attrs for new boltodds odds updates ws data
        """
        market_objs = self._get_markets_for_boltodds_ws_data(msg)
        outcomes_dict = msg["outcomes"]

        # update vegas odds for each market via boltodds
        for v, market_obj in zip(outcomes_dict.values(), market_objs):
            market_obj: Market
            
            if market_obj is None:
                continue

            vegas_px, is_offer = utils.determine_bot_market_vegas_offer(v)

            bid_px = None if vegas_px is None else round(1-vegas_px, 2)
    
            if is_offer:
                market_obj.vegas_no_bid = bid_px
            else: # is_offer == False, so this is bid px
                market_obj.vegas_yes_bid = bid_px
        
            # if market moneyline/set winner, update the inverse market (other team opposite market)
            if market_obj.boltodds_market_type in ["Moneyline", "S1 Moneyline", "S2 Moneyline"]:
                inv_market_boltodds_ticker = market_obj.get_inverse_market_boltodds_ticker()
                inv_market_obj = self._get_market_by_boltodds_ticker(inv_market_boltodds_ticker)
                if is_offer:
                    inv_market_obj.vegas_yes_bid = bid_px
                else:
                    inv_market_obj.vegas_no_bid = bid_px

            # update timestamp of last update
            market_obj.boltodds_last_update = int(time.time() * 1000)

            # update my bid prices following updated market state
            market_obj.handle_data_update()


    def _handle_boltodds_line_update(self, msg_dict) -> None:
        pass


    def _handle_boltodds_game_update(self, msg_dict) -> None:
        pass


    def handle_boltodds_data(self, boltodds_data:dict) -> None:
        """
        handles incoming data from the boltodds websocket
        """

        msg_type = boltodds_data["action"]
        msg_data = boltodds_data.get("data")

        if msg_type == "initial_state" or msg_type == "line_update":
            self._handle_boltodds_odds_update(msg_data)
        elif msg_type == "game_update":
            self._handle_boltodds_game_update(msg_data)
        elif msg_type == "game_removed" or msg_type == "sport_clear" or msg_type == "book_clear":
            # some error where the boltodds data is removed; stop all trading
            print(f"** BOLTODDS REMOVED (msg type {msg_type}), UNSUBSCRIBING ALL **")
            self.remove_all_markets()
        elif msg_type == "socket_connected":
            self._write(f"boltodds websocket connected and established.")
        elif msg_type == "ping":
            pass
            # self._write("boltodds ws pinged")
        elif msg_type == "subscribe":
            self._write(f"subscribed to boltodds ws! msg = {boltodds_data.get('filters')}")
        elif msg_type == "subscription_updated":
            self._write(f"boltodds subscription updated")
        elif msg_type == "error":
            error_msg = boltodds_data.get("message")
            self._write(f"ERROR in boltodds ws: {error_msg}")
            raise Exception(error_msg)
        else:
            self._write(f"unrecognized boltodds action: {msg_type} — ignoring")