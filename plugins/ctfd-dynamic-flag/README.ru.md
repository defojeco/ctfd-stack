# ctfd-dynamic-flag — персональные вычисляемые флаги для CTFd (тип `dynamic_formula`)

[🇬🇧 English version](README.md)

Плагин флагов для CTFd который вычисляет **уникальный флаг для каждого
пользователя/команды** на основе небольшого набора разрешённых схем хеширования.
Это стандартный паттерн анти-шаринга / персональных флагов.

> **Заметка про дизайн (почему без `exec`):** изначальное ТЗ для этого плагина
> просило выполнять Python-код заданный админом через `exec()` с "пустым
> `__builtins__`" в качестве песочницы и таймаутом через `threading.Timer`.
> Такой дизайн **небезопасен** и намеренно не используется здесь:
> - Пустой `__builtins__` тривиально обходится через интроспекцию объектов
>   (например `().__class__.__bases__[0].__subclasses__()`), что даёт доступ
>   к `os` / `subprocess` и полному RCE (CWE-95).
> - `threading.Timer` **не может** прервать выполняющийся Python байткод,
>   поэтому `while True: pass` или катастрофический regex подвесит воркер —
>   это DoS, а не лимит в 2 секунды.
>
> Вместо этого админ выбирает **схему** и параметры, плагин выполняет только
> свой собственный статически определённый код. Это покрывает кейс персональных
> флагов без выполнения непроверенного ввода. Если тебе реально нужно
> произвольное выполнение кода как задание — запускай его в изолированном
> процессе/контейнере с cgroup-лимитами и `SIGKILL` таймаутом, никогда не
> `exec()` внутри воркера CTFd.

## Установка

1. Положи папку в `CTFd/plugins/` под именем `ctfd-dynamic-flag`:

   ```
   CTFd/plugins/ctfd-dynamic-flag/
   ├── __init__.py
   ├── README.md
   └── assets/
       ├── create.html
       └── edit.html
   ```

   (Папка плагина **обязательно** должна называться `ctfd-dynamic-flag` чтобы
   URL ассетов `/plugins/ctfd-dynamic-flag/assets/...` резолвились. В Docker
   стеке монтируй с этим же именем, например
   `./plugins/ctfd-dynamic-flag:/opt/CTFd/CTFd/plugins/ctfd-dynamic-flag:ro`.)

   Примечание: имя папки изменилось, но **тип флага остаётся
   `dynamic_formula`** (`FLAG_CLASSES["dynamic_formula"]`) так что существующие
   флаги продолжат работать.

   Форма в админке состоит из обычных полей (scheme / secret / source / format /
   length); небольшой инлайн-скрипт упаковывает их в скрытое поле
   `name="content"` как JSON — именно это CTFd сохраняет и что читает
   `compare()`. CTFd рендерит эти шаблоны на клиенте через **nunjucks**
   (не Jinja), поэтому в них избегаются Jinja-специфичные фильтры типа `tojson`.

2. Перезапусти CTFd. При старте `load(app)` регистрирует тип флага в
   `FLAG_CLASSES["dynamic_formula"]` и монтирует blueprint с ассетами.

3. При создании задания выбери тип флага **dynamic_formula** и заполни поля
   формы (scheme, secret, source template, output format, length).

## Как это работает

Сохранённое значение флага — это JSON конфиг:

```json
{
  "scheme": "hmac-sha256",
  "secret": "S3CR3T",
  "source": "{team_name}",
  "format": "FLAG{%s}",
  "length": 32
}
```

При каждой отправке `DynamicFormulaFlag.compare()`:

1. Определяет текущего отправителя через `get_current_user()` /
   `get_current_team()`.
2. Подставляет плейсхолдеры в `source`:
   `{user_name} {user_email} {user_id} {team_name} {team_id}`
   (буквальная замена через `str.replace`, поэтому фигурные скобки в именах
   не могут вызвать format-string injection).
3. Вычисляет дайджест используя выбранную **разрешённую** схему.
4. Оборачивает в `format` (`%s` → дайджест) и обрезает до `length`.
5. Сравнивает с отправленным значением через `hmac.compare_digest()`
   (constant-time).

Любой некорректный конфиг или ошибка логируется как warning и отклоняет
флаг — никогда не падает при отправке.

## Схемы

| Схема         | Вычисление                                        |
|---------------|---------------------------------------------------|
| `sha256`      | `sha256(secret_bytes + source_bytes).hexdigest()` |
| `hmac-sha256` | `hmac(key=secret, msg=source, sha256).hexdigest()`|
| `base64`      | `base64(secret_bytes + source_bytes)`             |

## Примеры

Эти три конфигурации воспроизводят изначально запрошенные кейсы — без
выполнения какого-либо админского кода.

### 1. SHA-256 от имени пользователя

```json
{
  "scheme": "sha256",
  "secret": "SECRET_",
  "source": "{user_name}",
  "format": "FLAG{%s}",
  "length": 32
}
```

Эквивалентное вычисление: `FLAG{ sha256("SECRET_" + user_name)[:32] }`.

> Совет: если нужна старая нормализация `.strip().lower().replace(" ","_")` —
> нормализуй разрешённые имена пользователей при регистрации, либо выбери
> `source` который не зависит от пробелов. Плагин сохраняет `source`
> as-is, поэтому результат предсказуем и проверяем.

### 2. HMAC-SHA256 от имени команды

```json
{
  "scheme": "hmac-sha256",
  "secret": "team-signing-key",
  "source": "{team_name}",
  "format": "FLAG{%s}",
  "length": 40
}
```

Эквивалентное вычисление:
`FLAG{ hmac_sha256(key="team-signing-key", msg=team_name)[:40] }`.

### 3. Base64 от user_id + challenge_id

`{challenge_id}` теперь полноценный плейсхолдер:

```json
{
  "scheme": "base64",
  "source": "{challenge_id}:{user_id}",
  "format": "FLAG{%s}",
  "length": 0
}
```

Вычисление: `FLAG{ base64(challenge_id + ":" + user_id) }`.

## Интеграция с ctfd-dynamic-values

Если установлен плагин **ctfd-dynamic-values**, `source` и `secret` могут
ссылаться на его токены `{{variable}}`. Они резолвятся первыми (для текущего
участника + scope), затем плейсхолдеры `{placeholder}` выше. Пример —
вывести флаг из персонального сгенерированного IP:

```json
{
  "scheme": "sha256",
  "secret": "net-key",
  "source": "{{target_ip}}",
  "format": "FLAG{%s}",
  "length": 32
}
```

Эта интеграция опциональна и слабо связана (через
`app.dynamic_values_substitute`); если плагин values отсутствует, флаг
работает в точности как описано выше.

## Совместимость

- CTFd 3.x и 4.x.
- `compare()` читает конфиг из `chal_key_obj.content`, с fallback на `.data`,
  поэтому работает на версиях которые хранят значение флага в любом из полей.
