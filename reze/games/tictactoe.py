"""
Tic-tac-toe for chats.

A userbot cannot send inline buttons, so moves are plain messages: the player
whose turn it is sends a number 1-9 in the chat and the board message is edited
in place. Play against another member (reply to them with ``.tictactoe``) or
against Reze (minimax AI, unbeatable).
"""

import time
from typing import Any, Dict, List, Optional

from reze.ui import ascii

LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
IDLE_SECONDS = 600


def winner(board: List[str]) -> Optional[str]:
    for a, b, c in LINES:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return None


def is_full(board: List[str]) -> bool:
    return all(board)


def best_move(board: List[str], me: str = "O") -> int:
    """Perfect-play move for *me* (minimax with alpha-beta; 9 cells is instant)."""
    other = "X" if me == "O" else "O"

    def score(state: List[str], turn: str, alpha: int, beta: int, depth: int) -> int:
        won = winner(state)
        if won == me:
            return 10 - depth
        if won == other:
            return depth - 10
        if is_full(state):
            return 0
        best = -100 if turn == me else 100
        for i in range(9):
            if state[i]:
                continue
            state[i] = turn
            value = score(state, other if turn == me else me, alpha, beta, depth + 1)
            state[i] = ""
            if turn == me:
                best = max(best, value)
                alpha = max(alpha, best)
            else:
                best = min(best, value)
                beta = min(beta, best)
            if beta <= alpha:
                break
        return best

    options = [i for i in range(9) if not board[i]]
    if not options:
        raise ValueError("The board is full.")
    scored = []
    for i in options:
        board[i] = me
        scored.append((score(board, other, -100, 100, 1), -abs(i - 4), i))
        board[i] = ""
    return max(scored)[2]


def render(board: List[str], title: str, lines: List[str]) -> str:
    cells = [board[i] or str(i + 1) for i in range(9)]
    grid = [
        f" {cells[0]} │ {cells[1]} │ {cells[2]} ",
        "───┼───┼───",
        f" {cells[3]} │ {cells[4]} │ {cells[5]} ",
        "───┼───┼───",
        f" {cells[6]} │ {cells[7]} │ {cells[8]} ",
    ]
    return ascii.frame(title, grid + [""] + lines)


class Game:
    def __init__(self, chat_id: int, x_id: int, x_name: str, o_id: Optional[int], o_name: str):
        self.chat_id = chat_id
        self.players = {"X": (x_id, x_name), "O": (o_id, o_name)}  # o_id None = Reze AI
        self.board: List[str] = [""] * 9
        self.turn = "X"
        self.message: Any = None
        self.touched = time.time()

    @property
    def vs_ai(self) -> bool:
        return self.players["O"][0] is None

    def expired(self) -> bool:
        return time.time() - self.touched > IDLE_SECONDS

    def view(self, footer: Optional[str] = None) -> str:
        x, o = self.players["X"][1], self.players["O"][1]
        status = footer or f"Turn: {self.turn} ({self.players[self.turn][1]}) - send 1-9"
        return render(self.board, "Tic-Tac-Toe", [f"X: {x}", f"O: {o}", status])

    def play(self, symbol: str, cell: int) -> str:
        """Apply a move. Returns '', 'win', or 'draw'; raises ValueError on illegal moves."""
        if not 1 <= cell <= 9 or self.board[cell - 1]:
            raise ValueError("That cell is not free.")
        self.board[cell - 1] = symbol
        self.touched = time.time()
        if winner(self.board):
            return "win"
        if is_full(self.board):
            return "draw"
        self.turn = "O" if symbol == "X" else "X"
        return ""


class TicTacToeManager:
    def __init__(self):
        self.games: Dict[int, Game] = {}

    def get(self, chat_id: int) -> Optional[Game]:
        game = self.games.get(chat_id)
        if game and game.expired():
            self.games.pop(chat_id, None)
            return None
        return game

    def start(self, chat_id: int, x_id: int, x_name: str, o_id: Optional[int], o_name: str) -> Game:
        if self.get(chat_id):
            raise ValueError("A game is already running in this chat. Use .tictactoe stop first.")
        game = Game(chat_id, x_id, x_name, o_id, o_name or "Reze")
        self.games[chat_id] = game
        return game

    def stop(self, chat_id: int) -> bool:
        return self.games.pop(chat_id, None) is not None

    async def on_message(self, event: Any) -> None:
        """Hook for every incoming/outgoing message: apply a move if it is one."""
        chat_id = getattr(event, "chat_id", None)
        game = self.games.get(chat_id) if chat_id is not None else None
        if game is None:
            return
        if game.expired():
            self.games.pop(chat_id, None)
            return
        message = getattr(event, "message", event)
        text = (getattr(message, "text", "") or "").strip()
        if len(text) != 1 or text not in "123456789":
            return
        sender = getattr(event, "sender_id", None) or getattr(message, "sender_id", None)
        if sender != game.players[game.turn][0]:
            return

        symbol = game.turn
        try:
            result = game.play(symbol, int(text))
        except ValueError:
            return
        await self._delete(message)

        footer = None
        if result == "win":
            footer = f"{game.players[symbol][1]} ({symbol}) wins!"
        elif result == "draw":
            footer = "Draw - nobody wins."
        elif game.vs_ai and game.turn == "O":
            move = best_move(game.board, "O")
            ai_result = game.play("O", move + 1)
            if ai_result == "win":
                footer = "Reze (O) wins!"
            elif ai_result == "draw":
                footer = "Draw - nobody wins."

        await self._show(game, footer)
        if footer:
            self.games.pop(chat_id, None)

    @staticmethod
    async def _delete(message: Any) -> None:
        try:
            await message.delete()
        except Exception:  # noqa: BLE001 - only admins can delete other people's messages
            pass

    @staticmethod
    async def _show(game: Game, footer: Optional[str]) -> None:
        text = game.view(footer)
        try:
            if game.message is not None:
                await game.message.edit(text)
        except Exception:  # noqa: BLE001 - e.g. message not modified
            pass


tictactoe_manager = TicTacToeManager()
