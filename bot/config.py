import os

PLAIN = 0
MOUNTAIN = 1
CITY = 2
GENERAL = 3
UNSEEN = 4
UNSEEN_OBSTACLE = 5

NEUTRAL = -1
HIDDEN = -2

IMPASSABLE = (MOUNTAIN, UNSEEN_OBSTACLE)

# Server consumes one queued move per tick. Holding a couple in reserve absorbs
# network jitter so a 500ms tick is never wasted; any deeper and we are planning
# several ticks ahead on a board the opponent keeps changing.
QUEUE_TARGET = 2
QUEUE_MAX = 8

# A walk costs one tick per step regardless of how much army moves, so the
# general accumulates until a run can capture this many cells after arriving.
GENERAL_RUN_MIN = 6
SATELLITE_RUN_MIN = 1

# Defence reserve kept on the general, by BFS distance to the nearest known
# enemy tile. Before contact the general is our only army source, so dribbling
# it down to 1 is correct.
RESERVE_FAR = 1
RESERVE_MID = 8
RESERVE_NEAR = 16
CONTACT_MID = 12
CONTACT_NEAR = 6

# Visible proximity is not enough warning: an opponent masses out of sight and
# arrives faster than army can be gathered back at one move per tick. Hold a
# standing garrison as a share of the opponent's total army, which scores
# reports through the fog.
GARRISON_SHARE = 0.25

# Early contact against a fast expander switched the standing garrison on
# while it was most of the general's army, and between land-growth ticks the
# general is the only mobile unit, so the bot planned nothing for forty ticks
# and was run off the map. Real approaching stacks still count from tick 0
# through threat_to; the standing share is a midgame instrument.
GARRISON_MIN_TICK = 150

# Their army grows with their land, far faster than the general's +1 per two
# ticks, so an uncapped reserve outruns the general and freezes it for the rest
# of the game. Capping against our own army keeps a garrison we can actually
# afford: the general moves again once it holds enough of our total.
# A half move leaves ceil(army/2), so the general needs twice the reserve to
# act at all. 0.20 already means holding 40% of our total army; higher freezes.
GARRISON_CAP_OF_MINE = 0.20

# A neutral city costs 40-50 army and repays ~1.6x over a median 242-tick game,
# against ~2-3x for the same army spent on land. Only worth it once established
# and clearly affordable.
CITY_MIN_TICK = 60
CITY_ARMY_MARGIN = 20

# Opponent army rising while their land does not means they are stacking for a
# rush. scores is not fog-filtered, so this is visible through the fog.
STACK_RATIO_ALARM = 2.5

# Winning the economy is not winning: a game surviving 1,200 ticks is a draw.
# Once there is little neutral land left, drive into enemy territory to find and
# kill the general rather than shuffling a won board.
PRESS_MIN_TICK = 250
PRESS_NEUTRAL_FLOOR = 12
# Requiring near-parity meant a bot slightly behind on army never attacked at
# all: one loss ran 600 ticks in expand mode while the opponent massed and
# walked in. Pressing reveals their territory and finds the general.
PRESS_ARMY_RATIO = 0.7

# Bound the walk: a city run runs ahead of captures, so a long walk is a long
# expansion stall.
CITY_MAX_WALK = 8

RECONNECT_BACKOFF_MAX = 10


def arena_url():
    return os.environ.get("ARENA_URL", "").rstrip("/")


def bot_token():
    return os.environ.get("BOT_TOKEN", "")


def ws_url():
    base = arena_url()
    return base.replace("https://", "wss://").replace("http://", "ws://") + "/ws/v1"
