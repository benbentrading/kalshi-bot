################################
#    scripts/bot_logic.py      #
#  calling kalshi/odds api to  #
#  find markets for algo.      #
################################


#############
#  IMPORTS  #
#############
import os
from dotenv import load_dotenv
import requests
import json
from pprint import pprint
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import re

import scripts.api_external.kalshi_api_wrapper as kalshi_api_wrapper
import scripts.api_external.boltodds_wrapper as boltodds_wrapper
import scripts.utils as utils

load_dotenv()  # loads .env automatically
env = os.getenv("APP_ENV", "dev").lower()   # fallback to "dev" if missing
load_dotenv(f".env.{env}", override=True)

###############
#  CONSTANTS  #
###############

LEAGUE_IDS, MARKET_TYPES = utils.load_universe()
EVENT_MATCH_SCORE_MIN = 0.5


####################
#       UTILS      #
####################

def parse_kalshi_team_abbrs(abbr_str:str, league:str):

    abbr_str = re.sub(r'\d+', '', abbr_str) # remove all numbers
    if len(abbr_str) == 6:
        return abbr_str[:3], abbr_str[3:]
    
    two_letter_teams = {"TB", "KC", "SD", "SF"}   # add more if needed
    
    if abbr_str[:2] in two_letter_teams:
        away = abbr_str[:2]
        home = abbr_str[2:]
    else:
        away = abbr_str[:3]
        home = abbr_str[3:]
    
    return away, home


#############################
#  FUNCTIONS: api wrappers  #
#############################


def fetch_markets(league:str, market_type:str, kalshi_event_id:str, odds_api_event_id:str) -> list:
    """
    fetches information on each market to pair up the kalshi market with the odds api data
    to do relval
    """

    # function for asyncio. concurrently fetch main line odds and alt line odds
    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_kalshi  = ex.submit(kalshi_api_wrapper.get_markets_for_event, kalshi_event_id)
        fut_odds_api = ex.submit(
            fetch_dk_lines,
            LEAGUE_IDS.get(league)["odds_api"],
            odds_api_event_id,
            MARKET_TYPES.get(market_type)["odds_api"]
        )

        kalshi_markets_dict  = fut_kalshi.result()
        dk_lines = fut_odds_api.result()


    # clean kalshi markets data 
    kalshi_markets_list = kalshi_markets_dict.get("markets")
    kalshi_markets_list = [
        {
            "ticker": e["ticker"],
            "title": e["yes_sub_title"],
            "strike": e["floor_strike"],
            "last_price": e["last_price"],
            "open_interest": e["open_interest"],
            "volume_24h": e["volume_24h"],
            "yes_mkt": [
                e["yes_bid"], e["yes_ask"]
            ],
            "no_mkt": [
                e["no_bid"], e["no_ask"]
            ]
        } for e in kalshi_markets_list
    ]

    # pair odds: for each kalshi market, check to see if there are associated odds
    for km in kalshi_markets_list:
        dk_line_matches = [l for l in dk_lines if l["line"] == km["strike"]]
        if len(dk_line_matches) == 1:
            dk_odds = dk_line_matches[0]
            km["dk_over_mkt"] = dk_odds["over_mkt"]
            km["dk_under_mkt"] = dk_odds["under_mkt"]
        else: # if 0, no lines; if 2+, some error with odds_api so just ignore
            km["dk_over_mkt"] = km["dk_under_mkt"] = None

    return kalshi_markets_list


def fetch_events(league:str, market_type:str) -> list:
    """
    given a league and market type, fetches all current and upcoming events
    """

    # get IDs for league/market type
    kalshi_league_id = LEAGUE_IDS[league]['kalshi']
    kalshi_market_type = MARKET_TYPES[market_type]['kalshi']
    boltodds_market_type = MARKET_TYPES[market_type]['boltodds']
    kalshi_series_id = kalshi_league_id + kalshi_market_type
    boltodds_league_id = LEAGUE_IDS[league]['boltodds']
    market_is_team = MARKET_TYPES[market_type]["is_team"]
    market_is_strike = MARKET_TYPES[market_type]["is_strike"]

    # concurrently fetch kalshi/odds_api events for league and market type
    with ThreadPoolExecutor(max_workers=2) as ex:
        kalshi_func  = ex.submit(kalshi_api_wrapper.get_events_in_series, kalshi_series_id)
        boltodds_func = ex.submit(boltodds_wrapper.get_games, boltodds_league_id)

        kalshi_evts_dict  = kalshi_func.result()
        boltodds_evts_dict = boltodds_func.result()

    # clean and parse kalshi event data
    kalshi_evts_list = kalshi_evts_dict.get("events")
    kalshi_evts_clean = []
    for e in kalshi_evts_list:
        event_ticker = e["event_ticker"]

        # parse participant names from title
        participants_str = e["title"].split(":")[0]
        participants_split = participants_str.split(" vs ")
        p1_name = participants_split[0]
        p2_name = participants_split[1]

        # parse participant abbreviations
        teams_abbr_str = event_ticker[-6:] if market_type != "set_winner" \
            else event_ticker[-8:-2]
        p1_abbr, p2_abbr = parse_kalshi_team_abbrs(teams_abbr_str, league)

        kalshi_evts_clean.append({
            "kalshi_league_id": kalshi_league_id,
            "kalshi_market_type": kalshi_market_type,
            "kalshi_event_ticker": e["event_ticker"],
            "kalshi_title": e["title"],
            "kalshi_date": e["sub_title"].split("(")[-1][:-1],
            "kalshi_comp": participants_str,
            "kalshi_p1_name": p1_name,
            "kalshi_p2_name": p2_name,
            "kalshi_p1_abbr": p1_abbr,
            "kalshi_p2_abbr": p2_abbr,
        })

    # clean boltodds games data
    boltodds_evts = []
    for k, v in boltodds_evts_dict.items():
        bo_game_nodate = k.split(", ")[0]
        bo_comp = bo_game_nodate
        if league != "atp": # in all leagues except ATP (for now) p1/p2 in kalshi/boltodds are reversed
            bo_comp = "".join(bo_comp.partition(" vs ")[::-1])
            bo_comp.replace("vs", "at")

        # get p1 and p2 names for parsing websocket data
        team_names = bo_game_nodate.strip().split(" vs ")
        p1_name = team_names[1 if league != "atp" else 0]
        p2_name = team_names[0 if league != "atp" else 1]

        # get datetime data
        bo_datetime_unix = int(datetime.strptime(v.get("when"), '%Y-%m-%d, %I:%M %p').timestamp())

        boltodds_evts.append(
            {
                "boltodds_comp": bo_comp,
                "boltodds_datetime": v.get("when"),
                "boltodds_datetime_unix": bo_datetime_unix,
                "boltodds_id": k,
                "boltodds_p1_name": p1_name,
                "boltodds_p2_name": p2_name,
            }
        )

    # match events (pair)
    bo_comps_with_date = []
    for e in boltodds_evts:
        bo_date_str = datetime.fromtimestamp(e["boltodds_datetime_unix"]).strftime("%b %d")
        bo_comps_with_date.append(f"{e['boltodds_comp']} {bo_date_str}")

    for ke in kalshi_evts_clean:
        kalshi_comp_with_date = f"{ke['kalshi_comp']} {ke['kalshi_date']}"

        best_match_with_date, comp_score = utils.get_most_similar_sentence(
            kalshi_comp_with_date, bo_comps_with_date
        )

        if comp_score < EVENT_MATCH_SCORE_MIN:
            continue

        best_match_comp = " ".join(best_match_with_date.split(" ")[:-2])

        best_match_bo_elem = next(
            (e for e in boltodds_evts if e["boltodds_comp"] == best_match_comp), None
        )

        if best_match_bo_elem is None:
            continue

        # verify dates match
        bo_date = datetime.fromtimestamp(best_match_bo_elem["boltodds_datetime_unix"]).strftime("%b %-d")
        if bo_date != ke["kalshi_date"]:
            continue

        # append best match
        ke["boltodds_comp"] = best_match_comp

        # append best match odds api element to the kalshi element
        ke["boltodds_comp"] = best_match_comp
        ke["boltodds_id"] = best_match_bo_elem["boltodds_id"]
        ke["boltodds_datetime"] = best_match_bo_elem["boltodds_datetime"]
        ke["boltodds_datetime_unix"] = best_match_bo_elem["boltodds_datetime_unix"]
        ke["boltodds_p1_name"] = best_match_bo_elem["boltodds_p1_name"]
        ke["boltodds_p2_name"] = best_match_bo_elem["boltodds_p2_name"]
        ke["match_score"] = round(comp_score, 2)
        ke["league"] = league
        ke["market_type"] = market_type
        ke["boltodds_league_id"] = boltodds_league_id
        ke["boltodds_market_type"] = boltodds_market_type
        ke["is_team"] = market_is_team
        ke["is_strike"] = market_is_strike

    # remove kalshi events with no odds_api matches
    kalshi_evts_clean = [e for e in kalshi_evts_clean if e.get("boltodds_comp") is not None]
    kalshi_evts_clean.sort(key=lambda e: e["boltodds_datetime_unix"], reverse=False)

    return kalshi_evts_clean


if __name__ == "__main__":
    e = fetch_events("mlb", "moneyline")
    pprint(e, sort_dicts=False)
    # print("-------")