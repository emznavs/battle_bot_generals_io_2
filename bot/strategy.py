from .config import (
    CITY,
    CITY_ARMY_MARGIN,
    CITY_MAX_WALK,
    CITY_MIN_TICK,
    CONTACT_MID,
    CONTACT_NEAR,
    DEFEND_RATIO,
    GARRISON_CAP_OF_MINE,
    GARRISON_MIN_TICK,
    GARRISON_SHARE,
    GATHER_MIN_TICK,
    GATHER_RATIO,
    GENERAL_RUN_MIN,
    GUARD_MIN,
    IMPASSABLE,
    MARCH_FAT_ARMY,
    PRESS_DOMINANCE,
    PRESS_ENTER_RATIO,
    PRESS_MIN_TICK,
    PRESS_NEUTRAL_FLOOR,
    PRESS_ROOM_RATIO,
    PRESS_STAY_RATIO,
    SATELLITE_RUN_MIN,
    RESERVE_FAR,
    RESERVE_MID,
    RESERVE_NEAR,
    STACK_RATIO_ALARM,
    UNSEEN,
)

KILL_MARGIN = 2


class _Sim:
    """Our own moves applied forward, so a whole path can be queued at once.

    The opponent is not modelled: this exists to keep the move queue full, not
    to predict the game.
    """

    def __init__(self, board):
        self.board = board
        self.owners = list(board.owners)
        self.armies = board.armies()
        self.terrain = board.terrain
        self.neighbours = board.neighbours
        self.me = board.me
        self.foe = board.foe
        self.tick = board.tick

    def passable(self, index):
        return self.terrain[index] not in IMPASSABLE

    def mine(self, index):
        return self.owners[index] == self.me

    def my_tiles(self):
        return [i for i, owner in enumerate(self.owners) if owner == self.me]

    def apply(self, source, target, half):
        army = self.armies[source]
        if army < 2 or self.owners[source] != self.me:
            return False
        sent = army // 2 if half else army - 1
        self.armies[source] = army - sent
        if self.owners[target] == self.me:
            self.armies[target] += sent
        elif sent > self.armies[target]:
            self.owners[target] = self.me
            self.armies[target] = sent - self.armies[target]
        else:
            self.armies[target] -= sent
        return True


def _split(sim, source, general, reserve):
    """Choose full or half move so the general keeps its defence reserve."""
    army = sim.armies[source]
    if army < 2:
        return None
    if source != general or reserve <= 1:
        return False
    if army - army // 2 >= reserve and army // 2 >= 1:
        return True
    return None


def _sent(sim, source, half):
    army = sim.armies[source]
    return army // 2 if half else army - 1


def threat_to(board, general):
    """Army the strongest approaching enemy stack would still have on arrival.

    A stack crossing our land leaves one army behind per step, so a stack of A
    at distance d lands with roughly A - d. Comparing that against the general's
    garrison is what matters; a flat reserve loses to anyone who massed.
    """
    if general is None:
        return 0
    dist = board.distances([general])
    worst = 0
    for index in board.enemy_tiles():
        step = dist[index]
        if step < 0 or step > CONTACT_MID:
            continue
        worst = max(worst, board.army(index) - step)
    return max(0, worst)


def defence_reserve(board, general):
    if general is None:
        return RESERVE_FAR
    if not board.enemy_tiles():
        return RESERVE_FAR

    reserve = max(RESERVE_FAR, threat_to(board, general))
    if board.tick >= GARRISON_MIN_TICK:
        standing = int(GARRISON_SHARE * board.foe_score()["army"])
        reserve = max(reserve, standing)

    dist = board.distances([general])
    nearest = min((dist[i] for i in board.enemy_tiles() if dist[i] >= 0), default=-1)
    if 0 <= nearest <= CONTACT_NEAR:
        reserve = max(reserve, RESERVE_NEAR)
    elif 0 <= nearest <= CONTACT_MID:
        reserve = max(reserve, RESERVE_MID)

    # scores is not fog-filtered: army climbing without land means they are
    # massing out of sight rather than expanding.
    mine = board.my_score()
    foe = board.foe_score()
    if foe["land"] and mine["land"]:
        foe_ratio = foe["army"] / foe["land"]
        my_ratio = mine["army"] / max(1, mine["land"])
        if foe_ratio > my_ratio * STACK_RATIO_ALARM:
            reserve = max(reserve, RESERVE_MID)

    # The general only moves once it can leave the reserve behind, so an
    # unaffordable reserve is a permanent freeze rather than a defence.
    affordable = max(RESERVE_NEAR, int(GARRISON_CAP_OF_MINE * mine["army"]))
    return min(reserve, affordable)


def strike_plan(board, enemy_general):
    """Best stack that can reach the enemy general and still be lethal."""
    dist = board.distances([enemy_general])
    best = None
    for source in board.my_tiles():
        army = board.army(source)
        if army < 2 or dist[source] < 1:
            continue
        path = board.path_from(source, dist)
        if len(path) < 2 or path[-1] != enemy_general:
            continue
        steps = len(path) - 1
        cost = sum(board.army(cell) for cell in path[1:] if not board.mine(cell))
        needed = cost + steps + steps // 2 + KILL_MARGIN
        if army > needed and (best is None or army > best[1]):
            best = (source, army)
    return best[0] if best else None


def _neutral_targets(board, allow_city):
    targets = []
    for index, owner in enumerate(board.owners):
        if owner == board.me or owner == board.foe or not board.passable(index):
            continue
        if board.terrain[index] == CITY and not allow_city:
            continue
        targets.append(index)
    return targets


def press_target(board):
    """Deepest enemy tile: pushing at it drags our stack through their land.

    Their general sits behind their territory, and advancing reveals it once we
    are adjacent, at which point the lethal-strike check takes over.
    """
    enemies = board.enemy_tiles()
    if not enemies:
        return None
    outward = board.distances(board.my_tiles())
    reachable = [i for i in enemies if outward[i] >= 0]
    if not reachable:
        return None
    return max(reachable, key=lambda i: outward[i])


def _expansion_targets(sim, allow_city):
    targets = []
    for index, owner in enumerate(sim.owners):
        if owner == sim.me or not sim.passable(index):
            continue
        if sim.terrain[index] == CITY and owner != sim.foe and not allow_city:
            continue
        targets.append(index)
    return targets


def _best_capture(sim, general, reserve, allow_city, exclude=frozenset()):
    """Take a new cell this tick, preferring the smallest sufficient source.

    Small peripheral stacks are near-useless for anything else, so spending them
    on land keeps the big stack intact for the kill.
    """
    best_move = None
    best_value = 0.0
    for source in sim.my_tiles():
        if source in exclude or sim.armies[source] < 2:
            continue
        half = _split(sim, source, general, reserve)
        if half is None:
            continue
        sent = _sent(sim, source, half)
        if sent < 1:
            continue
        for target in sim.neighbours[source]:
            if sim.mine(target) or not sim.passable(target):
                continue
            defenders = sim.armies[target]
            is_city = sim.terrain[target] == CITY
            neutral_city = is_city and sim.owners[target] != sim.foe
            if neutral_city:
                if not allow_city or sent <= defenders + CITY_ARMY_MARGIN:
                    continue
            if sent <= defenders:
                continue
            value = 100.0
            if sim.owners[target] == sim.foe:
                # Taking their tile costs its defenders plus one. That trade
                # compounds a lead and bleeds a deficit: on equal land we fell
                # to 1075 army against 1630 by attacking tiles while weaker.
                # But a tile with one or two on it, typically our own border
                # they just nibbled, is the best trade on the board either way:
                # declining those is how SolomINT farmed our periphery.
                weaker = sim.board.my_score()["army"] < sim.board.foe_score()["army"]
                value += 25.0 if defenders <= 2 or not weaker else -25.0
            if sim.terrain[target] == UNSEEN:
                value += 5.0
            if neutral_city:
                value += 40.0
            # Mild preference for the stack already at the frontier: it keeps
            # capturing every tick, where a spent 2-army tile captures once.
            value += min(10.0, 0.2 * sim.armies[source])
            if value > best_value:
                best_value = value
                best_move = {"from": source, "to": target, "half": bool(half)}
    return best_move


def _city_run(sim, general, reserve, exclude=frozenset()):
    """Send the biggest stack that can take a neutral city to the nearest one.

    Both generals produce identically, so in the long games our garrison now
    produces, cities are the only production edge. A five-tick walk forgoes
    five tiles; a city returns that within twenty ticks and keeps paying.
    """
    known = sim.board.raw_armies
    cities = [
        index
        for index, code in enumerate(sim.terrain)
        if code == CITY
        and sim.owners[index] not in (sim.me, sim.foe)
        and known[index] is not None
    ]
    if not cities:
        return None
    dist = sim.board.distances(cities)
    best = None
    for source in sim.my_tiles():
        if source in exclude or sim.armies[source] < 2 or not 1 <= dist[source] <= CITY_MAX_WALK:
            continue
        half = _split(sim, source, general, reserve)
        if half is None:
            continue
        path = sim.board.path_from(source, dist)
        if len(path) < 2:
            continue
        city = path[-1]
        # One army stays behind per step, and the last step is the attack.
        arriving = _sent(sim, source, half) - (len(path) - 2)
        if arriving <= sim.armies[city] + CITY_ARMY_MARGIN:
            continue
        surplus = arriving - sim.armies[city]
        if best is None or surplus > best[0]:
            best = (surplus, {"from": source, "to": path[1], "half": bool(half)})
    return best[1] if best else None


def _walk(sim, targets, general, reserve, mode="expand", exclude=None):
    """Step the largest usable stack one cell along its shortest path.

    Walking costs a tick per step whatever the stack size, so a trip only pays
    for itself if enough army arrives to capture several cells. Dribbling the
    general out one army at a time pays that walk once per tile.
    """
    if not targets:
        return None
    dist = sim.board.distances(targets)
    best_move = None
    best_score = None
    for source in sim.my_tiles():
        if (exclude and source in exclude) or sim.armies[source] < 2 or dist[source] < 1:
            continue
        # A gathering stack stops beside the general as a mobile guard rather
        # than merging into a garrison the half-move rule would then freeze.
        if mode == "gather" and dist[source] <= 1:
            continue
        half = _split(sim, source, general, reserve)
        if half is None:
            continue
        if mode == "expand":
            floor = GENERAL_RUN_MIN if source == general else SATELLITE_RUN_MIN
            if _sent(sim, source, half) - dist[source] < floor:
                continue
        path = sim.board.path_from(source, dist)
        if len(path) < 2:
            continue
        score = sim.armies[source] - dist[source]
        if best_score is None or score > best_score:
            best_score = score
            best_move = {"from": source, "to": path[1], "half": bool(half)}
    if best_move and mode in ("press", "hunt", "gather"):
        step = _collecting_step(sim, best_move["from"], targets)
        if step is not None:
            best_move["to"] = step
    return best_move


def _collecting_step(sim, source, targets):
    """First step of the route that absorbs the most friendly army en route.

    Arriving on friendly land adds armies, so a march through our fattest
    tiles raises its concentration without spending ticks on a gather.
    """

    def cost(cell):
        if sim.owners[cell] != sim.me:
            return 1.0
        return 1.0 - 0.5 * min(1.0, sim.armies[cell] / MARCH_FAT_ARMY)

    path = sim.board.cheapest_path(source, targets, cost)
    return path[1] if len(path) >= 2 else None


def _defend_locally(sim, general, reserve, emergency):
    """Answer a stack adjacent to the general with the priority rules.

    Friendly reinforcement resolves before an enemy attack in the same tick,
    so a neighbour stepping onto the general lands first. Failing that, a
    half-move sortie removes the stack while the other half stays home: a 208
    stack grew from 15 beside our general over 160 ticks while we did nothing.
    Outside an emergency the half left behind must still cover the reserve.
    """
    if general is None:
        return None
    adjacent = [(sim.armies[n], n) for n in sim.neighbours[general] if sim.owners[n] == sim.foe]
    if not adjacent:
        return None
    guards = [
        (sim.armies[n], n)
        for n in sim.neighbours[general]
        if sim.owners[n] == sim.me and sim.armies[n] >= 2
    ]
    if guards:
        return {"from": max(guards)[1], "to": general, "half": False}
    garrison = sim.armies[general]
    target_army, target = max(adjacent)
    sent = garrison // 2
    remaining = garrison - sent
    # The half left behind must beat the next threat in range, not an
    # abstract reserve: a 28 beside the general is what the reserve is for,
    # and refusing to remove it is how 28 became 208.
    dist = sim.board.distances([general])
    next_threat = 0
    for index, owner in enumerate(sim.owners):
        if owner != sim.foe or index == target or not 0 <= dist[index] <= CONTACT_MID:
            continue
        next_threat = max(next_threat, sim.armies[index] - dist[index])
    floor = next_threat + 1 if emergency else max(next_threat + 1, RESERVE_NEAR)
    if sent > target_army and remaining >= floor:
        return {"from": general, "to": target, "half": True}
    return None


def _next_move(sim, general, reserve, mode, focus, allow_city):
    move = _defend_locally(sim, general, reserve, emergency=(mode == "defend"))
    if move:
        return move
    if mode in ("hunt", "press") and focus is not None:
        move = _walk(sim, [focus], general, reserve, mode)
        if move:
            return move
    # The guard beside the general stays put for everything but a strike:
    # otherwise expansion walks it straight back out and gather refetches it.
    keep = _guards(sim, general)
    if mode in ("defend", "gather"):
        move = _walk(sim, [focus], general, reserve, mode, exclude=keep | {general})
        if move:
            return move
    # Before captures, or an always-available capture starves the run.
    if allow_city:
        move = _city_run(sim, general, reserve, exclude=keep)
        if move:
            return move
    move = _best_capture(sim, general, reserve, allow_city, exclude=keep)
    if move:
        return move
    return _walk(sim, _expansion_targets(sim, allow_city), general, reserve, mode, exclude=keep)


def _guards(sim, general):
    """Stacks beside the general worth holding back from expansion.

    Only while the opponent is massing or a threat is in range: otherwise a
    big stack beside the general is the general's own run just leaving.
    """
    if general is None:
        return set()
    board = sim.board
    if not (out_concentrated(board) or threat_to(board, general) > 0):
        return set()
    return {
        n
        for n in sim.neighbours[general]
        if sim.owners[n] == sim.me and sim.armies[n] >= GUARD_MIN
    }


def decide_mode(board, general, allow_city=False, previous="expand"):
    """Re-derived every frame; a v3 general trade moves our general mid-game.

    `previous` only sets the press threshold: a lower bar to continue an attack
    than to start one, so a press neither bleeds to parity nor flaps.
    """
    if general is None:
        return "expand", None
    if threat_to(board, general) > board.army(general) * DEFEND_RATIO:
        return "defend", general
    enemy_general = board.enemy_general()
    if enemy_general is not None and strike_plan(board, enemy_general) is not None:
        return "hunt", enemy_general

    room = len(_neutral_targets(board, allow_city))
    boxed_in = room < PRESS_NEUTRAL_FLOOR
    filling = room < board.my_score()["land"] * PRESS_ROOM_RATIO
    # Free land is the better investment while it lasts: only press once the
    # map is filling up or the general is actually in sight. A clock alone
    # abandoned 210 open tiles with a winning economy.
    mine, foe = board.my_score(), board.foe_score()
    dominant = (
        mine["army"] >= foe["army"] * PRESS_DOMINANCE
        and mine["land"] >= foe["land"] * PRESS_DOMINANCE
    )
    ready = board.tick >= PRESS_MIN_TICK and (filling or dominant or enemy_general is not None)
    ratio = PRESS_STAY_RATIO if previous in ("press", "hunt") else PRESS_ENTER_RATIO
    strong = board.my_score()["army"] >= board.foe_score()["army"] * ratio
    # With no neutral land left, hoarding army only loses slowly: their general
    # is the one remaining way to win, so press even from behind.
    if (boxed_in or ready) and (strong or boxed_in):
        target = enemy_general or press_target(board)
        if target is not None:
            return "press", target
    if board.tick >= GATHER_MIN_TICK and out_concentrated(board) and not guard_in_place(board, general):
        return "gather", general
    return "expand", None


def out_concentrated(board):
    """Their army per tile exceeds ours: they are massing while we spread."""
    mine, foe = board.my_score(), board.foe_score()
    if not mine["land"] or not foe["land"]:
        return False
    return foe["army"] / foe["land"] > (mine["army"] / mine["land"]) * GATHER_RATIO


def guard_in_place(board, general):
    return any(
        board.mine(n) and board.army(n) >= GUARD_MIN for n in board.neighbours[general]
    )


def plan(board, want, pending=(), previous="expand"):
    general = board.my_general()
    reserve = defence_reserve(board, general)
    city_ready = board.tick >= CITY_MIN_TICK
    mode, focus = decide_mode(board, general, city_ready, previous)
    allow_city = city_ready and mode == "expand"

    sim = _Sim(board)
    # Moves already sitting in the server queue execute before anything we add
    # now. Planning against the unmodified board picks sources they will have
    # already drained, and those moves fail on execution.
    for queued in pending:
        sim.apply(queued["from"], queued["to"], queued.get("half", False))
    moves = []
    for _ in range(max(1, want)):
        move = _next_move(sim, general, reserve, mode, focus, allow_city)
        if move is None:
            break
        sim.apply(move["from"], move["to"], move["half"])
        moves.append(move)
    return moves, mode
