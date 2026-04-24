# Telegram Bridge Record - 2026-04-21

## Summary

This note records the Telegram Userbot bridge implementation and the currently used runtime settings for `chat-oracle`.

Current command:

- `#查询 xxx`

Current result strategy:

- short-circuit normal model chat
- send only `xxx` to Telegram target bot
- return Telegram result directly
- if TXT is small enough, return inline text
- if TXT is large, return:
  - first-page content
  - TXT download link

## Technical Path

### Command ingress

- User enters `#查询 xxx`
- [chat_service.py](L:/project/chat-oracle/app/services/chat_service.py:1)
  - identifies internal command
  - routes to Telegram bridge
- [telegram_bridge_service.py](L:/project/chat-oracle/app/services/telegram_bridge_service.py:1)
  - strips `#查询`
  - forwards raw query text

### Telegram bridge runtime

- [telegram_userbot_manager.py](L:/project/chat-oracle/app/services/telegram_userbot_manager.py:1)
  - starts Telethon with configured session
  - ensures target bot and required peers are prepared
  - sends query
  - collects:
    - first response
    - follow-up responses
    - edited messages
    - button click return values
  - after export trigger, actively polls:
    - source message latest state
    - recent bot dialog messages

### TXT path

- direct TXT file: download bytes from Telegram
- TXT URL: fetch via HTTP
- large TXT:
  - store in Redis
  - expose temporary platform download link
  - return first page + link

### Download route

- [telegram.py](L:/project/chat-oracle/app/api/v1/telegram.py:1)
- [telegram_download_service.py](L:/project/chat-oracle/app/services/telegram_download_service.py:1)

Route shape:

```text
/v1/telegram/downloads/{download_id}?token={token}
```

## Current Runtime Values

### Server

- Host: `ubuntu@40.233.67.228`
- App dir: `/home/ubuntu/chat-oracle`
- Public URL: `https://chat.202574.xyz`
- Internal URL: `http://127.0.0.1:18000`

### Telegram bridge config currently in use

- `TELEGRAM_BRIDGE_API_ID=2040`
- `TELEGRAM_BRIDGE_API_HASH=b18441a1ff607e10a989891a5462e627`
- `TELEGRAM_BRIDGE_TARGET_BOT_USERNAME=@mfsgk`
- `TELEGRAM_BRIDGE_REQUIRED_PEERS=@KaliCD,@KaliSGK`
- `TELEGRAM_BRIDGE_BOOTSTRAP_START_MESSAGE=/start`
- `TELEGRAM_BRIDGE_REQUEST_TIMEOUT_SECONDS=180`
- `TELEGRAM_BRIDGE_INLINE_TEXT_MAX_CHARS=12000`
- `TELEGRAM_BRIDGE_DOWNLOAD_TTL_SECONDS=86400`

### Session string currently in use

`TELEGRAM_BRIDGE_SESSION_STRING`

```text
1BVtsOGsBu0OLdkJRHmtRidUY-KFwyFa0Yoet4JfuZYHqcGqwzW8VAYxU0IPQp6VDKc2rzMcUU2OY96PDROl8QgvyCTWv67Od9t_7KQw3gWYEwOiHv4TmQ3B8kGUSB2419dMvKeM4IRcQfPJl2D7PXNVjgP1pixRdO8uXUiFLgcD4Lt5OuhexmpOeMasYPaeDl6TiBf635f6u-r766EnPnSa33V-4smnZG8H3bYtfA8TMwKnemNt_BKL_vj7dCakl5J2gvg81KyANfFi3aW8W4VQ2pDzr4Gno5fsl76JjlVf83KxkL1RnpEUS0bDWsuwlwL-c5HS6IFQdofreFBNiAzD-z1CZtU8=
```

## Deployment Commands Used

Typical file sync:

```powershell
scp -i L:\project\chat-oracle\k_ssh.key -o StrictHostKeyChecking=no <local-file> ubuntu@40.233.67.228:/home/ubuntu/chat-oracle/<remote-path>
```

Typical app rebuild:

```powershell
ssh -i L:\project\chat-oracle\k_ssh.key -o StrictHostKeyChecking=no ubuntu@40.233.67.228 "cd /home/ubuntu/chat-oracle && docker compose -f deploy/compose/docker-compose.yml up -d --build app"
```

## Observed Bot Behavior

Observed from stored message metadata:

- bridge initially captured page `1 / 40`
- result message carried buttons:
  - `下一页`
  - `🆓 导出TXT`
  - `📢 官方频道`
- early failures happened because TXT export completion was not always emitted as a simple new message

Current bridge logic now tries:

- message replies
- message edits
- button click return values
- recent bot message polling
- source message refresh polling

## Output Policy

Current output policy is:

- if no TXT export is available: return Telegram text result
- if TXT is available and small: return TXT full text
- if TXT is available and large: return:
  - first-page Telegram content
  - platform TXT download link

## Filename Policy

Downloaded TXT file names now use timestamp format:

```text
telegram-export-YYYYMMDD-HHMMSS.txt
```

## Risk Note

- The session string written in this note is sensitive and grants Telegram session access.
- The current API ID / API hash pair is not a private self-owned credential pair.
- If the bot changes export behavior again, the polling logic may need another targeted adjustment.
