############################
#  core/classes/market.py. #
############################
import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, Callable, List
from pprint import pprint

# local
from core.classes.order import Order
from core.enums import TradingVenue, OrderStatus
import scripts.utils as utils
from core.thread_bridge import emit_ui_update
from scripts.db_wrapper.db_operations import insert_trade, insert_market_position
from scripts.api_external.pushover_wrapper import send_notification


###############
#  CONSTANTS  #
###############
MIN_BID_BELOW_VEGAS = .02 # minimum cents from vegas bid
MAX_BID_ABOVE_VEGAS = .00 # minimum cents from vegas bid
KALSHI_ORDER_SKEW = 0
LEAGUE_IDS, MARKET_TYPES = utils.load_universe()


########################
#   CLASS DECLARATION  #
########################
@dataclass
class Market:
    # generic static data
    is_strike: bool # market is a strike market (i.e. some number target)
    is_team: bool # market has to do with a team (i.e. moneyline/spread ... vs "game total" would be false)
    team_is_p1: bool|None

    # kalshi static data
    kalshi_ticker: str
    kalshi_event_ticker: str
    kalshi_league_id: str
    kalshi_market_type: str
    kalshi_p1_abbr: str
    kalshi_p2_abbr: str
    kalshi_p1_name: str
    kalshi_p2_name: str

    # boltodds static data
    boltodds_id: str # game ticker
    boltodds_market_type: str
    boltodds_market_ticker: str
    boltodds_league_id: str
    boltodds_p1_name: str
    boltodds_p2_name: str

    # market config
    game_description: str
    rules_primary: str
    strike_type: str
    floor_strike: int | None

    # kalshi live data
    kalshi_yes_best_bid: float = 0.0
    kalshi_no_best_bid: float = 0.0
    kalshi_yes_best_bid_ctx: float = 0.0
    kalshi_no_best_bid_ctx: float = 0.0
    kalshi_trades: List[dict] = field(default_factory=list)
    kalshi_last_px: float = 0.0
    kalshi_volume: float = 0.0
    kalshi_last_update: float = 0.0
    kalshi_last_trade_time: int = 0
    kalshi_trades_count: int = 0

    # boltodds live data
    vegas_yes_bid: int = None
    vegas_no_bid: int = None
    boltodds_last_update: int = 0

    # positions
    position_ctx: float = 0.0
    max_position_ctx: float = 0.0
    realized_pnl: float = 0.0
    trading_fees_paid: float = 0.0
    position_fee_cost: float = 0.0    # from position_fee_cost_dollars
    bot_volume: float = 0.0
    cost_basis: float = 0.0
    cost_basis_per_share: float = 0.0
    cumulative_ev: float = 0.0

    # orders — set in __post_init__
    trading_venue: TradingVenue = TradingVenue.NONE
    yes_order: Optional[Order] = field(init=False, default=None)
    no_order: Optional[Order] = field(init=False, default=None)

    def __post_init__(self):
        self.yes_order = Order(
            kalshi_market_ticker=self.kalshi_ticker,
            side="yes",
            trading_venue=self.trading_venue
        )
        self.no_order = Order(
            kalshi_market_ticker=self.kalshi_ticker,
            side="no",
            trading_venue=self.trading_venue
        )


    ###############################
    #  METHODS: read object data  #
    ###############################
    def to_dict(self) -> dict:
        return {
            # generic static
            "is_strike": self.is_strike,
            "is_team": self.is_team,
            "team_is_p1": self.team_is_p1,

            # kalshi static
            "kalshi_ticker": self.kalshi_ticker,
            "kalshi_event_ticker": self.kalshi_event_ticker,
            "kalshi_league_id": self.kalshi_league_id,
            "kalshi_market_type": self.kalshi_market_type,
            "kalshi_p1_abbr": self.kalshi_p1_abbr,
            "kalshi_p2_abbr": self.kalshi_p2_abbr,
            "kalshi_p1_name": self.kalshi_p1_name,
            "kalshi_p2_name": self.kalshi_p2_name,

            # boltodds static
            "boltodds_id": self.boltodds_id,
            "boltodds_market_type": self.boltodds_market_type,
            "boltodds_market_ticker": self.boltodds_market_ticker,
            "boltodds_league_id": self.boltodds_league_id,
            "boltodds_p1_name": self.boltodds_p1_name,
            "boltodds_p2_name": self.boltodds_p2_name,

            # market config
            "game_description": self.game_description,
            "rules_primary": self.rules_primary,
            "strike_type": self.strike_type,
            "floor_strike": self.floor_strike,
            "trading_venue": self.trading_venue.value,

            # kalshi live
            "kalshi_yes_best_bid": self.kalshi_yes_best_bid,
            "kalshi_no_best_bid": self.kalshi_no_best_bid,
            "kalshi_yes_best_bid_ctx": self.kalshi_yes_best_bid_ctx,
            "kalshi_no_best_bid_ctx": self.kalshi_no_best_bid_ctx,
            "kalshi_last_px": self.kalshi_last_px,
            "kalshi_volume": self.kalshi_volume,
            "kalshi_last_update": self.kalshi_last_update,
            "kalshi_last_trade_time": self.kalshi_last_trade_time,
            "kalshi_trades_count": self.kalshi_trades_count,

            # boltodds live
            "vegas_yes_bid": self.vegas_yes_bid,
            "vegas_no_bid": self.vegas_no_bid,
            "boltodds_last_update": self.boltodds_last_update,

            # position data
            "position_ctx": self.position_ctx,
            "max_position_ctx": self.max_position_ctx,
            "realized_pnl": self.realized_pnl,
            "trading_fees_paid": self.trading_fees_paid,
            "bot_volume": self.bot_volume,
            "cost_basis": self.cost_basis,
            "cost_basis_per_share": self.cost_basis_per_share,
            "cumulative_ev": self.cumulative_ev,

            # orders
            "yes_order": self.yes_order.to_dict(),
            "no_order": self.no_order.to_dict(),
        }


    def get_inverse_market_boltodds_ticker(self) -> str|None:
        """
        gets boltodds ticker for "inverse market":
        - this should only be called for moneyline markets (NO STRIKE)
        - same game, same market type, opposite team!
        only returns ticker if 
        """

        if not self.is_team:
            return None
        
        # if market is_team, generate inverse market boltodds ticker
        inv_boltodds_ticker = self.boltodds_id + "/" + self.boltodds_market_type
        inv_boltodds_ticker += "/" + (
            self.boltodds_p2_name if self.team_is_p1 else self.boltodds_p1_name
        )
        
        return inv_boltodds_ticker


    ############################
    #  METHODS: trading logic  #
    ############################

    def _evaluate_bid(self, is_yes:bool) -> tuple[int,int]:
        """
        evaluates trading decision in "yes" market (buy only)
        NOTE this is the function that determines the logic of the bot
        returns px, cts of yes market
        """
        
        vegas_bid = self.vegas_yes_bid if is_yes else self.vegas_no_bid
        if vegas_bid is None:
            return 0, 0

        max_bid = vegas_bid
        min_bid = vegas_bid - MIN_BID_BELOW_VEGAS
        best_bid = self.kalshi_yes_best_bid if is_yes else self.kalshi_no_best_bid

        bid_px = max(min_bid, min(max_bid, best_bid))
        bid_px = max(bid_px - KALSHI_ORDER_SKEW, 0) # skew to be safe here TODO delete in prod
        bid_px = round(bid_px, 2) # round to 2 for now

        side_ctx = max(0, self.position_ctx if is_yes else -self.position_ctx)
        bid_ctx = max(0, self.max_position_ctx - side_ctx)

        return bid_px, bid_ctx


    async def _update_orders(self):
        """
        handler for updating kalshi orders
        - evaluate yes/no prices/sizes given most recent data
        - push updates to kalshi api
        - emit event if price changed
        """

        # evaluate yes/no px
        yes_px, yes_ctx = self._evaluate_bid(is_yes=True)
        no_px, no_ctx = self._evaluate_bid(is_yes=False)


        yes_result, no_result = await asyncio.gather(
            self.yes_order.update(px=yes_px, ctx=yes_ctx),
            self.no_order.update(px=no_px, ctx=no_ctx)
        )

        emit_ui_update("market_update", self.to_dict())


    def handle_data_update(self):
        """
        called post data update on market attrs
        """
        asyncio.create_task(self._update_orders())


    async def _update_trading_venue(self, venue:str) -> None:
        """
        async .. updates trading venues for yes and no markets
        this acts as "switch on" from test/None markets to actual placing orders in kalshi
        """

        # set venue
        self.trading_venue = TradingVenue(venue)

        # set venue for order objs
        yes_result, no_result = await asyncio.gather(
            self.yes_order.set_trading_venue(trading_venue=self.trading_venue),
            self.no_order.set_trading_venue(trading_venue=self.trading_venue)
        )
        await self._update_orders()

        emit_ui_update("market_update", self.to_dict())


    def handle_trading_venue_update(self, trading_venue:str) -> None:
        """
        "fires and forgets" to update the trading venue in market order objects
        """
        asyncio.create_task(self._update_trading_venue(trading_venue))


    def handle_fill(self, msg:dict) -> None:
        """
        handles fill of order
        - changes position_ctx of market (+ for long, - for short)
        - updates yes/no orders to change sizes, skew px (TODO implement)
        - logs filled order (trade) to database
        """

        trade_ctx = msg["count_fp"]
        trade_yes_px = msg["yes_price_dollars"]
        trade_time_ms = msg["ts_ms"]
        fee = msg["fee_cost"]
        side = msg["purchased_side"]
        trade_px = float(trade_yes_px) if side == "yes" else round(1-float(trade_yes_px), 4)
        subaccount = msg["subaccount"]
        position = float(msg["post_position_fp"])

        trade_ev = Market.compute_ev(msg, self.vegas_yes_bid, self.vegas_no_bid)
        self.position_ctx = position
        self.cumulative_ev += trade_ev
        self.kalshi_trades_count = self.kalshi_trades_count + 1

        print(f"*** NEW TRADE ***")
        print(f"bought {trade_ctx} {side} ctx of {self.kalshi_ticker} @ {trade_px} (ev={trade_ev:.4f})")
        print(f"new {self.kalshi_ticker} position: {self.position_ctx}")
        print("------------")

        # evaluate new levels
        is_yes = side == "yes"
        _, new_ctx = self._evaluate_bid(is_yes=is_yes)
        order_obj = self.yes_order if is_yes else self.no_order
        order_obj.handle_fill(msg=msg, new_ctx=new_ctx)

        # update opposite order obj to increase # ctx
        inv_new_px, inv_new_ctx = self._evaluate_bid(is_yes=not is_yes)
        inv_order_obj = self.no_order if is_yes else self.yes_order
        asyncio.create_task(inv_order_obj.update(inv_new_px, inv_new_ctx))

        # emit update to UI
        emit_ui_update("market_update", self.to_dict())

        # log to db file to store trades, send push to 
        insert_trade(
            msg=msg,
            kalshi_event_ticker=self.kalshi_event_ticker,
            vegas_yes_bid=self.vegas_yes_bid,
            vegas_no_bid=self.vegas_no_bid,
            trade_px=trade_px,
            ev_dollars=trade_ev
        )

        # send push notificatioin
        pushover_title = f"[benben] kalshi trade — {self.boltodds_league_id} {self.boltodds_market_type}"
        pushover_msg = f"market: {self.kalshi_ticker}\n"
        pushover_msg += f"bought {trade_ctx} {side} @ {trade_px} (ev={trade_ev:.4f})\n"
        pushover_msg += f"new position: {self.position_ctx} ctx\n"
        pushover_msg += f"realized pnl: ${self.realized_pnl:.2f}"
        asyncio.create_task(asyncio.to_thread(
            send_notification,
            title=pushover_title,
            msg=pushover_msg,
            priority=0,
        ))


    def compute_ev(msg:dict, vegas_yes_bid:float, vegas_no_bid:float) -> float | None:
        """
        calculates expected value of a trade based off fill px/fee and vegas mid
        """
        if vegas_yes_bid is None or vegas_no_bid is None:
            return None

        side = msg.get("purchased_side")
        yes_px = float(msg.get("yes_price_dollars"))
        count = float(msg.get("count_fp"))
        fee = float(msg.get("fee_cost", 0))

        if side == "yes":
            fill_px = yes_px
            vegas_mid = (vegas_yes_bid + (1 - vegas_no_bid)) / 2
        else:
            fill_px = 1 - yes_px  # convert to no price
            vegas_mid = ((1 - vegas_yes_bid) + vegas_no_bid) / 2  # no-side mid

        fee_per_contract = fee / count if count > 0 else 0
        ev = (vegas_mid - fill_px - fee_per_contract) * count

        return round(ev, 6)


    def handle_market_positions(self, pos_data:dict) -> None:
        """
        handles kalshi ws "market_positions" object
        """

        # print(f"market position for {self.kalshi_ticker}")
        # pprint(pos_data, sort_dicts=False)

        # dict keys shared by ws and rest endpoint json
        self.position_ctx = float(pos_data["position_fp"])
        self.realized_pnl = float(pos_data["realized_pnl_dollars"])
        self.trading_fees_paid = float(pos_data["fees_paid_dollars"])

        # dict keys differ by ws/rest
        vlm_key = "volume_fp" if "volume_fp" in pos_data.keys() else "total_traded_dollars"
        self.bot_volume = float(pos_data.get(vlm_key, 0))

        cost_key = "position_cost_dollars" if "position_cost_dollars" in pos_data.keys() \
                    else "market_exposure_dollars"
        self.cost_basis = float(pos_data.get(cost_key, 0))

        self.cost_basis_per_share = 0 if self.position_ctx == 0 else \
                                    round(self.cost_basis / abs(self.position_ctx),4)

        # emit ui update
        emit_ui_update("market_update", self.to_dict())

        # log market position to db (snapshot)
        insert_market_position(msg=pos_data)

        
    def handle_set_max_position_ctx(self, max_ctx:float) -> None:
        """
        handles update to "max_position_ctx" 
        called from gui
        """

        self.max_position_ctx = max_ctx
        self.handle_data_update()
