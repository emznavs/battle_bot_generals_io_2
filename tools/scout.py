"""Read-only arena inspection: standings, our results, and replay economy curves.

    python -m tools.scout board
    python -m tools.scout history [N]
    python -m tools.scout replay MATCH_ID [step]
"""

import json
import sys
import urllib.error
import urllib.request

from bot.main import load_env


def get(path, token):
    request = urllib.request.Request(
        path, headers={"Authorization": f"Bearer {token}"} if token else {}
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read() or "null")
    except urllib.error.HTTPError as error:
        body = json.loads(error.read() or "{}")
        raise SystemExit(f"HTTP {error.code}: {body.get('code')}: {body.get('message')}")


def board(base, token):
    bots = get(f"{base}/api/v1/bots", token)
    ranked = sorted(bots, key=lambda b: -b["rating"])
    print(f"{'#':>3} {'bot':28} {'elo':>7} {'W-L-D':>10} {'status':12} casual")
    for position, bot in enumerate(ranked, 1):
        record = f"{bot['wins']}-{bot['losses']}-{bot['draws']}"
        mark = " <-- us" if bot["name"] == "beeline" else ""
        print(
            f"{position:>3} {bot['name'][:28]:28} {bot['rating']:7.1f} {record:>10} "
            f"{bot['status']:12} {str(bot['accept_casual']):5}{mark}"
        )


def history(base, token, limit):
    page = get(f"{base}/api/v1/history?limit={limit}", token)
    items = page.get("items", [])
    if not items:
        print("no matches yet")
        return
    wins = losses = draws = 0
    for item in items:
        outcome = item.get("outcome") or {}
        players = item.get("players") or ["?", "?"]
        us = 0 if players[0] == "beeline" else 1
        winner = outcome.get("winner")
        if winner is None:
            verdict, draws = "draw", draws + 1
        elif winner == us:
            verdict, wins = "WON ", wins + 1
        else:
            verdict, losses = "LOST", losses + 1
        changes = item.get("rating_changes")
        delta = f"{changes[us]:+.1f}" if changes else "  n/a"
        print(
            f"{item['id']}  {verdict}  {delta:>6}  "
            f"{'ranked' if item.get('ranked') else 'casual':6} "
            f"t={str(item.get('ticks')):>5}  {outcome.get('reason','?'):16} "
            f"vs {players[1 - us]}"
        )
    print(f"\n{wins}W {losses}L {draws}D over {len(items)} matches")


def replay(base, token, match_id, step):
    """Land and army per tick for both sides: shows where a game was decided."""
    tick = 0
    rows = []
    while tick is not None:
        page = get(
            f"{base}/api/v1/history/{match_id}/frames"
            f"?from_tick={tick}&limit=200&perspective=full",
            token,
        )
        for frame in page.get("frames", []):
            rows.append((frame["tick"], frame["scores"]))
        tick = page.get("next_tick")
    if not rows:
        print("no frames (replay may still be locked)")
        return
    print(f"{'tick':>5} {'p0 army':>8} {'p0 land':>8} {'p1 army':>8} {'p1 land':>8}")
    for at, scores in rows:
        if at % step == 0 or at == rows[-1][0]:
            print(
                f"{at:>5} {scores[0]['army']:>8} {scores[0]['land']:>8} "
                f"{scores[1]['army']:>8} {scores[1]['land']:>8}"
            )
    first, last = rows[0][1], rows[-1][1]
    span = max(1, rows[-1][0])
    for side in (0, 1):
        gained = last[side]["land"] - first[side]["land"]
        print(f"p{side}: {gained:+} land over {span} ticks = {gained/span:.2f} land/tick")


if __name__ == "__main__":
    load_env()
    import os

    base = os.environ.get("ARENA_URL", "").rstrip("/")
    token = os.environ.get("ARENA_TOKEN", "")
    if not base:
        raise SystemExit("ARENA_URL is not set")
    command = sys.argv[1] if len(sys.argv) > 1 else "board"
    if command == "board":
        board(base, token)
    elif command == "history":
        history(base, token, int(sys.argv[2]) if len(sys.argv) > 2 else 25)
    elif command == "replay":
        if len(sys.argv) < 3:
            raise SystemExit("usage: scout replay MATCH_ID [step]")
        replay(base, token, sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 25)
    else:
        raise SystemExit(__doc__)
