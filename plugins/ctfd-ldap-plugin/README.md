# CTFd LDAP / Active Directory Plugin

Active Directory authentication for CTFd. Lets participants sign in with their domain credentials while keeping the standard local login as a fallback.

No alternatives exist for CTFd — this plugin fills a gap that the official project has never addressed.

## Features

| Feature | Description |
|---|---|
| Domain login | Authenticate via AD using UPN (`user@domain`) |
| Local login | Standard CTFd accounts work in parallel |
| Login switcher | Domain / Local tabs on the login page |
| Auto-registration | New AD users get a CTFd account on first login |
| Display name sync | CTFd username pulled from AD `displayName` / `cn` |
| Superadmin bypass | User ID=1 can always log in locally, even if local login is disabled |
| AES-256 credential cache | Offline login when AD is unreachable (Fernet) |
| Cache TTL | Configurable (default 72 h) |
| Custom DNS | Resolve internal AD hostnames via a specific DNS server |
| Team auto-assignment | Map AD groups → CTFd teams automatically |
| Category filtering | Show only allowed challenge categories per team |
| Admin panel | `/admin/ldap-settings` — configure everything via UI |
| TCP ping | Check if the LDAP server is reachable |
| Bind test | Verify credentials and preview email + displayName |
| Debug mode | Verbose logging with `[LDAP-PLUGIN]` tag |

## Requirements

- CTFd 3.7.x
- Python 3.8+
- `ldap3 >= 2.9`
- `cryptography >= 41.0` (optional, but required for AES-256 cache)
- `dnspython` (optional, required for custom DNS resolution)

## Installation

```bash
# 1. Copy the plugin folder into CTFd
cp -r ldap_plugin /opt/ctfd/CTFd/plugins/

# 2. Install dependencies
pip install ldap3>=2.9 cryptography>=41.0

# Optional: custom DNS support
pip install dnspython

# 3. Restart CTFd
docker restart ctfd
# or
systemctl restart ctfd
```

## Docker

If you're running CTFd in Docker, add this to your Dockerfile:

```dockerfile
FROM ctfd/ctfd:latest
USER root
RUN pip install "ldap3>=2.9" "cryptography>=41.0"
USER ctfd
```

> Replace `latest` with a specific version tag if needed (e.g. `ctfd/ctfd:3.8.5`)

Without these dependencies the plugin will fail to load silently.

## Configuration

Open **Admin → LDAP Settings** (`/admin/ldap-settings`) and fill in your AD details.

| Setting | Default | Description |
|---|---|---|
| `ldap_enabled` | `true` | Enable domain login |
| `ldap_host` | `winserv.ctfd.loc` | LDAP server hostname or IP |
| `ldap_port` | `389` | Port (`636` for LDAPS) |
| `ldap_use_ssl` | `false` | Use LDAPS |
| `ldap_use_tls` | `false` | Use STARTTLS |
| `ldap_base_dn` | `DC=ctfd,DC=loc` | Base DN for user search |
| `ldap_domain` | `ctfd.loc` | Domain suffix for UPN |
| `ldap_search_filter` | `(sAMAccountName={})` | LDAP search filter |
| `ldap_attr_email` | `mail` | AD attribute for email |
| `ldap_local_enabled` | `true` | Allow local CTFd login |
| `ldap_debug` | `false` | Enable verbose logging |
| `ldap_cache_enabled` | `true` | Cache credentials for offline login |
| `ldap_cache_ttl` | `72` | Cache TTL in hours |
| `ldap_dns_server` | `192.168.1.1` | Custom DNS for resolving AD hostnames |

## Team Auto-Assignment

If CTFd is running in **Teams mode**, the plugin can automatically assign users to teams based on their AD group membership.

1. Go to **Admin → LDAP Settings → Teams**
2. Map AD group CN → CTFd team name (e.g. `ctf-web` → `Web Team`)
3. Enable category filtering if you want each team to see only their challenges

### Category Filtering Logic

1. If a challenge has a `team:X` tag → shown only to team X (overrides category rule)
2. If no `team:*` tags → shown based on category allowlist for the team
3. If filtering is disabled or team is not in the mapping → all challenges visible

## Debug Logs

```bash
# Docker
docker logs <container> 2>&1 | grep "LDAP-PLUGIN"

# systemd
journalctl -u ctfd | grep "LDAP-PLUGIN"
```

## FAQ

**How do I log in if LDAP is not configured yet?**
Use the **Local** tab on the login page with the admin credentials you set during CTFd setup. User ID=1 always has local access.

**User gets 403 on first login?**
CTFd 3.7 can occasionally block login if the plugin intercepts the auth route before the session is fully initialized. Use the **Local** tab as a workaround.

**Email not found in AD?**
Some AD setups store email in `userPrincipalName` or `proxyAddresses` instead of `mail`. Change `ldap_attr_email` in the settings panel.

**LDAP server hostname not resolving?**
Set `ldap_dns_server` to your internal DNS IP. Install `dnspython` to enable custom DNS resolution.

## Compatibility

- CTFd 3.7.x
- Works alongside [ctfd-user-control-plugin](https://github.com/defojeco/ctfd-user-control-plugin)

## License

MIT
