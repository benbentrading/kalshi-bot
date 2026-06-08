#######################
#  scripts/kalshi.py  #
#######################

#############
#  IMPORTS  #
#############
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import json
from pathlib import Path
from pprint import pprint



###############
#  FUNCTIONS  #
###############

def load_private_key_from_file(file_path):
    """
    this code is directly pasted from kalshi documentation.
    https://docs.kalshi.com/getting_started/api_keys
    """
    with open(file_path, "rb") as key_file:
        private_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None,  # or provide a password if your key is encrypted
            backend=default_backend()
        )
    return private_key


def sign_pss_text(private_key: rsa.RSAPrivateKey, text: str) -> str:
    """
    this code is directly pasted from kalshi documentation.
    https://docs.kalshi.com/getting_started/api_keys
    """
    message = text.encode('utf-8')
    try:
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode('utf-8')
    except InvalidSignature as e:
        raise ValueError("RSA sign PSS failed") from e
    

def get_unix_timestamp(minutes_ago:int = 0):
    """
    gets unix timestamp
    """
    if minutes_ago < 0:
            raise ValueError("minutes_ago should be non-negative")

    now_utc = datetime.now(timezone.utc)
    past_utc = now_utc - timedelta(minutes=minutes_ago)
    return int(past_utc.timestamp())


def get_sentence_similarity(a:str, b:str) -> int:
    """
     gets similarity between two sentences
     uses simple transformer package
    """
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def get_most_similar_sentence(a:str, b:list) -> tuple:
    """
    returns most similar sentence to a in list
    """

    if len(b) == 0:
        return (None, None)

    best_word = ""
    best_score = 0

    for word in b:
        score = get_sentence_similarity(a, word)
        if score > best_score:
            best_word = word
            best_score = score

    return (best_word, best_score)


def prob_to_american_odds(p: float, decimals: int = 0) -> str:
    if not 0 <= p <= 1:
        raise ValueError("Probability must be between 0 and 1")
    
    if p == 0:
        return "+∞"
    if p == 1:
        return "-∞"
    
    if p > 0.5:
        odds = -100 * p / (1 - p)
        return f"{odds:,.{decimals}f}"
    else:
        odds = 100 * (1 - p) / p
        return f"{odds:,.{decimals}f}"


def american_odds_to_prob(odds_str: str) -> float:
    if odds_str is None:
        return None
    
    odds = float(odds_str)
    
    if odds < 0:
        p = -odds / (-odds + 100)
    else:
        p = 100 / (odds + 100)
    
    return round(p, 2)

def rfc3339_to_unix_seconds(rfc3339_str: str) -> int:
    """
    Convert an RFC 3339 timestamp string to Unix timestamp (seconds since epoch).

    Accepts formats like:
    - 2026-02-12T20:15:02Z
    - 2026-02-12T20:15:02.345Z
    - 2026-02-12T20:15:02+00:00

    Returns: integer seconds (UTC)

    Raises ValueError if the string cannot be parsed.
    """
    # Replace 'Z' with '+00:00' because fromisoformat() in Python < 3.11 doesn't understand 'Z'
    if rfc3339_str.endswith('Z'):
        rfc3339_str = rfc3339_str[:-1] + '+00:00'

    # Parse the string
    dt = datetime.fromisoformat(rfc3339_str)

    # Convert to Unix timestamp (seconds since 1970-01-01 00:00:00 UTC)
    return int(dt.timestamp())


def load_universe():
    config_path = Path(__file__).parent.parent \
        / "assets" / "json" / "universe.json"
    
    with open(config_path, "r") as f:
        data = json.load(f)
    
    return data["LEAGUE_IDS"], data["MARKET_TYPES"]


def get_market_type_by_boltodds_market_type(boltodds_market_type: str):
    """
    Returns the internal market type key (e.g. 'moneyline', 'spread') 
    that matches the given BoltOdds market type.
    """

    _, MARKET_TYPES = load_universe()

    if not boltodds_market_type:
        return None

    for market_key, config in MARKET_TYPES.items():
        bolt_value = config.get("boltodds")
        
        # Handle both string and list cases
        if isinstance(bolt_value, list):
            if boltodds_market_type in bolt_value:
                return market_key
        elif isinstance(bolt_value, str):
            if boltodds_market_type == bolt_value:
                return market_key

    # If no match found
    return None


def determine_bot_market_vegas_offer(outcomes_dict:dict) -> tuple:
    market_type = outcomes_dict["outcome_name"]
    vegas_px = american_odds_to_prob(outcomes_dict["odds"])

    if market_type in ["Total", "Total Games", "1st 5 Innings Total", "Team Total"]:
        over_under = outcomes_dict["outcome_over_under"][-1]
        # pprint(outcomes_dict)
        # print(f"{outcomes_dict['outcome_line']} / {over_under} / {over_under == 'U'} /")
        is_offer = over_under == "O"
    elif market_type in ["Moneyline", "S1 Moneyline", "S2 Moneyline"]:
        is_offer = True
    elif market_type in ["Spread", "Alternate Spread", "1st 5 Innings Spread"]:
        # if the spread is a "+", change team 
        line = float(outcomes_dict["outcome_line"])
        is_offer = line < 0


    return vegas_px, is_offer


if __name__ == "__main__":
    s = get_sentence_similarity("Ottowa at Washington", "Philadelphia Senators at New York Capitals")
    print(s)