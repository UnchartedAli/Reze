"""
Fun commands: quote, joke, roast, ship, truth, dare, tictactoe.

Content is local (no network) and kept friendly enough for group chats.
`.calc` and `.meme` already exist elsewhere and are intentionally not redefined.
"""

import hashlib
import random
from typing import List, Optional

from reze.command_router import CommandContext, router
from reze.games.tictactoe import tictactoe_manager
from reze.ui import ascii

CATEGORY = "Fun"

QUOTES = [
    ("The only thing we have to fear is fear itself.", "Franklin D. Roosevelt"),
    ("I think, therefore I am.", "Rene Descartes"),
    ("The unexamined life is not worth living.", "Socrates (as reported by Plato)"),
    ("A journey of a thousand miles begins with a single step.", "Lao Tzu (Tao Te Ching)"),
    ("Veni, vidi, vici.", "Julius Caesar"),
    ("Knowledge is power.", "Francis Bacon"),
    ("That which does not kill us makes us stronger.", "Friedrich Nietzsche"),
    ("Well done is better than well said.", "Benjamin Franklin"),
    ("Rome wasn't built in a day.", "Proverb"),
    ("Fall seven times, stand up eight.", "Japanese proverb"),
    ("The best time to plant a tree was twenty years ago. The second best time is now.", "Proverb"),
    ("A smooth sea never made a skilled sailor.", "Proverb"),
    ("Slow and steady wins the race.", "Aesop"),
    ("No act of kindness, no matter how small, is ever wasted.", "Aesop"),
    ("Premature optimization is the root of all evil.", "Donald Knuth"),
    ("Talk is cheap. Show me the code.", "Linus Torvalds"),
    ("Programs must be written for people to read, and only incidentally for machines to execute.", "Harold Abelson"),
    ("Simplicity is prerequisite for reliability.", "Edsger W. Dijkstra"),
    ("First, solve the problem. Then, write the code.", "John Johnson"),
    ("Make it work, make it right, make it fast.", "Kent Beck"),
    ("Done is better than perfect.", "Proverb of the startup world"),
    ("Hope for the best, prepare for the worst.", "Proverb"),
    ("Actions speak louder than words.", "Proverb"),
    ("Every expert was once a beginner.", "Proverb"),
]

JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I would tell you a UDP joke, but you might not get it.",
    "There are 10 kinds of people: those who understand binary and those who don't.",
    "A SQL query walks into a bar, walks up to two tables and asks: 'Can I join you?'",
    "Why did the developer go broke? He used up all his cache.",
    "To understand recursion, you must first understand recursion.",
    "How many programmers does it take to change a light bulb? None, that's a hardware problem.",
    "I told my computer I needed a break. It said: 'No problem, I'll go to sleep.'",
    "Why was the JavaScript developer sad? Because he didn't Node how to Express himself.",
    "My code never has bugs. It just develops random features.",
    "Why do Java developers wear glasses? Because they don't C#.",
    "!false - it's funny because it's true.",
    "A programmer's wife says: 'Go to the store and buy a loaf of bread. If they have eggs, buy a dozen.' He came back with 12 loaves.",
    "Why did the Python programmer get kicked out of the forest? Too many indentation errors.",
    "What's a pirate's favourite programming language? R... but his first love is the C.",
    "I changed my password to 'incorrect' so whenever I forget, it tells me: 'Your password is incorrect.'",
    "Debugging: being the detective in a crime movie where you are also the murderer.",
    "Git commit -m 'fixed stuff'. Narrator: it was not fixed.",
    "Two threads walk into a bar. The barkeeper looks up and says: 'Hey, I want don't any trouble.'",
    "Why did the Telegram bot go to therapy? Too many unresolved commands.",
]

ROASTS = [
    "{n} has the energy of a phone at 1%: everyone worries, nobody has a charger.",
    "{n} is proof that 'ctrl+z' doesn't work on life decisions.",
    "{n} treats deadlines like suggestions and suggestions like insults.",
    "{n}'s Wi-Fi password is stronger than their opinions.",
    "{n} brings a whole new meaning to 'loading...' in real life.",
    "{n} is the human version of 'Are you sure you want to exit?'",
    "{n} could get lost in a one-room apartment, with GPS, and a guide.",
    "{n} replies 'on my way' from the sofa with unmatched confidence.",
    "{n} is the reason the 'mute' button was invented, and we thank them for it.",
    "{n}'s sense of direction is a lot like their Wi-Fi: it drops whenever it matters.",
    "{n} has 3 GB of photos and 0 of them in focus.",
    "{n} would lose a staring contest with a loading bar.",
]

TRUTHS = [
    "What is the most embarrassing thing in your search history (the PG version)?",
    "What is a habit you have that you'd never admit in public?",
    "Who in this chat would you trust to plan your birthday party?",
    "What is the silliest fear you have?",
    "What is the last lie you told, and was it worth it?",
    "What's the worst gift you ever received?",
    "Which app do you waste the most time on?",
    "What's your most useless talent?",
    "If you could swap lives with someone here for a day, who would it be?",
    "What is the strangest food combination you secretly love?",
    "What was your worst haircut or style choice ever?",
    "What's a song you love but pretend not to?",
    "What is something you pretended to understand but still don't?",
    "When did you last cry laughing, and why?",
]

DARES = [
    "Send a voice message singing the first line of any song.",
    "Change your profile picture to a potato for 10 minutes.",
    "Write a two-line poem about the last thing you ate.",
    "Send the 7th photo in your gallery (if it's safe to share).",
    "Talk in rhymes for the next 5 messages.",
    "Set your status to 'I lost a bet' for 15 minutes.",
    "Send a selfie making your silliest face.",
    "Describe your day using only emojis.",
    "Type your next three messages with your eyes closed.",
    "Tell the group one genuine compliment for each person who replies.",
    "Imitate an animal in a voice message.",
    "Invent a new word and use it in a sentence.",
]


def ship_percent(a: str, b: str) -> int:
    """Deterministic and symmetric: ship(a, b) == ship(b, a)."""
    names = sorted([a.strip().lower(), b.strip().lower()])
    digest = hashlib.sha256("|".join(names).encode("utf-8")).digest()
    return int.from_bytes(digest[:2], "big") % 101


def ship_verdict(percent: int) -> str:
    if percent >= 90:
        return "Soulmates. Start planning the wedding."
    if percent >= 70:
        return "Great chemistry!"
    if percent >= 50:
        return "Decent odds. Needs a little effort."
    if percent >= 30:
        return "Hmm... friends first?"
    return "Opposites repel. Maybe next lifetime."


async def _display_name(ctx: CommandContext, user_id: Optional[int]) -> str:
    if not user_id:
        return "Someone"
    try:
        entity = await ctx.client.get_entity(user_id)
        name = " ".join(p for p in (getattr(entity, "first_name", ""), getattr(entity, "last_name", "")) if p)
        return name or getattr(entity, "title", "") or getattr(entity, "username", "") or str(user_id)
    except Exception:  # noqa: BLE001
        return str(user_id)


@router.register(name="quote", category=CATEGORY, description="Show a random quote.", usage=".quote")
async def quote_cmd(ctx: CommandContext):
    text, author = random.choice(QUOTES)
    return await ctx.reply(ascii.frame("Quote", [f'"{text}"', "", f"- {author}"]))


@router.register(name="joke", category=CATEGORY, description="Tell a random joke.", usage=".joke")
async def joke_cmd(ctx: CommandContext):
    return await ctx.reply(ascii.frame("Joke", [random.choice(JOKES)]))


@router.register(
    name="roast", category=CATEGORY, owner_only=True,
    description="Playfully roast someone (reply, id, or a name).", usage=".roast (reply | id | name)",
)
async def roast_cmd(ctx: CommandContext):
    name = None
    target = await ctx.get_target_user_id()
    if target:
        name = await _display_name(ctx, target)
    elif ctx.args_text.strip():
        name = ctx.args_text.strip()[:40]
    if not name:
        return await ctx.reply_usage("Reply to someone or write a name.")
    return await ctx.reply(ascii.frame("Roast", [random.choice(ROASTS).format(n=name), "", "(all in good fun)"]))


@router.register(
    name="ship", category=CATEGORY,
    description="Chance of a relationship between two people.", usage=".ship <name1> <name2>  or reply + <name>",
)
async def ship_cmd(ctx: CommandContext):
    names: List[str] = []
    target = await ctx.get_target_user_id()
    if target:
        names.append(await _display_name(ctx, target))
        # `.ship 123456` uses the id as the target; extra words are the second name.
        extra = [a for a in ctx.args if not a.lstrip("-").isdigit()]
        if extra:
            names.append(" ".join(extra)[:30])
        elif getattr(ctx, "sender_id", None):
            names.append(await _display_name(ctx, ctx.sender_id))
    else:
        names = [a[:30] for a in ctx.args[:2]]
    if len(names) < 2:
        return await ctx.reply_usage("Example: .ship Ali Sara")
    percent = ship_percent(names[0], names[1])
    return await ctx.reply(ascii.frame("Ship", [
        f"{names[0]}  x  {names[1]}", "", f"{ascii.bar(percent)} {percent}%", ship_verdict(percent)]))


@router.register(name="truth", category=CATEGORY, description="A random truth question.", usage=".truth")
async def truth_cmd(ctx: CommandContext):
    return await ctx.reply(ascii.frame("Truth", [random.choice(TRUTHS)]))


@router.register(name="dare", category=CATEGORY, description="A random dare.", usage=".dare")
async def dare_cmd(ctx: CommandContext):
    return await ctx.reply(ascii.frame("Dare", [random.choice(DARES)]))


@router.register(
    name="tictactoe", category=CATEGORY, cooldown=3,
    description="Play tic-tac-toe: reply to a member to challenge them, or play against Reze.",
    usage=".tictactoe [stop]  (reply to challenge someone)",
)
async def tictactoe_cmd(ctx: CommandContext):
    if ctx.args and ctx.args[0].lower() in ("stop", "end", "cancel"):
        stopped = tictactoe_manager.stop(ctx.chat_id)
        return await ctx.reply(ascii.success("Game stopped", ["The board was cleared."]) if stopped
                               else ascii.warning("No game", ["There is no running game in this chat."]))

    me_id = ctx.sender_id
    me_name = await _display_name(ctx, me_id)
    opponent = None
    reply = await ctx.get_reply_message()
    if reply is not None and getattr(reply, "sender_id", None) not in (None, me_id):
        opponent = reply.sender_id
    try:
        game = tictactoe_manager.start(
            ctx.chat_id, me_id, me_name, opponent,
            await _display_name(ctx, opponent) if opponent else "Reze",
        )
    except ValueError as exc:
        return await ctx.reply(ascii.warning("Busy", [str(exc)]))
    game.message = await ctx.reply(game.view())
    return None
