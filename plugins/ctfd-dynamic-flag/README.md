# ctfd-dynamic-flag — per-user computed flags for CTFd (`dynamic_formula` type)

[🇷🇺 Русская версия](README.ru.md)

A CTFd flag plugin that computes a **unique flag per user / per team** from a
small set of whitelisted hashing schemes. This is the standard anti-sharing /
per-user-flag pattern.

> **Design note (why no `exec`):** an earlier spec for this plugin asked to run
> admin-supplied Python via `exec()` with an "empty `__builtins__`" sandbox and
> a `threading.Timer` timeout. That design is **not safe** and is intentionally
> not used here:
> - An empty `__builtins__` is trivially escaped via object introspection
>   (e.g. `().__class__.__bases__[0].__subclasses__()`), reaching `os` /
>   `subprocess` and full RCE (CWE-95).
> - `threading.Timer` **cannot** interrupt running Python bytecode, so a
>   `while True: pass` or catastrophic regex hangs the worker — a DoS, not a 2s cap.
>
> Instead, the admin chooses a **scheme** and parameters; the plugin runs only
> its own statically-defined code. This covers per-user flags without ever
> executing untrusted input. If you genuinely need arbitrary code execution as a
> challenge, run it in an isolated process/container with cgroup limits and a
> `SIGKILL` timeout — never `exec()` inside the CTFd worker.

## Installation

1. Place this directory in `CTFd/plugins/` as `ctfd-dynamic-flag`:

   ```
   CTFd/plugins/ctfd-dynamic-flag/
   ├── __init__.py
   ├── README.md
   └── assets/
       ├── create.html
       └── edit.html
   ```

   (The plugin directory **must** be named `ctfd-dynamic-flag` so the asset URLs
   `/plugins/ctfd-dynamic-flag/assets/...` resolve. In the Docker stack, mount it
   with that name, e.g.
   `./plugins/ctfd-dynamic-flag:/opt/CTFd/CTFd/plugins/ctfd-dynamic-flag:ro`.)

   Note: the directory name changed, but the **flag type name stays
   `dynamic_formula`** (`FLAG_CLASSES["dynamic_formula"]`) so existing flags keep
   working.

   The admin form is a set of normal fields (scheme / secret / source / format /
   length); a small inline script packs them into the hidden `name="content"`
   field as JSON, which is exactly what CTFd persists and what `compare()` reads
   back. CTFd renders these templates client-side with **nunjucks** (not Jinja),
   so they avoid Jinja-only filters like `tojson`.

2. Restart CTFd. On boot, `load(app)` registers the flag type in
   `FLAG_CLASSES["dynamic_formula"]` and mounts the assets blueprint.

3. When creating a challenge, choose flag type **dynamic_formula** and fill in
   the form fields (scheme, secret, source template, output format, length).

## How it works

The stored flag value is a JSON config:

```json
{
  "scheme": "hmac-sha256",
  "secret": "S3CR3T",
  "source": "{team_name}",
  "format": "FLAG{%s}",
  "length": 32
}
```

On each submission, `DynamicFormulaFlag.compare()`:

1. Resolves the current submitter via `get_current_user()` /
   `get_current_team()`.
2. Substitutes placeholders in `source`:
   `{user_name} {user_email} {user_id} {team_name} {team_id}`
   (literal `str.replace`, so braces in names cannot trigger format-string
   injection).
3. Computes the digest using the selected **whitelisted** scheme only.
4. Wraps it with `format` (`%s` → digest) and truncates to `length`.
5. Compares against the submission with `hmac.compare_digest()` (constant-time).

Any malformed config or error logs a warning and rejects the flag — it never
crashes submission.

## Schemes

| Scheme        | Computation                                       |
|---------------|---------------------------------------------------|
| `sha256`      | `sha256(secret_bytes + source_bytes).hexdigest()` |
| `hmac-sha256` | `hmac(key=secret, msg=source, sha256).hexdigest()`|
| `base64`      | `base64(secret_bytes + source_bytes)`             |

## Examples

These three configurations reproduce the originally requested use cases —
without any admin-supplied code.

### 1. SHA-256 over the username

```json
{
  "scheme": "sha256",
  "secret": "SECRET_",
  "source": "{user_name}",
  "format": "FLAG{%s}",
  "length": 32
}
```

Equivalent computation: `FLAG{ sha256("SECRET_" + user_name)[:32] }`.

> Tip: if you want the old `.strip().lower().replace(" ","_")` normalization,
> pre-normalize how usernames are allowed at registration, or pick a `source`
> that doesn't depend on whitespace. The plugin keeps `source` verbatim so the
> result is predictable and auditable.

### 2. HMAC-SHA256 over the team name

```json
{
  "scheme": "hmac-sha256",
  "secret": "team-signing-key",
  "source": "{team_name}",
  "format": "FLAG{%s}",
  "length": 40
}
```

Equivalent computation:
`FLAG{ hmac_sha256(key="team-signing-key", msg=team_name)[:40] }`.

### 3. Base64 of user_id + challenge_id

`{challenge_id}` is now a first-class placeholder:

```json
{
  "scheme": "base64",
  "source": "{challenge_id}:{user_id}",
  "format": "FLAG{%s}",
  "length": 0
}
```

Computation: `FLAG{ base64(challenge_id + ":" + user_id) }`.

## Integration with ctfd-dynamic-values

If the **ctfd-dynamic-values** plugin is also installed, `source` and `secret`
may reference its `{{variable}}` tokens. They are resolved first (per the current
participant + scope), then the `{placeholder}` tokens above. Example — derive the
flag from a per-user generated IP:

```json
{
  "scheme": "sha256",
  "secret": "net-key",
  "source": "{{target_ip}}",
  "format": "FLAG{%s}",
  "length": 32
}
```

This integration is optional and loosely coupled (via `app.dynamic_values_substitute`);
if the values plugin is absent, the flag behaves exactly as documented above.

## Compatibility

- CTFd 3.x and 4.x.
- `compare()` reads the config from `chal_key_obj.content`, falling back to
  `.data`, so it works across versions that store the flag value in either field.
