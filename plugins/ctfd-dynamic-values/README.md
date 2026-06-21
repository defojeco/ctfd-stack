# ctfd-dynamic-values — per-participant dynamic variables for CTFd

[🇷🇺 Русская версия](README.ru.md)

Define named variables on a challenge that are **generated deterministically**
from the current participant's identity (user / team) plus an optional salt,
using a token **mask**. Reference them as `{{name}}` in the challenge
description — each participant sees their own value, and it stays the same on
refresh (the value is a pure function of the inputs; nothing random is stored).

Typical uses: a unique target IP or port per user, a per-team subnet, a
per-user token embedded in the task text.

## Installation

Place this directory in `CTFd/plugins/` as `ctfd-dynamic-values`:

```
CTFd/plugins/ctfd-dynamic-values/
├── __init__.py
├── generator.py
├── README.md
└── assets/
    ├── variables.js
    └── variables.css
```

In the Docker stack, mount it with that name:

```yaml
- ./plugins/ctfd-dynamic-values:/opt/CTFd/CTFd/plugins/ctfd-dynamic-values:ro
```

Restart CTFd. On boot the plugin:
- creates its table (`dynamic_values`),
- registers the admin script that adds a **Variables** tab to the challenge
  editor (next to Files / Flags / Topics),
- patches challenge `read()` so `{{name}}` in descriptions is substituted for
  each participant,
- publishes `app.dynamic_values_substitute` for the optional flag integration.

## Using it

1. Open a challenge in the admin, go to the **Variables** tab.
2. Add a variable: a **name** (`target_ip`), a **mask**, a **scope**, and an
   optional **salt**. Use **Preview** to see a sample value.
3. Put `{{target_ip}}` anywhere in the challenge **description**.
4. Each participant now sees their own generated value, stable across refreshes.

### Scope

| Scope     | Value is shared by… |
|-----------|---------------------|
| `user`    | each individual user (default) |
| `team`    | everyone on the same team (falls back to per-user if no team) |
| `global`  | everyone (one value for the whole challenge) |

### Salt

Optional string mixed into the seed. Change it to rotate all generated values
for a variable without changing names or masks. Leave empty if not needed.

## Mask tokens

Everything outside a token is emitted literally. Tokens consume deterministic
entropy left-to-right.

| Token            | Meaning |
|------------------|---------|
| `{A-B}`          | integer in the inclusive range `[A, B]` (decimal) |
| `{N}`            | `N` decimal digits |
| `{xN}` / `{XN}`  | `N` hex chars (lower / upper) |
| `{aN}` / `{AN}`  | `N` letters (lower / upper) |
| `{wN}`           | `N` alphanumeric chars `[a-zA-Z0-9]` |
| `\{` `\}`        | literal braces |

### Examples

| Mask                              | Sample output   |
|-----------------------------------|-----------------|
| `10.{0-255}.{0-255}.{1-254}`      | `10.137.42.200` |
| `{1024-65535}`                    | `49213`         |
| `host-{x8}`                       | `host-3fa9c0b1` |
| `USER-{A6}`                       | `USER-KQWZPL`   |
| `token_{w16}`                     | `token_yK1s0KqHHWq3aB9c` |
| `static-value-123` (no tokens)    | `static-value-123` (always) |

## Determinism

The seed is `sha256("<scope_key>|<salt>|<challenge_id>|<name>")`, expanded into
an unbounded byte stream for the mask. Ranges use unbiased rejection sampling.
Same inputs → same output, always. This is why values survive a page refresh and
why two different users (almost always) get different values, while a `team`-
scoped variable is identical for all members of a team.

## Integration with ctfd-dynamic-flag

If **ctfd-dynamic-flag** is installed, its `dynamic_formula` flags can reference
these variables in `source`/`secret` via the same `{{name}}` syntax — so a flag
can be derived from the same per-user value shown in the task text. The
integration is loosely coupled through `app.dynamic_values_substitute`; neither
plugin imports the other, and each works standalone.

## REST API (admin only)

| Method | Path | Purpose |
|--------|------|---------|
| GET    | `/api/v1/plugins/dynamic_values?challenge_id=<id>` | list variables |
| POST   | `/api/v1/plugins/dynamic_values` | create |
| PATCH  | `/api/v1/plugins/dynamic_values/<id>` | update |
| DELETE | `/api/v1/plugins/dynamic_values/<id>` | delete |
| GET    | `/api/v1/plugins/dynamic_values/preview?mask=…&salt=…&scope=…&name=…` | preview a mask |

All endpoints require an admin session (`@admins_only`).

## Security notes

- No code execution: masks are parsed by a fixed tokenizer, never `eval`/`exec`.
- Generated values are not secrets by themselves; if you derive a flag from a
  variable, the secrecy comes from the flag's salt/secret, not the variable.
- Write endpoints are admin-only; the preview uses the requesting admin's own
  identity as the sample.

## Compatibility

CTFd 3.x and 4.x.
