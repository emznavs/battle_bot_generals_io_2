import asyncio
import json
import time

import websockets

from .board import Board
from .config import QUEUE_MAX, QUEUE_TARGET, RECONNECT_BACKOFF_MAX, bot_token, ws_url
from .strategy import plan


def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


class ArenaBot:
    def __init__(self, token, games=0, verbose=True):
        self.token = token
        self.games = games
        self.verbose = verbose
        self.completed = 0
        self.results = []
        self._reset_match()

    def _reset_match(self):
        self.match_id = None
        self.player = None
        self.sequence = 1
        self.planned_tick = -1
        self.mode = "expand"
        self.executed = 0
        self.failed = 0

    async def run(self):
        backoff = 1
        while True:
            try:
                async with websockets.connect(
                    ws_url(), max_size=2**20, ping_interval=10, ping_timeout=20
                ) as socket:
                    backoff = 1
                    async for raw in socket:
                        if await self._handle(socket, json.loads(raw)):
                            return self.results
            # WebSocketException covers a rejected handshake (e.g. a transient
            # 403 while the arena restarts) as well as a dropped connection.
            # Only a revoked credential, raised as RuntimeError, should exit.
            except (
                OSError,
                asyncio.TimeoutError,
                websockets.exceptions.WebSocketException,
            ) as error:
                log(f"connection lost ({type(error).__name__}: {error}); retry in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX)

    async def _send(self, socket, payload):
        await socket.send(json.dumps(payload))

    async def _handle(self, socket, message):
        kind = message.get("type")

        if kind == "hello":
            log(f"hello: api={message['api_version']} rules={message['rules_version']}")
            await self._send(socket, {"type": "authenticate", "token": self.token})

        elif kind == "authenticated":
            log(f"authenticated as {message['name']} ({message['kind']})")
            # Human challenges block ranked pairing while they run and never
            # affect Elo, so during a ranked event they only cost games.
            await self._send(
                socket, {"type": "queue", "enabled": True, "accept_casual": False}
            )

        elif kind == "queue_status":
            log(f"queue: ranked={message['enabled']} casual={message['accept_casual']}")

        elif kind == "match_start":
            self._reset_match()
            self.match_id = message["match_id"]
            self.player = message["player_index"]
            side = "blue" if self.player == 0 else "red"
            log(
                f"match {self.match_id[:8]} as {side} vs "
                f"{message['players'][1 - self.player]} "
                f"(ranked={message['ranked']}, phase={message['phase']})"
            )
            if not message["ranked"]:
                # Casual games never change Elo and block ranked pairing while
                # they run; conceding costs nothing and frees the bot at once.
                log("  casual game: conceding to return to ranked queue")
                await self._send(socket, {"type": "surrender", "match_id": self.match_id})
                return False
            await self._send(socket, {"type": "ready", "match_id": self.match_id})

        elif kind == "state":
            await self._on_state(socket, message)

        elif kind == "action_result":
            if message["executed"]:
                self.executed += 1
            else:
                self.failed += 1

        elif kind == "match_end":
            outcome = message["outcome"]
            verdict = "draw"
            if outcome.get("winner") is not None:
                verdict = "WON" if outcome["winner"] == self.player else "LOST"
            attempted = self.executed + self.failed
            waste = 100.0 * self.failed / attempted if attempted else 0.0
            log(
                f"match {message['match_id'][:8]} {verdict} ({outcome['reason']}) "
                f"moves={attempted} failed={self.failed} ({waste:.0f}%)"
            )
            self.results.append({"match_id": message["match_id"], "outcome": outcome})
            self.completed += 1
            self._reset_match()
            if self.games and self.completed >= self.games:
                await self._send(
                    socket, {"type": "queue", "enabled": False, "accept_casual": False}
                )
                return True

        elif kind == "revoked":
            raise RuntimeError("credential revoked or identity replaced")

        elif kind == "error":
            log(f"server error {message['code']}: {message['message']}")
            if message["code"] in ("invalid_token", "authentication_required"):
                raise RuntimeError(message["message"])

        return False

    async def _on_state(self, socket, message):
        if message["match_id"] != self.match_id:
            return
        frame = message["frame"]
        self.sequence = max(self.sequence, message["next_sequence"])
        if frame.get("outcome") or frame["tick"] <= self.planned_tick:
            return

        pending = len(message["queued_moves"])
        want = min(QUEUE_TARGET, QUEUE_MAX) - pending
        if want <= 0:
            return

        board = Board(frame, self.player)
        moves, mode = plan(board, want, message["queued_moves"], self.mode)
        self.planned_tick = frame["tick"]
        self.mode = mode

        for move in moves:
            await self._send(
                socket,
                {
                    "type": "move",
                    "match_id": self.match_id,
                    "sequence": self.sequence,
                    "action": move,
                },
            )
            self.sequence += 1

        if self.verbose and frame["tick"] % 20 == 0:
            mine, foe = board.my_score(), board.foe_score()
            log(
                f"  t{frame['tick']:<4} {mode:<6} "
                f"me {mine['army']:>4}a/{mine['land']:>3}l  "
                f"foe {foe['army']:>4}a/{foe['land']:>3}l  "
                f"queued={pending}+{len(moves)}"
            )


async def main(games=0):
    token = bot_token()
    if not token:
        raise SystemExit("BOT_TOKEN is not set")
    await ArenaBot(token, games=games).run()
