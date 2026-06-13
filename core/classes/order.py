import asyncio
import time
from dataclasses import dataclass, field

# local
from scripts.api_external.kalshi_api_wrapper import place_order, amend_order, cancel_order
from core.enums import TradingVenue, OrderStatus
from core.thread_bridge import emit_ui_update
from scripts.db_wrapper.db_operations import insert_order

@dataclass
class Order:
    kalshi_market_ticker: str # never changes
    side: str # never changes
    ctx: float = None
    px: int = None
    trading_venue: TradingVenue = TradingVenue.NONE

    status: OrderStatus = OrderStatus.NONE # enum
    kalshi_order_id: str = None # order id from kalshi
    is_best: bool = False

    # confirmed state on kalshi — only updated on successful api response
    kalshi_px: int = None
    kalshi_ctx: float = None


    def __post_init__(self):
        self.updated_at = time.time()


    #####################
    #  getters/setters  #
    #####################

    def to_dict(self) -> dict:
        return {
            "kalshi_market_ticker": self.kalshi_market_ticker,
            "side": self.side,
            "ctx": self.ctx,
            "px": self.px,
            "trading_venue": self.trading_venue.value,
            "status": self.status.value,
            "kalshi_order_id": self.kalshi_order_id,
            "is_best": self.is_best,
        }

    def get_venue(self) -> str:
        return self.trading_venue.value

    def emit_order_ui_update(self) -> None:
        emit_ui_update(event_type="kalshi_order_update", data=self.to_dict())


    ####################
    #  venue cxn fxns  #
    ####################

    async def update(self, px, ctx) -> None:
        """
        updates contract based off new px and/or ctx.
        compares target against kalshi_px/kalshi_ctx (confirmed kalshi state)
        to determine correct action.
        """
        response = {}
        action = ""

        # if no change from confirmed kalshi state, do nothing
        if px == self.kalshi_px and ctx == self.kalshi_ctx:
            return

        # if any attr is none or zero, just cancel the order (or ignore if no order)
        if px == None or ctx == None or px == 0 or ctx == 0:
            self.px = None
            self.ctx = None

            if self.status == OrderStatus.NONE:
                return

            response = await self.cancel_on_venue()
            action = "cancel"

        # now we know order px and ctx are valid to place

        # if no order exists, place it
        elif self.status == OrderStatus.NONE:
            self.px = px
            self.ctx = ctx
            response = await self.place_on_venue()
            action = "place"

        # if order exists, amend
        elif self.status == OrderStatus.RESTING:
            old_px = self.px
            old_ctx = self.ctx
            self.px = px
            self.ctx = ctx
            response = await self.amend_on_venue(old_px, old_ctx)
            action = "amend"

        else:
            return

        # log to db
        if self.trading_venue != TradingVenue.NONE and response["success"] == True:
            insert_order(
                action=action,
                kalshi_order_id=self.kalshi_order_id,
                kalshi_market_ticker=self.kalshi_market_ticker,
                side=self.side,
                px=self.px,
                ctx=self.ctx,
                status=self.status.value,
            )

        return response


    async def cancel_on_venue(self) -> dict:
        if self.status == OrderStatus.CANCEL_PENDING:
            return {"success": False, "error": "cancel already pending"}

        self.status = OrderStatus.CANCEL_PENDING
        order_id = self.kalshi_order_id

        try:
            if self.trading_venue != TradingVenue.NONE:

                self.emit_order_ui_update()

                print(f"canceling {self.kalshi_market_ticker} (order {self.kalshi_order_id})")

                response = await asyncio.to_thread(
                    cancel_order,
                    order_id=order_id,
                    market_ticker=self.kalshi_market_ticker,
                    side=self.side
                )

                self.status = OrderStatus.NONE
                self.kalshi_order_id = None
                self.px = None
                self.ctx = None
                self.kalshi_px = None
                self.kalshi_ctx = None

                print(f"order {order_id} canceled")
                self.emit_order_ui_update()

                return {"success": True, "order_id": order_id}

            else:
                self.status = OrderStatus.NONE
                self.kalshi_order_id = None
                self.px = None
                self.ctx = None
                self.kalshi_px = None
                self.kalshi_ctx = None
                return {"success": True, "order_id": order_id}

        except Exception as e:
            # 404 = already filled or expired — treat as gone
            print(f"cancel failed for {self.kalshi_market_ticker} {self.side}: \
                  {e} — treating as cancelled")
            self.status = OrderStatus.NONE
            self.kalshi_order_id = None
            self.px = None
            self.ctx = None
            self.kalshi_px = None
            self.kalshi_ctx = None

            self.emit_order_ui_update()

            return {"success": False, "error": str(e)}


    async def place_on_venue(self) -> dict:
        if self.status == OrderStatus.PLACE_PENDING:
            # if in process of placing, don't place another, amend existing
            return await self.amend_on_venue(self.px, self.ctx)

        self.status = OrderStatus.PLACE_PENDING

        try:
            if self.trading_venue != TradingVenue.NONE:

                self.emit_order_ui_update()

                print(f"placing {self.kalshi_market_ticker} (order {self.kalshi_order_id})")

                response = await asyncio.to_thread(
                    place_order,
                    market_ticker=self.kalshi_market_ticker,
                    side=self.side,
                    ctx=self.ctx,
                    bid_px=int(100 * self.px)
                )

                order_id = response.get("order_id")
                order_status = response.get("status")
                remaining = float(response.get("remaining_count") or response.get("remaining_count_fp") or 0)

                if remaining > 0:
                    self.kalshi_order_id = order_id
                    self.status = OrderStatus.RESTING
                    self.kalshi_px = self.px
                    self.kalshi_ctx = self.ctx
                else:
                    self.status = OrderStatus.NONE
                    self.kalshi_px = None
                    self.kalshi_ctx = None

                self.emit_order_ui_update()

                return {"success": True, "status": order_status}

            else:
                self.kalshi_order_id = "internal-xxxxx"
                self.status = OrderStatus.RESTING
                self.kalshi_px = self.px
                self.kalshi_ctx = self.ctx
                return {"success": True, "status": "resting"}

        except Exception as e:
            self.status = OrderStatus.NONE
            self.px = None
            self.ctx = None
            self.kalshi_px = None
            self.kalshi_ctx = None
            print(f"place failed {self.kalshi_market_ticker} {self.side}: {e}")

            self.emit_order_ui_update()

            return {"success": False, "error": str(e)}


    async def amend_on_venue(self, old_px, old_ctx) -> dict:
        if self.status == OrderStatus.CANCEL_PENDING:
            return {"success": False, "error": "cancel pending, cannot amend"}

        self.status = OrderStatus.AMEND_PENDING

        try:
            if self.trading_venue != TradingVenue.NONE:

                self.emit_order_ui_update()

                print(f"amending {self.kalshi_market_ticker} (order {self.kalshi_order_id})")

                response = await asyncio.to_thread(
                    amend_order,
                    order_id=self.kalshi_order_id,
                    market_ticker=self.kalshi_market_ticker,
                    ctx=self.ctx,
                    bid_px=int(100 * self.px),
                    side=self.side
                )

                # NO_OP — kalshi already has this price, confirm and move on
                if response is None:
                    self.status = OrderStatus.RESTING
                    self.kalshi_px = self.px
                    self.kalshi_ctx = self.ctx
                    self.emit_order_ui_update()
                    return {"success": True, "status": "resting"}

                order_status = response.get("status")
                remaining = float(response.get("remaining_count") or response.get("remaining_count_fp") or 0)

                if remaining > 0:
                    self.status = OrderStatus.RESTING
                    self.kalshi_px = self.px
                    self.kalshi_ctx = self.ctx
                else:
                    self.status = OrderStatus.NONE
                    self.kalshi_order_id = None
                    self.kalshi_px = None
                    self.kalshi_ctx = None

                self.emit_order_ui_update()

                return {"success": True, "status": order_status}

            else:
                self.status = OrderStatus.RESTING
                self.kalshi_px = self.px
                self.kalshi_ctx = self.ctx
                return {"success": True, "status": "resting"}

        except Exception as e:
            # rollback target state to last confirmed kalshi state
            self.status = OrderStatus.RESTING
            self.px = old_px
            self.ctx = old_ctx
            print(f"amend failed {self.kalshi_market_ticker} {self.side}: {e}")
            self.emit_order_ui_update()
            return {"success": False, "error": str(e)}


    async def set_trading_venue(self, trading_venue: TradingVenue) -> None:
        # if identical trading venue, do nothing
        if trading_venue == self.trading_venue:
            return

        # ensure str is valid value for trading venue Enum
        valid_values = [v for v in TradingVenue]
        if trading_venue not in valid_values:
            print(f"invalid trading_venue '{trading_venue}' — must be one of {valid_values}")
            return

        # cancel trades on outstanding venue
        await self.cancel_on_venue()

        # set venue
        self.trading_venue = TradingVenue(trading_venue)


    def handle_fill(self, msg: dict, new_ctx: float):
        order_id = msg.get("order_id")
        print(f"handling fill of {self.kalshi_market_ticker} {self.side} ({self.kalshi_order_id})")
        if order_id != self.kalshi_order_id:
            return

        self.ctx = round(float(new_ctx), 2)
        self.kalshi_ctx = round(float(new_ctx), 2)

        if self.ctx == 0:
            self.kalshi_order_id = None
            self.is_best = False
            self.px = None
            self.ctx = None
            self.kalshi_px = None
            self.kalshi_ctx = None
            self.status = OrderStatus.NONE

        self.emit_order_ui_update()