from enum import Enum

class TradingVenue(Enum):
    NONE = "none"        # Simulation only - no API calls
    TEST = "test"      # Kalshi Testnet
    PROD = "prod"      # Real Kalshi Production

class OrderStatus(Enum):
    NONE = "none"               # no order on book
    PLACE_PENDING = "place_pending"   # place API call in flight
    AMEND_PENDING = "amend_pending"   # amend API call in flight
    CANCEL_PENDING = "cancel_pending" # cancel API call in flight
    RESTING = "resting"         # confirmed resting on book