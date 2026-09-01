import asyncio
import json
import re
from pathlib import Path

from telethon import TelegramClient
from telethon.tl import functions


CREDENTIALS_FILE = Path(
    "/telegram-preview/credentials.json"
)

SESSION_PATH = (
    "/telegram-preview/telegram-preview"
)


def _load_credentials():

    data = json.loads(
        CREDENTIALS_FILE.read_text(
            encoding="utf-8"
        )
    )

    return (
        data["api_id"],
        data["api_hash"],
    )


def _is_generic_immowelt_preview(
    url,
    site_name,
    title,
    description,
):

    source = " ".join(
        str(value or "")
        for value in (
            url,
            site_name,
        )
    ).casefold()

    if "immowelt" not in source:
        return False

    if description:
        return False

    title = str(
        title or ""
    ).strip()

    if not title:
        return True

    return bool(
        re.search(
            r"\d"
            r"[\d.\s\u00a0]*"
            r"(?:,\d+)?"
            r"\s*€"
            r"\s+zum\s+"
            r"(?:kauf|miete)\b",
            title,
            re.I,
        )
    )


async def _get_preview_async(url):

    api_id, api_hash = (
        _load_credentials()
    )

    client = TelegramClient(
        SESSION_PATH,
        api_id,
        api_hash,
    )

    await client.connect()

    try:

        if not await client.is_user_authorized():

            raise RuntimeError(
                "Telegram-Session "
                "ist nicht autorisiert"
            )

        # Telegram liefert bei einem bisher nicht gecachten
        # Link manchmal zunächst nur einen Pending-/leeren
        # Webpage-Preview.
        #
        # Immowelt liefert zusätzlich gelegentlich zuerst
        # einen technischen Zwischenstand wie:
        #
        #   Haus 150 m² 87900 € zum Kauf Ort (...)
        #
        # Dieser kann sich kurz darauf noch zu einem
        # aussagekräftigen Titel wie
        # "... Zwangsversteigerungen ..." ändern.
        # Deshalb bei einem solchen Immowelt-Zwischenstand
        # NICHT sofort abbrechen, sondern die vorhandenen
        # Folgeversuche ausschöpfen.

        last_preview = None

        for attempt in range(1, 5):

            result = await client(
                functions.messages
                .GetWebPagePreviewRequest(
                    message=url
                )
            )

            media = getattr(
                result,
                "media",
                None
            )

            webpage = getattr(
                media,
                "webpage",
                None
            )

            if webpage is not None:

                site_name = getattr(
                    webpage,
                    "site_name",
                    None
                )

                title = getattr(
                    webpage,
                    "title",
                    None
                )

                description = getattr(
                    webpage,
                    "description",
                    None
                )

                preview_url = getattr(
                    webpage,
                    "url",
                    None
                )

                if title or description:

                    last_preview = {
                        "site_name":
                            site_name,

                        "title":
                            title,

                        "description":
                            description,

                        "url":
                            preview_url,
                    }

                    if not _is_generic_immowelt_preview(
                        url,
                        site_name,
                        title,
                        description,
                    ):
                        return last_preview

                    print(
                        "TELEGRAM PREVIEW: "
                        "generic Immowelt preview | "
                        f"attempt={attempt}/4 | "
                        f"{title!r}",
                        flush=True,
                    )

            if attempt < 4:

                await asyncio.sleep(
                    1.5
                )

        return last_preview

    finally:

        await client.disconnect()


def get_telegram_preview(url):

    return asyncio.run(
        _get_preview_async(
            url
        )
    )
