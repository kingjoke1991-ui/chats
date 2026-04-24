from __future__ import annotations

import getpass
import os

from telethon.sync import TelegramClient
from telethon.sessions import StringSession


def read_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    return input(f"{name}: ").strip()


def main() -> None:
    api_id_text = read_required_env("TELEGRAM_BRIDGE_API_ID")
    api_hash = read_required_env("TELEGRAM_BRIDGE_API_HASH")
    phone = os.getenv("TELEGRAM_PHONE", "").strip() or input("TELEGRAM_PHONE: ").strip()
    target_bot = os.getenv("TELEGRAM_BRIDGE_TARGET_BOT_USERNAME", "").strip() or input(
        "TELEGRAM_BRIDGE_TARGET_BOT_USERNAME (optional): "
    ).strip()
    required_peers = os.getenv("TELEGRAM_BRIDGE_REQUIRED_PEERS", "").strip() or input(
        "TELEGRAM_BRIDGE_REQUIRED_PEERS comma-separated (optional): "
    ).strip()

    if not api_id_text or not api_hash or not phone:
        raise SystemExit("TELEGRAM_BRIDGE_API_ID, TELEGRAM_BRIDGE_API_HASH, TELEGRAM_PHONE are required.")

    api_id = int(api_id_text)

    with TelegramClient(StringSession(), api_id, api_hash) as client:
        client.send_code_request(phone)
        code = getpass.getpass("Telegram login code: ").strip()
        try:
            client.sign_in(phone=phone, code=code)
        except Exception as exc:
            if exc.__class__.__name__ == "SessionPasswordNeededError":
                password = getpass.getpass("Telegram 2FA password: ").strip()
                client.sign_in(password=password)
            else:
                raise

        session_string = client.session.save()

    print("\n" + "=" * 60)
    print("TELEGRAM_BRIDGE_SESSION_STRING")
    print("=" * 60)
    print(session_string)
    print("=" * 60)
    print("\n可直接写入服务器 .env 的片段：")
    print("-" * 60)
    print(f"TELEGRAM_BRIDGE_API_ID={api_id}")
    print(f"TELEGRAM_BRIDGE_API_HASH={api_hash}")
    print(f"TELEGRAM_BRIDGE_SESSION_STRING={session_string}")
    if target_bot:
        print(f"TELEGRAM_BRIDGE_TARGET_BOT_USERNAME={target_bot}")
    if required_peers:
        print(f"TELEGRAM_BRIDGE_REQUIRED_PEERS={required_peers}")
    print("-" * 60)
    print("\n保存后请写入服务端环境变量，不要提交到代码仓库。")


if __name__ == "__main__":
    main()
