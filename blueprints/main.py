# blueprints/main.py

from flask import Blueprint, render_template
from collections import defaultdict

import scripts.api_external.kalshi_api_wrapper
from pprint import pprint
from core.bot_init import bot
from scripts.utils import load_universe

###############
#  CONSTANTS  #
###############

LEAGUE_IDS, MARKET_TYPES = load_universe()
main_bp = Blueprint('main', __name__)


##################
#  -- ROUTES --  #
##################

@main_bp.route("/")
def home():
    return render_template("index.html", page_title="home")


@main_bp.route("/health")
def health():
    return {"status": "healthy", "bot_running": True}, 200


@main_bp.route("/portfolio")
def portfolio():
    balance = scripts.api_external.kalshi_api_wrapper.get_portfolio_balance()
    return render_template(
        "portfolio.html",
        page_title="portfolio",
        portfolio=balance
    )


@main_bp.route("/history")
def history():
    return render_template(
        "history.html",
        page_title="history",
    )


@main_bp.route("/add_event")
def add_event():
    return render_template(
        "add_event.html",
        page_title="add event",
        leagues=LEAGUE_IDS.keys(),
        market_types=MARKET_TYPES.keys(),
        league_ids=LEAGUE_IDS,
    )


@main_bp.route("/events")
def events_html():
    events_list = bot.get_all_events_list()
    return render_template(
        "events.html",
        page_title="events",
        events=events_list
    )


@main_bp.route("/trade")
def trade():
    markets_list = bot.get_all_markets_dicts_list()
    
    grouped = defaultdict(list)
    for m in sorted(markets_list, key=lambda m: m["trading_venue"] != "prod"):
        grouped[m["kalshi_event_ticker"]].append(m)

    # build display headers from first element of each group
    group_headers = {
        event_ticker: {
            "boltodds_id": markets[0]["boltodds_id"],
            "market_type": markets[0]["boltodds_market_type"],
        }
        for event_ticker, markets in grouped.items()
    }

    return render_template(
        "trade.html",
        grouped_markets=grouped,
        group_headers=group_headers,
        page_title="trade"
    )