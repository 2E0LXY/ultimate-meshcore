"""What the bot says. Every list can be edited in the UI; these are the starting lines."""
import random
import re

DEFAULT_TEXTS = {
    # answers to a test call: each station gets every line once before any repeats
    "replies": [
        "@[{name}] test received by {me}, {hops}, SNR {snr} dB",
        "@[{name}] heard you loud and clear, {hops}",
        "@[{name}] {me} here in {location}: you came in {hops}, SNR {snr}",
        "@[{name}] copy, {hops} via {path}",
        "@[{name}] radio check ok, {hops}, RSSI {rssi}",
        "@[{name}] got you {hops} ({snr} dB), thanks for the test",
        "@[{name}] 5 and 9 from {location}, {hops}",
        "@[{name}] test ok, {hops}",
    ],
    # answers to people who name the node without a test word (answer_mentions)
    "mentions": [
        "@[{name}] hello from {me} in {location}",
        "@[{name}] yes, this is {me}",
        "@[{name}] hi, {me} listening in {location}",
    ],
    "beacons": [
        "{greeting} from {me} in {location}, anyone hearing me?",
        "{me} in {location} on air, who hears this?",
        "{greeting} all, {me} here in {location}. Replies welcome",
        "Radio check from {me}, {location}: who is out there?",
    ],
    "quick": ["Test", "hi all, anyone around?", "copy, thanks", "73"],
}

GREETINGS = ["hello", "hi", "hey", "hi there"]          # never a time of day: the other end may be elsewhere
_FIELD = re.compile(r"\{(\w+)\}")


def hops_text(hops):
    if hops is None:
        return "a few hops"
    if hops == 0:
        return "direct, no repeater"
    return "1 hop" if hops == 1 else f"{hops} hops"


def daypart(hour):
    return "morning" if 5 <= hour < 12 else "afternoon" if 12 <= hour < 17 else "evening" if 17 <= hour < 22 else "night"


def uses(template, *names):
    return any(n in _FIELD.findall(template) for n in names)


def fill(template, values):
    """Replace {field} with its value; unknown fields are left as they are."""
    return _FIELD.sub(lambda m: str(values.get(m.group(1), m.group(0))), template)


def pick_greeting(rng=random):
    return rng.choice(GREETINGS)
