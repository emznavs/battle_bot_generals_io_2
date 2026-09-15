import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.board import Board
from bot.config import CITY, GENERAL, HIDDEN, MOUNTAIN, NEUTRAL, PLAIN, UNSEEN
from bot.strategy import decide_mode, defence_reserve, plan

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
