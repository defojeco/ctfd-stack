# ctfd-stack

[🇬🇧 English version](README.md)

Готовый к продакшену деплой CTFd с проверенными плагинами и темами. Клонируй, настрой, запусти.

Основан на [CTFd 3.8.5](https://github.com/CTFd/CTFd).

## Что включено

### Плагины
| Плагин | Описание | Автор |
|---|---|---|
| [ctfd-ldap-plugin](https://github.com/defojeco/ctfd-ldap-plugin) | Аутентификация через Active Directory с кэшем AES-256 и автоназначением команд | defojeco |
| [ctfd-dynamic-flag](https://github.com/defojeco/ctfd-dynamic-flag) | Персональные/командные вычисляемые флаги (защита от шаринга) через разрешённые схемы хеширования | defojeco |
| [ctfd-dynamic-values](https://github.com/defojeco/ctfd-dynamic-values) | Динамические переменные для каждого участника (уникальный IP/порт/токен) встроенные в текст задания | defojeco |
| [ctfd-plugin-multichoice](https://github.com/defojeco/ctfd-plugin-multichoice) | Задания с выбором ответа — одиночный/множественный выбор, перемешивание, частичный зачёт | defojeco |
| [ctfd-user-control-plugin](https://github.com/defojeco/ctfd-user-control-plugin) | Блокировка профиля, лимит попыток, журнал аудита | defojeco |
| [chat-notifier](https://github.com/krzys-h/CTFd_chat_notifier) | Уведомления в Discord / Slack / Telegram | krzys-h |

### Темы
| Тема | Описание | Автор |
|---|---|---|
| [wmctf2025](https://github.com/wm-team/ctfd-wmctf2025-theme) | Современная тема с 3D таблицей лидеров | wm-team |
| [pixo](https://github.com/jagdishtripathy/pixo) | Ретро тема в стиле CRT | jagdishtripathy |
| [neon](https://github.com/chainflag/ctfd-neon-theme) | Тёмная неоновая тема | chainflag |

## Варианты запуска

### Полный стек (рекомендуется)
Включает все плагины и темы. Готово к работе сразу после настройки.

```bash
git clone https://github.com/defojeco/ctfd-stack.git
cd ctfd-stack

cp .env.example .env
# Заполни .env своими паролями и секретным ключом

docker compose up -d
```

Открой `http://localhost` и пройди мастер настройки CTFd.

### Минимальный
Чистый CTFd без плагинов и дополнительных тем. Используй если хочешь сам выбрать плагины или просто нужен ванильный CTFd в продакшене.

```bash
git clone https://github.com/defojeco/ctfd-stack.git
cd ctfd-stack

cp .env.example .env
docker compose -f docker-compose.minimal.yml up -d
```

Сборка Dockerfile не нужна — используется официальный образ `ctfd/ctfd:3.8.5` напрямую.

> **Важно:** LDAP плагин требует дополнительных зависимостей (ldap3, cryptography).
> Если планируешь его использовать — запускай полный стек, он автоматически собирает образ с нужными пакетами.

## Настройка

Скопируй `.env.example` в `.env` и заполни значения:

```env
DB_ROOT_PASSWORD=твой_root_пароль
DB_PASSWORD=твой_пароль_бд
DB_USER=ctfd
DB_NAME=ctfd
SECRET_KEY=твой_секретный_ключ
```

Сгенерировать секретный ключ:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## SSL / HTTPS

SSL отключён по умолчанию. Чтобы включить:

1. Положи сертификаты в `./ssl/`:
   - `./ssl/cert.pem`
   - `./ssl/key.pem`

2. Раскомментируй HTTPS блок в `nginx.conf`

3. Раскомментируй SSL строки в `docker-compose.yml`

4. Перезапусти:
```bash
docker compose down && docker compose up -d
```

## Стек

| Компонент | Версия |
|---|---|
| CTFd | 3.8.5 |
| MariaDB | 10.6 |
| Redis | 7 |
| Nginx | alpine |

## Благодарности

- [CTFd](https://github.com/CTFd/CTFd) — платформа
- [wmctf2025 theme](https://github.com/wm-team/ctfd-wmctf2025-theme) — wm-team
- [pixo theme](https://github.com/jagdishtripathy/pixo) — jagdishtripathy
- [neon theme](https://github.com/chainflag/ctfd-neon-theme) — chainflag
- [chat-notifier](https://github.com/krzys-h/CTFd_chat_notifier) — krzys-h

## Лицензия

MIT — см. [LICENSE](LICENSE)
