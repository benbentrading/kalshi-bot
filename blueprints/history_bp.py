from flask import Blueprint, render_template
from scripts.db_wrapper.db_operations import (
    get_events, get_market_positions, get_orders, get_trades, get_settlements
)
from pprint import pprint
from core.bot_init import bot
from scripts.utils import load_universe

###############
#  CONSTANTS  #
###############

LEAGUE_IDS, MARKET_TYPES = load_universe()
history_bp = Blueprint('history', __name__)

##############
#   ROUTES   #
##############

@history_bp.route("/history/trades")
def trades():
    rows = get_trades()
    cols = list(rows[0].keys()) if rows else []
    return render_template("history_table.html", rows=rows, cols=cols, page_title="trades")

@history_bp.route("/history/orders")
def orders():
    rows = get_orders()
    cols = list(rows[0].keys()) if rows else []
    return render_template("history_table.html", rows=rows, cols=cols, page_title="orders")

@history_bp.route("/history/positions")
def positions():
    rows = get_market_positions()
    cols = list(rows[0].keys()) if rows else []
    return render_template("history_table.html", rows=rows, cols=cols, page_title="positions")

@history_bp.route("/history/events")
def events_log():
    rows = get_events()
    cols = list(rows[0].keys()) if rows else []
    return render_template("history_table.html", rows=rows, cols=cols, page_title="events log")

@history_bp.route("/history/settlements")
def settlements():
    rows = get_settlements()
    cols = list(rows[0].keys()) if rows else []
    return render_template("history_table.html", rows=rows, cols=cols, page_title="settlements")