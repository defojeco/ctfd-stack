# CTFd MultiChoice Plugin

Multiple choice challenge type for CTFd — single and multiple correct answer modes, shuffle, partial scoring, and a clean card-based UI.

No equivalent plugin exists for CTFd. Standard CTFd only supports flag-based challenges.

## Features

| Feature | Description |
|---|---|
| Single choice | Radio button mode — one correct answer |
| Multiple choice | Checkbox mode — several correct answers |
| Answer shuffle | Options shown in random order to prevent cheating |
| Partial scoring | Award points for partially correct answers |
| Partial modes | Percentage-based or fixed points per correct option |
| Multiple questions | One challenge can contain several questions |
| Card UI | Clean card layout instead of plain checkboxes |
| Visual feedback | Green/red highlighting after submission |
| Multilingual | English, Russian, Spanish built-in |

## Requirements

- CTFd 3.7.x
- Python 3.8+

No extra pip packages required.

## Installation

```bash
# 1. Copy the plugin folder into CTFd
cp -r ctfd-plugin-multichoice /opt/ctfd/CTFd/plugins/

# 2. Restart CTFd — the database table is created automatically
docker restart ctfd
```

## Creating a Challenge

1. Go to **Admin → Challenges → New Challenge**
2. Select type **multichoice**
3. Add answer options and mark the correct ones
4. Choose mode: **single** (radio) or **multiple** (checkbox)
5. Optionally enable **shuffle** and **partial scoring**
6. Set `max_attempts` to prevent brute-forcing

## Answer Storage Format

Options are stored in the `flagchoose` field using a custom format:

```
Option A|0§Option B|1§Option C|0§Option D|1
```

- `§` — separator between options
- `|1` — correct option
- `|0` — incorrect option

## Partial Scoring

Two modes are available:

**Percentage-based** — score = `(correct_selected / total_correct) * challenge_points`

**Fixed points per question** — set a point value per correct option; useful when a challenge has multiple questions with different weights.

Partial scoring requires `max_attempts > 0` to be meaningful, otherwise participants can brute-force by selecting all options.

## Compatibility

- CTFd 3.7.x
- Works alongside [ldap-plugin](https://github.com/defojeco/ctfd-ldap-plugin) and [ctfd-user-control-plugin](https://github.com/defojeco/ctfd-user-control-plugin)

## License

MIT
