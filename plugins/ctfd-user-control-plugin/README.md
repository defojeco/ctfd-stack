# CTFd User Control Plugin

Admin control over participant behavior in CTFd — lock profile fields, limit submission attempts, and audit everything.

Designed for academic and corporate CTF deployments where you need to prevent cheating and track participant actions.

## Features

| Feature | Description |
|---|---|
| Block username change | Prevent participants from renaming themselves mid-competition |
| Block email change | Lock the email field |
| Block password change | Prevent password changes during the event |
| Attempt limiting | Cap failed submissions per challenge within a time window |
| Whitelist | Exempt specific users from all restrictions |
| Superadmin bypass | User ID=1 is always exempt |
| Audit log | Every blocked action is recorded with timestamp and IP |
| Log viewer | Browse the audit log directly in the admin panel |

## Requirements

- CTFd 3.7.x
- Python 3.8+

No extra pip packages required.

## Installation

```bash
# 1. Copy the plugin folder into CTFd
cp -r ctfd_user_control_plugin /opt/ctfd/CTFd/plugins/

# 2. Restart CTFd — the audit log table is created automatically
docker restart ctfd
```

## Configuration

Go to **Admin → User Control** (`/admin/user-control`).

| Setting | Default | Description |
|---|---|---|
| Plugin enabled | `false` | Master switch — all restrictions are inactive when off |
| Block username change | `false` | Prevent `PATCH /api/v1/users/me` name field |
| Block email change | `false` | Prevent `PATCH /api/v1/users/me` email field |
| Block password change | `false` | Prevent `PATCH /api/v1/users/me` password field |
| Limit attempts | `false` | Enable per-challenge attempt limiting |
| Max attempts | `10` | Maximum failed submissions per period |
| Period (minutes) | `60` | Rolling time window for attempt counting |
| Audit log | `true` | Record all blocked actions |

## Whitelist

Add usernames as a JSON array to exempt specific users from all restrictions:

```json
["admin", "moderator", "test_user"]
```

User ID=1 (superadmin) is always exempt regardless of whitelist settings.

## Attempt Limiting

When enabled, participants who exceed `max_attempts` failed submissions for a single challenge within the `period` window receive a `429` response with a clear error message.

Counts only **failed** attempts (`Fails` table). Successful solves do not count.

## Audit Log

Every blocked action is stored in the `user_audit_log` table:

| Column | Description |
|---|---|
| `user_id` | CTFd user ID |
| `action` | Action type (`username_change_blocked`, `attempt_limit_exceeded`, etc.) |
| `target` | Target resource (username, challenge ID) |
| `ip_address` | Remote IP |
| `timestamp` | UTC timestamp |
| `blocked` | Whether the action was blocked |

View logs at **Admin → User Control → Logs**.

## LDAP Integration

Works seamlessly alongside [ctfd-ldap-plugin](https://github.com/defojeco/ctfd-ldap-plugin). LDAP users are subject to the same restrictions as local users. Add them to the whitelist by their CTFd display name if needed.

## Compatibility

- CTFd 3.7.x
- Works alongside [ctfd-ldap-plugin](https://github.com/defojeco/ctfd-ldap-plugin) and [ctfd-plugin-multichoice](https://github.com/defojeco/ctfd-plugin-multichoice)

## License

MIT
