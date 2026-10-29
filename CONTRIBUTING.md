# Contributing to Reze

Thanks for helping! Small, focused pull requests are easiest to review.

## Dev setup

```bash
git clone https://github.com/UnchartedAli/Reze.git && cd Reze
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The suite needs no Telegram credentials, network access or AI keys. FFmpeg is only
needed to try video commands by hand.

## Ground rules

- **English only** for user-facing text, and render replies through `reze.ui.ascii`
  (`ascii.success / error / warning / frame ...`) so every command looks the same.
- Telegram calls must match Telethon's real signatures, for example
  `client.send_file(entity, file, ...)`. Test doubles in `tests/support.py` mirror them.
- Add or update tests for behaviour you change. Never put secrets or real chat ids in tests.
- Keep optional integrations optional: fail with an actionable message, not a crash.
- Update `CHANGELOG.md` and `docs/COMMANDS.md` when you add a command.

## Writing a plugin

Drop a file in `reze/plugins/` with a `MANIFEST` and register commands with
`@router.register(...)`. See [docs/PLUGIN_GUIDE.md](docs/PLUGIN_GUIDE.md) or run
`.plugintemplate` inside Telegram.

## Pull request checklist

- [ ] `python -m unittest discover -s tests` passes
- [ ] New commands are documented
- [ ] No secrets, session files or database files are included
