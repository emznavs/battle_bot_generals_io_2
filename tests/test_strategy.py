import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.board import Board
from bot.config import CITY, GENERAL, HIDDEN, MOUNTAIN, NEUTRAL, PLAIN, UNSEEN
from bot.strategy import _Sim, _walk, decide_mode, defence_reserve, plan

W = H = 25
N = W * H


def blank_frame(tick=100):
    return {
        "tick": tick,
        "width": W,
        "height": H,
        "terrain": [UNSEEN] * N,
        "owners": [HIDDEN] * N,
        "armies": [None] * N,
        "visible": [False] * N,
        "scores": [{"army": 1, "land": 1}, {"army": 1, "land": 1}],
        "outcome": None,
    }


def own(frame, index, army, player=0):
    frame["owners"][index] = player
    frame["armies"][index] = army
    frame["visible"][index] = True
    if frame["terrain"][index] in (UNSEEN,):
        frame["terrain"][index] = PLAIN


def assert_legal(board, moves):
    armies = board.armies()
    owners = list(board.owners)
    for move in moves:
        source, target = move["from"], move["to"]
        assert target in board.neighbours[source], f"{source}->{target} not adjacent"
        assert owners[source] == board.me, f"source {source} not ours"
        assert armies[source] >= 2, f"source {source} has {armies[source]} army"
        assert board.terrain[target] != MOUNTAIN, "moved into a mountain"
        sent = armies[source] // 2 if move["half"] else armies[source] - 1
        armies[source] -= sent
        if owners[target] == board.me:
            armies[target] += sent
        elif sent > armies[target]:
            owners[target] = board.me
            armies[target] = sent - armies[target]
        else:
            armies[target] -= sent


def test_expands_and_returns_legal_moves():
    frame = blank_frame()
    general = 12 * W + 12
    frame["terrain"][general] = GENERAL
    own(frame, general, 30)
    for offset in (-1, 1, -W, W):
        own(frame, general + offset, 1)
    frame["scores"] = [{"army": 34, "land": 5}, {"army": 20, "land": 4}]

    board = Board(frame, 0)
    moves, mode = plan(board, 4)
    assert mode == "expand", mode
    assert len(moves) == 4, moves
    assert_legal(board, moves)


def test_never_idles_when_army_is_available():
    frame = blank_frame()
    general = 5 * W + 5
    frame["terrain"][general] = GENERAL
    own(frame, general, 50)
    board = Board(frame, 0)
    moves, _ = plan(board, 6)
    assert len(moves) == 6, "a 50-stack should always find something to do"
    assert_legal(board, moves)


def test_hunts_a_reachable_enemy_general():
    frame = blank_frame()
    general = 12 * W + 2
    enemy_general = 12 * W + 8
    frame["terrain"][general] = GENERAL
    frame["terrain"][enemy_general] = GENERAL
    own(frame, general, 200)
    own(frame, enemy_general, 5, player=1)
    for step in range(3, 8):
        frame["terrain"][12 * W + step] = PLAIN
        frame["owners"][12 * W + step] = NEUTRAL
        frame["armies"][12 * W + step] = 0
        frame["visible"][12 * W + step] = True
    frame["scores"] = [{"army": 200, "land": 1}, {"army": 5, "land": 1}]

    board = Board(frame, 0)
    mode, _ = decide_mode(board, general)
    assert mode == "hunt", mode
    moves, _ = plan(board, 3)
    assert moves, "should march on a killable general"
    assert moves[0]["from"] == general
    assert_legal(board, moves)


def test_holds_reserve_and_defends_when_threatened():
    frame = blank_frame()
    general = 10 * W + 10
    attacker = 10 * W + 12
    frame["terrain"][general] = GENERAL
    own(frame, general, 5)
    own(frame, attacker, 80, player=1)
    own(frame, 10 * W + 11, 1)
    own(frame, 2 * W + 10, 60)
    frame["scores"] = [{"army": 66, "land": 3}, {"army": 80, "land": 1}]

    board = Board(frame, 0)
    assert defence_reserve(board, general) > 1
    mode, _ = decide_mode(board, general)
    assert mode == "defend", mode
    moves, _ = plan(board, 2)
    assert moves, "should route reinforcements home"
    assert moves[0]["from"] != general, "must not strip the threatened general"
    assert_legal(board, moves)


def test_accounts_for_moves_already_queued_on_the_server():
    """A pending move drains its source before anything we add now executes."""
    frame = blank_frame()
    general = 6 * W + 6
    frame["terrain"][general] = GENERAL
    own(frame, general, 9)
    own(frame, general + 1, 1)
    board = Board(frame, 0)

    pending = [{"from": general, "to": general + 1, "half": False}]
    moves, _ = plan(board, 3, pending)
    assert all(move["from"] != general for move in moves), (
        "planned from a source the pending move leaves at 1 army"
    )

    without = plan(board, 3)[0]
    assert any(move["from"] == general for move in without), "sanity: free to use it"


def test_reserve_never_freezes_the_general():
    """A reserve the general can never leave behind stops it expanding forever."""
    frame = blank_frame(tick=400)
    general = 12 * W + 12
    frame["terrain"][general] = GENERAL
    own(frame, general, 220)
    for offset in (-1, 1, -W, W):
        own(frame, general + offset, 1)
    # Opponent far ahead on army, as when they out-expand us.
    own(frame, 3 * W + 3, 60, player=1)
    frame["scores"] = [{"army": 500, "land": 95}, {"army": 1040, "land": 200}]

    board = Board(frame, 0)
    reserve = defence_reserve(board, general)
    assert reserve <= board.army(general), (
        f"reserve {reserve} exceeds the general's {board.army(general)} army"
    )
    moves, _ = plan(board, 3)
    assert moves, "a 220-army general must still be able to act"
    assert_legal(board, moves)


def test_walks_a_big_stack_to_an_affordable_city():
    frame = blank_frame(tick=300)
    general = 10 * W + 10
    city = general + 4 * W
    frame["terrain"][general] = GENERAL
    own(frame, general, 100)
    for step in (1, 2, 3):
        cell = general + step * W
        frame["terrain"][cell] = PLAIN
        frame["owners"][cell] = NEUTRAL
        frame["armies"][cell] = 0
        frame["visible"][cell] = True
    for offset in (-1, 1, -W):
        frame["terrain"][general + offset] = PLAIN
        frame["owners"][general + offset] = NEUTRAL
        frame["armies"][general + offset] = 0
        frame["visible"][general + offset] = True
    frame["terrain"][city] = CITY
    frame["owners"][city] = NEUTRAL
    frame["armies"][city] = 45
    frame["visible"][city] = True

    board = Board(frame, 0)
    moves, mode = plan(board, 4)
    assert mode == "expand", mode
    assert moves[0]["to"] == general + W, "first step should head for the city"
    assert moves[-1]["to"] == city, f"should reach and take the city: {moves}"
    assert_legal(board, moves)


def test_early_contact_does_not_freeze_the_opening():
    """A distant enemy sighting must not switch the midgame garrison on at t80."""
    frame = blank_frame(tick=80)
    general = 5 * W + 5
    frame["terrain"][general] = GENERAL
    own(frame, general, 20)
    for offset in (-1, 1, -W, W):
        own(frame, general + offset, 1)
    own(frame, 5 * W + 20, 30, player=1)
    frame["scores"] = [{"army": 30, "land": 19}, {"army": 90, "land": 40}]

    board = Board(frame, 0)
    assert defence_reserve(board, general) <= 1, "no approaching stack, no reserve"
    moves, _ = plan(board, 2)
    assert moves, "a 20-army general with a distant enemy must keep expanding"
    assert_legal(board, moves)


def test_press_needs_an_edge_to_start_but_less_to_continue():
    """At 0.8x their army: no fresh press, but an ongoing press carries on."""
    frame = blank_frame(tick=400)
    general = 12 * W + 2
    frame["terrain"][general] = GENERAL
    own(frame, general, 60)
    own(frame, 12 * W + 3, 40)
    for step in range(10, 20):
        own(frame, 12 * W + step, 5, player=1)
    # Their general is in sight but out of lethal reach: press territory.
    frame["terrain"][12 * W + 19] = GENERAL
    frame["scores"] = [{"army": 100, "land": 2}, {"army": 125, "land": 10}]

    board = Board(frame, 0)
    fresh, _ = decide_mode(board, general, False, previous="expand")
    ongoing, _ = decide_mode(board, general, False, previous="press")
    assert fresh != "press", f"0.8x is not enough of an edge to start: {fresh}"
    assert ongoing == "press", f"0.8x should still continue an attack: {ongoing}"


def test_march_collects_friendly_army_on_the_way():
    """Pressing takes the fat row; plain expansion takes the straight line."""
    frame = blank_frame(tick=400)
    general = 20 * W + 20
    frame["terrain"][general] = GENERAL
    own(frame, general, 5)
    source = 12 * W + 2
    own(frame, source, 40)
    target = 12 * W + 6
    own(frame, target, 3, player=1)
    for step in (3, 4, 5):
        own(frame, 12 * W + step, 1)
    for step in (2, 3, 4, 5, 6):
        own(frame, 11 * W + step, 30)

    board = Board(frame, 0)
    straight = _walk(_Sim(board), [target], general, 1, mode="expand")
    collecting = _walk(_Sim(board), [target], general, 1, mode="press")
    assert straight["to"] == source + 1, straight
    assert collecting["to"] == source - W, collecting


def test_keeps_expanding_while_the_map_is_still_open():
    """A lead at t300 with hundreds of neutral tiles is not a reason to press."""
    frame = blank_frame(tick=300)
    general = 12 * W + 2
    frame["terrain"][general] = GENERAL
    own(frame, general, 80)
    for step in range(3, 8):
        own(frame, 12 * W + step, 4)
    for step in range(14, 20):
        own(frame, 12 * W + step, 3, player=1)
    frame["scores"] = [{"army": 320, "land": 100}, {"army": 199, "land": 58}]

    board = Board(frame, 0)
    mode, _ = decide_mode(board, general, False, previous="expand")
    assert mode == "expand", f"open map with a lead should expand, got {mode}"


def test_answers_a_stack_at_the_general_before_it_strikes():
    frame = blank_frame(tick=500)
    general = 12 * W + 8
    frame["terrain"][general] = GENERAL
    own(frame, general, 100)
    own(frame, general + 1, 90, player=1)
    own(frame, general - 1, 8)
    frame["scores"] = [{"army": 300, "land": 60}, {"army": 400, "land": 60}]

    board = Board(frame, 0)
    mode, _ = decide_mode(board, general)
    assert mode == "defend", f"a 90 beside a 100 garrison must trigger defend, got {mode}"
    moves, _ = plan(board, 1)
    assert moves and moves[0] == {"from": general - 1, "to": general, "half": False}, (
        f"the neighbour should step onto the general first: {moves}"
    )

    frame["owners"][general - 1] = NEUTRAL
    frame["armies"][general - 1] = 0
    frame["armies"][general] = 200
    board = Board(frame, 0)
    moves, _ = plan(board, 1)
    assert moves and moves[0] == {"from": general, "to": general + 1, "half": True}, (
        f"with no guard, half the garrison should remove the stack: {moves}"
    )


def test_skips_neutral_cities_it_cannot_afford():
    frame = blank_frame(tick=200)
    general = 8 * W + 8
    city = 8 * W + 9
    frame["terrain"][general] = GENERAL
    frame["terrain"][city] = CITY
    own(frame, general, 12)
    frame["owners"][city] = NEUTRAL
    frame["armies"][city] = 45
    frame["visible"][city] = True

    board = Board(frame, 0)
    moves, _ = plan(board, 2)
    assert all(move["to"] != city for move in moves), "cannot take a 45-army city with 12"
    assert_legal(board, moves)


if __name__ == "__main__":
    passed = 0
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
            print(f"  ok  {name}")
            passed += 1
    print(f"{passed} passed")
