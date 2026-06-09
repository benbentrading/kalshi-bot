from flask import Blueprint, request, jsonify
from core.gui_handler import add_event_to_bot, remove_event_from_bot,\
    unsubscribe_all, set_market_trading_venue, set_market_max_position_ctx, \
    cancel_all_kalshi_orders
from scripts.api_external.market_selection import fetch_events
from pprint import pprint

bot_bp = Blueprint('bot', __name__)

##################
#  FLASK ROUTES  #
##################
@bot_bp.route("/add_event_to_bot", methods=["POST"])
def route_add_event():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No JSON data received"}), 400

    add_event_to_bot(data)

    return jsonify({
        "status": "success",
        "message": f"Added: {data.get('kalshi_title', 'Event')}"
    })


@bot_bp.route("/remove_event_from_bot", methods=["POST"])
def route_remove_event():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No JSON data received"}), 400

    kalshi_event_ticker = data.get("kalshi_event_ticker")
    if not kalshi_event_ticker:
        return jsonify({"status": "error", "message": "Missing kalshi_event_ticker"}), 400

    remove_event_from_bot(kalshi_event_ticker)

    return jsonify({
        "status": "success",
        "message": f"removed: {kalshi_event_ticker}"
    })


@bot_bp.route("/get_events", methods=["GET"])
def get_events():
    league = request.args.get("league")
    market_type = request.args.get("market_type")

    events = []
    if league and market_type:
        events = fetch_events(league, market_type)

    return jsonify({"events": events})


@bot_bp.route("/set_market_trading_venue", methods=["POST"])
def route_set_market_trading_venue():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No JSON data received"}), 400

    kalshi_market_ticker = data.get("kalshi_market_ticker")
    trading_venue = data.get("trading_venue")

    if not kalshi_market_ticker or not trading_venue:
        return jsonify({"status": "error", "message": "Missing kalshi_market_ticker or trading_venue"}), 400

    set_market_trading_venue(kalshi_market_ticker, trading_venue)

    return jsonify({
        "status": "success",
        "message": f"set {kalshi_market_ticker} trading venue to {trading_venue}"
    })


@bot_bp.route("/set_market_max_position_ctx", methods=["POST"])
def route_set_market_max_position_ctx():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "No JSON data received"}), 400

    kalshi_market_ticker = data.get("kalshi_market_ticker")
    ctx = data.get("ctx")

    if not kalshi_market_ticker or not ctx:
        return jsonify({"status": "error", "message": "Missing kalshi_market_ticker or ctx"}), 400

    set_market_max_position_ctx(kalshi_market_ticker, ctx)

    return jsonify({
        "status": "success",
        "message": f"set {kalshi_market_ticker} max position ctx to {ctx:.2f}"
    })


@bot_bp.route("/unsubscribe_all", methods=["POST"])
def route_unsubscribe_all():
    unsubscribe_all()
    return jsonify({"status": "success", "message": "unsubscribed from all events"})


@bot_bp.route("/cancel_all_kalshi_orders", methods=["POST"])
def route_cancel_all_kalshi_orders():
    cancel_all_kalshi_orders()
    return jsonify({"status": "success", "message": "unsubscribed from all events"})