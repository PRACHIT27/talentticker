"""Turn free-text job locations into a US metro and state.

Companies write locations however they like. Across a sample of 1,800 postings
there were 394 distinct spellings, including "Hybrid", "Distributed", "N/A" and
"San Francisco, CA - New York, NY - United States". This module boils those
down to something countable.
"""
from __future__ import annotations

import re

STATES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "washington dc": "DC", "washington d.c.": "DC",
    "puerto rico": "PR",
}
STATE_ABBRS = set(STATES.values())

# City -> (metro label, state). Grouped so that Palo Alto and Oakland both
# land on the same row of the dashboard as San Francisco.
CITIES: dict[str, tuple[str, str]] = {}


def _add(metro: str, state: str, *cities: str) -> None:
    for city in cities:
        CITIES[city.lower()] = (metro, state)


_add("SF Bay Area", "CA", "san francisco", "sf", "south san francisco",
     "palo alto", "mountain view", "menlo park", "redwood city", "san mateo",
     "sunnyvale", "santa clara", "cupertino", "san jose", "oakland", "berkeley",
     "fremont", "foster city", "burlingame", "emeryville", "bay area",
     "silicon valley", "milpitas", "campbell", "los gatos", "alameda",
     "pleasanton", "walnut creek", "san bruno", "daly city", "brisbane")
_add("Seattle", "WA", "seattle", "bellevue", "redmond", "kirkland", "tacoma",
     "renton", "everett", "bothell")
_add("New York", "NY", "new york", "new york city", "nyc", "manhattan",
     "brooklyn", "queens", "long island city", "bronx")
_add("New York", "NJ", "jersey city", "newark", "hoboken")
_add("Boston", "MA", "boston", "cambridge", "somerville", "waltham",
     "burlington", "needham", "quincy", "newton", "watertown", "lexington",
     "woburn", "bedford", "andover", "framingham")
_add("Austin", "TX", "austin", "round rock")
_add("Dallas", "TX", "dallas", "plano", "irving", "fort worth", "richardson",
     "frisco", "addison", "arlington")
_add("Houston", "TX", "houston", "sugar land")
_add("Los Angeles", "CA", "los angeles", "santa monica", "pasadena",
     "culver city", "el segundo", "burbank", "venice", "long beach",
     "playa vista", "torrance", "glendale", "irvine", "costa mesa",
     "newport beach", "anaheim", "santa ana")
_add("San Diego", "CA", "san diego", "carlsbad", "la jolla")
_add("Denver", "CO", "denver", "boulder", "broomfield", "louisville",
     "englewood", "aurora", "lakewood", "colorado springs", "fort collins")
_add("Chicago", "IL", "chicago", "evanston", "naperville", "schaumburg")
_add("Atlanta", "GA", "atlanta", "alpharetta", "marietta", "sandy springs")
_add("Washington DC", "DC", "washington dc", "washington d.c.", "washington, dc")
_add("Washington DC", "VA", "arlington", "mclean", "reston", "herndon",
     "alexandria", "tysons", "vienna", "ashburn", "chantilly", "fairfax")
_add("Washington DC", "MD", "bethesda", "rockville", "silver spring",
     "columbia", "annapolis", "baltimore", "gaithersburg")
_add("Portland", "OR", "portland", "beaverton", "hillsboro")
_add("Salt Lake City", "UT", "salt lake city", "lehi", "provo", "draper",
     "sandy", "south jordan", "american fork", "park city")
_add("Phoenix", "AZ", "phoenix", "scottsdale", "tempe", "chandler", "mesa",
     "gilbert", "glendale")
_add("Raleigh-Durham", "NC", "raleigh", "durham", "chapel hill", "cary",
     "research triangle", "morrisville")
_add("Charlotte", "NC", "charlotte")
_add("Nashville", "TN", "nashville", "franklin", "brentwood")
_add("Miami", "FL", "miami", "fort lauderdale", "boca raton", "coral gables",
     "west palm beach", "miami beach")
_add("Orlando", "FL", "orlando", "tampa", "st. petersburg", "jacksonville")
_add("Philadelphia", "PA", "philadelphia", "conshohocken", "king of prussia",
     "malvern", "wayne", "radnor")
_add("Pittsburgh", "PA", "pittsburgh")
_add("Minneapolis", "MN", "minneapolis", "st. paul", "saint paul", "bloomington",
     "eden prairie")
_add("Detroit", "MI", "detroit", "ann arbor", "troy", "southfield")
_add("Columbus", "OH", "columbus", "cleveland", "cincinnati", "dublin")
_add("Madison", "WI", "madison", "milwaukee")
_add("Kansas City", "MO", "kansas city", "st. louis", "saint louis", "overland park")
_add("Las Vegas", "NV", "las vegas", "reno", "henderson")
_add("Indianapolis", "IN", "indianapolis", "carmel", "fishers")
_add("Pennsylvania", "PA", "pennsylvania")
_add("Hartford", "CT", "hartford", "stamford", "greenwich", "norwalk", "new haven")
_add("Richmond", "VA", "richmond")
_add("New Orleans", "LA", "new orleans", "baton rouge")
_add("Oklahoma City", "OK", "oklahoma city", "tulsa")
_add("Omaha", "NE", "omaha", "lincoln")
_add("Boise", "ID", "boise", "meridian")
_add("Albuquerque", "NM", "albuquerque", "santa fe")
_add("Honolulu", "HI", "honolulu")
_add("Anchorage", "AK", "anchorage")
_add("Buffalo", "NY", "buffalo", "rochester", "syracuse", "albany", "ithaca")
_add("Birmingham", "AL", "birmingham", "huntsville", "montgomery")
_add("Little Rock", "AR", "little rock", "bentonville", "fayetteville")
_add("Des Moines", "IA", "des moines", "cedar rapids", "iowa city")
_add("Louisville", "KY", "louisville", "lexington")
_add("Memphis", "TN", "memphis", "knoxville", "chattanooga")
_add("Jackson", "MS", "jackson")
_add("Billings", "MT", "billings", "bozeman", "missoula")
_add("Manchester", "NH", "manchester", "nashua", "portsmouth")
_add("Providence", "RI", "providence")
_add("Charleston", "SC", "charleston", "columbia", "greenville")
_add("Sioux Falls", "SD", "sioux falls", "fargo")
_add("Burlington", "VT", "burlington", "montpelier")
_add("Spokane", "WA", "spokane", "vancouver")
_add("Cheyenne", "WY", "cheyenne", "jackson hole")
_add("Wilmington", "DE", "wilmington", "newark")
_add("Portland", "ME", "portland")
_add("San Juan", "PR", "san juan")

# Places that are clearly not in the US. Anything matching here is dropped.
FOREIGN = {
    "london", "dublin", "paris", "berlin", "munich", "amsterdam", "madrid",
    "barcelona", "lisbon", "zurich", "geneva", "stockholm", "copenhagen",
    "oslo", "helsinki", "warsaw", "krakow", "prague", "budapest", "bucharest",
    "milan", "rome", "vienna", "brussels", "edinburgh", "manchester uk",
    "cambridge uk", "tel aviv", "jerusalem", "haifa", "dubai", "abu dhabi",
    "bangalore", "bengaluru", "hyderabad", "pune", "mumbai", "delhi",
    "new delhi", "gurgaon", "gurugram", "noida", "chennai", "kolkata",
    "ahmedabad", "tokyo", "osaka", "kyoto", "seoul", "singapore", "hong kong",
    "shanghai", "beijing", "shenzhen", "taipei", "sydney", "melbourne",
    "brisbane au", "perth", "auckland", "wellington", "toronto", "vancouver bc",
    "montreal", "ottawa", "calgary", "waterloo", "mexico city", "guadalajara",
    "monterrey", "sao paulo", "são paulo", "rio de janeiro", "buenos aires",
    "santiago", "bogota", "bogotá", "lima", "medellin", "medellín",
    "cape town", "johannesburg", "nairobi", "lagos", "cairo", "istanbul",
    "bangkok", "jakarta", "manila", "kuala lumpur", "ho chi minh", "hanoi",
    "belfast", "glasgow", "leeds", "bristol", "birmingham uk", "cork",
    "eindhoven", "rotterdam", "hamburg", "frankfurt", "stuttgart", "cologne",
    "dusseldorf", "düsseldorf", "vilnius", "riga", "tallinn", "sofia", "zagreb",
    "belgrade", "kyiv", "kiev", "yerevan", "tbilisi", "karachi", "lahore",
    "islamabad", "dhaka", "colombo", "doha", "riyadh", "amman", "beirut",
}
FOREIGN_COUNTRIES = {
    "united kingdom", "uk", "england", "scotland", "wales", "ireland",
    "germany", "france", "spain", "portugal", "italy", "netherlands",
    "belgium", "switzerland", "austria", "sweden", "norway", "denmark",
    "finland", "poland", "czech republic", "czechia", "hungary", "romania",
    "bulgaria", "greece", "croatia", "serbia", "ukraine", "russia", "turkey",
    "israel", "uae", "united arab emirates", "saudi arabia", "qatar", "egypt",
    "south africa", "kenya", "nigeria", "india", "china", "japan", "korea",
    "south korea", "taiwan", "singapore", "malaysia", "indonesia", "thailand",
    "vietnam", "philippines", "australia", "new zealand", "canada", "mexico",
    "brazil", "argentina", "chile", "colombia", "peru", "costa rica",
    "uruguay", "panama", "guatemala", "pakistan", "bangladesh", "sri lanka",
    "armenia", "georgia country", "lithuania", "latvia", "estonia", "iceland",
    "luxembourg", "slovakia", "slovenia", "cyprus", "malta", "morocco",
    "tunisia", "ghana", "emea", "apac", "latam", "united kingdom of great britain",
}

US_MARKERS = re.compile(
    r"\b(usa|u\.s\.a\.|united states|u\.s\.|us based|us-based|us|"
    r"americas|north america|nationwide)\b",
    re.I,
)
REMOTE_MARKERS = re.compile(
    r"\b(remote|distributed|anywhere|work from home|wfh|virtual|telecommute)\b", re.I
)
HYBRID_MARKERS = re.compile(r"\b(hybrid|in[\s-]?office|on[\s-]?site|onsite)\b", re.I)
NOISE = {"", "n/a", "na", "none", "tbd", "multiple locations", "various",
         "flexible", "other", "global", "worldwide", "any"}

SPLITTERS = re.compile(r"[;•·|\n]|(?:\s+-\s+)|(?:\s+or\s+)|(?:\s*,?\s+and\s+)")


class Place:
    __slots__ = ("metro", "state", "country", "remote", "hybrid")

    def __init__(self, metro="", state="", country="", remote=False, hybrid=False):
        self.metro = metro
        self.state = state
        self.country = country
        self.remote = remote
        self.hybrid = hybrid

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Place(metro={self.metro!r}, state={self.state!r}, country={self.country!r}, remote={self.remote})"


def _clean(part: str) -> str:
    part = part.strip().strip(",-()").strip()
    part = re.sub(r"\s+", " ", part)
    return part


def _match_part(part: str) -> Place | None:
    """Resolve a single location fragment such as 'Austin, TX'."""
    low = _clean(part).lower()
    if low in NOISE:
        return None

    if low in FOREIGN_COUNTRIES or any(
        low.endswith(", " + c) or low == c for c in FOREIGN_COUNTRIES
    ):
        return Place(country="non-US")

    tokens = [t.strip() for t in low.split(",") if t.strip()]
    for token in tokens:
        if token in FOREIGN or token in FOREIGN_COUNTRIES:
            return Place(country="non-US")

    # Find a state, either spelled out or as a two-letter code.
    state = ""
    for token in tokens:
        if token in STATES:
            state = STATES[token]
            break
        upper = token.upper()
        if len(upper) == 2 and upper in STATE_ABBRS:
            state = upper
            break

    # Find a city we know.
    for token in tokens:
        hit = CITIES.get(token)
        if hit:
            metro, city_state = hit
            # A city name shared across states (Portland, Columbia) is settled
            # by the state token when one is present.
            if state and state != city_state:
                alt = CITIES.get(f"{token}|{state.lower()}")
                if alt:
                    return Place(metro=alt[0], state=state, country="US")
                return Place(metro=token.title(), state=state, country="US")
            return Place(metro=metro, state=city_state, country="US")

    if state:
        return Place(metro=f"Other {state}", state=state, country="US")
    if US_MARKERS.search(low):
        return Place(metro="United States", state="", country="US")
    return None


def parse(location_raw: str, remote_hint: bool = False) -> Place:
    """Best guess at where a job sits.

    When a posting lists several places we keep the first US one, because that
    is the office a US-based candidate would actually be hired into.
    """
    text = (location_raw or "").strip()
    remote = remote_hint or bool(REMOTE_MARKERS.search(text))
    hybrid = bool(HYBRID_MARKERS.search(text))

    parts = [p for p in SPLITTERS.split(text) if p and p.strip()]
    if not parts:
        parts = [text]

    resolved = [p for p in (_match_part(part) for part in parts) if p]
    us = [p for p in resolved if p.country == "US"]

    if us:
        # Prefer a fragment that names an actual metro over a bare "United States".
        best = next((p for p in us if p.metro != "United States"), us[0])
        best.remote = remote
        best.hybrid = hybrid
        return best

    if resolved and all(p.country == "non-US" for p in resolved):
        return Place(country="non-US", remote=remote, hybrid=hybrid)

    # Nothing recognisable. A remote-only string still tells us something.
    if remote and not resolved:
        return Place(metro="Remote", state="", country="US?", remote=True, hybrid=hybrid)
    return Place(country="", remote=remote, hybrid=hybrid)


def is_us(place: Place) -> bool:
    return place.country in ("US", "US?")


# Phrases companies use in the body when the location field says nothing useful.
IN_TEXT_LOCATION = re.compile(
    r"(?:based\s+in|located\s+in|location:|office\s+in|onsite\s+in|on-site\s+in|"
    r"role\s+is\s+in|position\s+is\s+(?:based\s+)?in|work\s+from\s+our|"
    r"hybrid\s+in|reporting\s+to\s+our)\s+"
    r"([A-Z][A-Za-z.\- ]{2,30}(?:,\s*[A-Z][A-Za-z.\- ]{1,20})?)",
)
# "San Francisco, CA" written anywhere, which pay-transparency notes often use.
CITY_STATE = re.compile(r"\b([A-Z][a-zA-Z.\-]+(?:\s+[A-Z][a-zA-Z.\-]+){0,2}),\s*([A-Z]{2})\b")


def parse_with_fallback(location_raw: str, content: str, remote_hint: bool = False) -> Place:
    """Parse the location field, and fall back to the description when it is useless.

    Boards are full of location fields that read "Hybrid", "In-Office" or "N/A".
    Roughly one posting in six looks like that, and throwing them away would
    lose real US jobs, so when the field tells us nothing we go looking in the
    text for a city.
    """
    place = parse(location_raw, remote_hint)
    if place.country in ("US", "non-US"):
        return place
    if not content:
        return place

    head = content[:4000]
    tail = content[-4000:] if len(content) > 8000 else ""
    for chunk in (head, tail):
        if not chunk:
            continue
        for match in IN_TEXT_LOCATION.finditer(chunk):
            candidate = _match_part(match.group(1))
            if candidate and candidate.country == "US":
                candidate.remote = place.remote
                candidate.hybrid = place.hybrid
                return candidate
        for city, state in CITY_STATE.findall(chunk):
            if state not in STATE_ABBRS:
                continue
            candidate = _match_part(f"{city}, {state}")
            if candidate and candidate.country == "US":
                candidate.remote = place.remote
                candidate.hybrid = place.hybrid
                return candidate
    return place
