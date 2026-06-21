# ctfd-stack

[🇷🇺 Русская версия](README_RU.md)

Production-ready CTFd deployment with curated plugins and themes. Clone, configure, run.

Built on [CTFd 3.8.5](https://github.com/CTFd/CTFd).

## Included

### Plugins
| Plugin | Description | Author |
|---|---|---|
| [ctfd-ldap-plugin](https://github.com/defojeco/ctfd-ldap-plugin) | Active Directory authentication with AES-256 cache and team auto-assignment | defojeco |
| [ctfd-dynamic-flag](https://github.com/defojeco/ctfd-dynamic-flag) | Per-user/per-team computed flags (anti-sharing) via whitelisted hashing schemes | defojeco |
| [ctfd-dynamic-values](https://github.com/defojeco/ctfd-dynamic-values) | Per-participant dynamic variables (unique IP/port/token) embedded in challenge text | defojeco |
| [ctfd-plugin-multichoice](https://github.com/defojeco/ctfd-plugin-multichoice) | Multiple choice challenge type with shuffle and partial scoring | defojeco |
| [ctfd-user-control-plugin](https://github.com/defojeco/ctfd-user-control-plugin) | Profile lock, attempt limiting, and audit log | defojeco |
| [chat-notifier](https://github.com/krzys-h/CTFd_chat_notifier) | Discord / Slack / Telegram notifications | krzys-h |

### Themes
| Theme | Description | Author |
|---|---|---|
| [wmctf2025](https://github.com/wm-team/ctfd-wmctf2025-theme) | Clean modern theme with 3D scoreboard | wm-team |
| [pixo](https://github.com/jagdishtripathy/pixo) | Retro CRT-style theme | jagdishtripathy |
| [neon](https://github.com/chainflag/ctfd-neon-theme) | Dark neon glow theme | chainflag |

## Deployment options

### Full stack (recommended)
Includes all plugins and themes. Ready to run out of the box.

```bash
git clone https://github.com/defojeco/ctfd-stack.git
cd ctfd-stack

cp .env.example .env
# Edit .env and set your passwords and secret key

docker compose up -d
```

Open `http://localhost` and complete the CTFd setup wizard.

### Minimal
Clean CTFd with no plugins and no extra themes. Use this if you want
to pick your own plugins or just need a vanilla CTFd in production.

```bash
git clone https://github.com/defojeco/ctfd-stack.git
cd ctfd-stack

cp .env.example .env
docker compose -f docker-compose.minimal.yml up -d
```

No Dockerfile build needed — pulls the official `ctfd/ctfd:3.8.5` image directly.

> **Note:** The LDAP plugin requires additional dependencies (ldap3, cryptography).
> If you plan to use it, use the full stack — it builds the image with the required packages automatically.

## Configuration

Copy `.env.example` to `.env` and fill in the values:

```env
DB_ROOT_PASSWORD=your_root_password
DB_PASSWORD=your_db_password
DB_USER=ctfd
DB_NAME=ctfd
SECRET_KEY=your_secret_key_here
```

Generate a secret key:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## SSL / HTTPS

SSL is not enabled by default. To enable it:

1. Place your certificates in `./ssl/`:
   - `./ssl/cert.pem`
   - `./ssl/key.pem`

2. Uncomment the HTTPS server block in `nginx.conf`

3. Uncomment the SSL-related lines in `docker-compose.yml`

4. Restart:
```bash
docker compose down && docker compose up -d
```

## Stack

| Component | Version |
|---|---|
| CTFd | 3.8.5 |
| MariaDB | 10.6 |
| Redis | 7 |
| Nginx | alpine |

## Credits

- [CTFd](https://github.com/CTFd/CTFd) — the platform
- [wmctf2025 theme](https://github.com/wm-team/ctfd-wmctf2025-theme) — wm-team
- [pixo theme](https://github.com/jagdishtripathy/pixo) — jagdishtripathy
- [neon theme](https://github.com/chainflag/ctfd-neon-theme) — chainflag
- [chat-notifier](https://github.com/krzys-h/CTFd_chat_notifier) — krzys-h

## License

MIT — see [LICENSE](LICENSE)
