# Security policy

Reze runs as **your own Telegram account**, so a leaked session string or `.env`
means a leaked account. The full hardening guide is in
[docs/SECURITY.md](docs/SECURITY.md).

## Reporting a vulnerability

Please **do not open a public issue** for security problems.

- Use GitHub's private reporting: **Security -> Report a vulnerability** on this repository, or
- message the maintainer on Telegram: [@yamods](https://t.me/yamods).

Include what you found, how to reproduce it and the affected version. You will get
an answer as soon as possible; please allow a reasonable time for a fix before
disclosing details publicly.

## Supported versions

Only the latest release receives security fixes.

## Safe-use checklist

- Keep `.env`, `*.session` and `data/` out of git (the repository `.gitignore` does this).
- Bind the web panel to `127.0.0.1` unless it sits behind HTTPS (see [DEPLOY.md](DEPLOY.md)).
- Set a panel password hash, not a plain password, in production.
- Only install plugins you have read: plugins run with the same privileges as Reze.
