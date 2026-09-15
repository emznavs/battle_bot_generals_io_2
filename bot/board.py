import heapq
from collections import deque
from functools import lru_cache

from .config import GENERAL, IMPASSABLE


@lru_cache(maxsize=4)
def neighbour_table(width, height):
    table = []
    for index in range(width * height):
        x, y = index % width, index // width
        adjacent = []
        if x > 0:
            adjacent.append(index - 1)
        if x < width - 1:
            adjacent.append(index + 1)
        if y > 0:
            adjacent.append(index - width)
        if y < height - 1:
            adjacent.append(index + width)
        table.append(tuple(adjacent))
    return tuple(table)


class Board:
    """Read-only view of one `state.frame` from our player's perspective."""

    def __init__(self, frame, me):
        self.width = frame["width"]
        self.height = frame["height"]
        self.size = self.width * self.height
        self.tick = frame["tick"]
        self.terrain = frame["terrain"]
        self.owners = frame["owners"]
        self.raw_armies = frame["armies"]
        self.visible = frame["visible"]
        self.scores = frame["scores"]
        self.outcome = frame.get("outcome")
        self.me = me
        self.foe = 1 - me
        self.neighbours = neighbour_table(self.width, self.height)

    def army(self, index):
        value = self.raw_armies[index]
        return 0 if value is None else value

    def armies(self):
        return [0 if value is None else value for value in self.raw_armies]

    def passable(self, index):
        return self.terrain[index] not in IMPASSABLE

    def mine(self, index):
        return self.owners[index] == self.me

    def my_tiles(self):
        return [i for i, owner in enumerate(self.owners) if owner == self.me]

    def enemy_tiles(self):
        return [i for i, owner in enumerate(self.owners) if owner == self.foe]

    def my_general(self):
        return self._find_general(self.me)

    def enemy_general(self):
        return self._find_general(self.foe)

    def _find_general(self, player):
        for index, code in enumerate(self.terrain):
            if code == GENERAL and self.owners[index] == player:
                return index
        return None

    def my_score(self):
        return self.scores[self.me]

    def foe_score(self):
        return self.scores[self.foe]

    def distances(self, sources, blocked=frozenset()):
        """Multi-source BFS over passable cells. -1 means unreachable."""
        dist = [-1] * self.size
        queue = deque()
        for source in sources:
            if dist[source] == -1:
                dist[source] = 0
                queue.append(source)
        while queue:
            current = queue.popleft()
            step = dist[current] + 1
            for nxt in self.neighbours[current]:
                if dist[nxt] != -1 or nxt in blocked or not self.passable(nxt):
                    continue
                dist[nxt] = step
                queue.append(nxt)
        return dist

    def cheapest_path(self, source, targets, step_cost):
        """Dijkstra from source to the nearest target; step_cost prices entering a cell."""
        wanted = set(targets)
        best = {source: 0.0}
        parent = {}
        heap = [(0.0, source)]
        while heap:
            cost, current = heapq.heappop(heap)
            if cost > best.get(current, float("inf")):
                continue
            if current in wanted and current != source:
                path = [current]
                while path[-1] != source:
                    path.append(parent[path[-1]])
                return path[::-1]
            for nxt in self.neighbours[current]:
                if not self.passable(nxt):
                    continue
                candidate = cost + step_cost(nxt)
                if candidate < best.get(nxt, float("inf")):
                    best[nxt] = candidate
                    parent[nxt] = current
                    heapq.heappush(heap, (candidate, nxt))
        return []

    def path_from(self, source, dist):
        """Walk a distance field downhill from source to its nearest target."""
        if dist[source] <= 0:
            return []
        path = [source]
        current = source
        while dist[current] > 0:
            for nxt in self.neighbours[current]:
                if dist[nxt] == dist[current] - 1:
                    path.append(nxt)
                    current = nxt
                    break
            else:
                return path
        return path
