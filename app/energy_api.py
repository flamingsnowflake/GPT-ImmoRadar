import json
import os
import sqlite3
import urllib.parse
import urllib.request
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)

from energy_data import (
    ensure_energy_columns,
    format_energy_summary,
    update_property_energy,
)
from property_types import is_house_type
from scoring import score_house
from score_display import completed_score_lines


HOST = "0.0.0.0"
PORT = int(
    os.environ.get(
        "ENERGY_API_INTERNAL_PORT",
        "8090",
    )
)
DB_PATH = os.environ.get(
    "DB_PATH",
    "/data/database.sqlite3",
)
API_TOKEN = os.environ.get(
    "ENERGY_API_TOKEN",
    "",
).strip()

TELEGRAM_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "",
).strip()
TELEGRAM_CHAT_ID = os.environ.get(
    "TELEGRAM_CHAT_ID",
    "",
).strip()

MAX_BODY_BYTES = 64 * 1024


def send_telegram(text):

    if not (
        TELEGRAM_TOKEN
        and TELEGRAM_CHAT_ID
    ):
        return

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=20,
        ):
            pass
    except Exception as exc:
        print(
            "ENERGY API TELEGRAM ERROR: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )


class Handler(BaseHTTPRequestHandler):

    def send_json(
        self,
        status_code,
        data,
    ):

        raw = json.dumps(
            data,
            ensure_ascii=False,
        ).encode("utf-8")

        self.send_response(status_code)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(raw)),
        )
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):

        if not API_TOKEN:
            return False

        header = self.headers.get(
            "Authorization",
            "",
        )

        return header == f"Bearer {API_TOKEN}"

    def do_GET(self):

        if self.path != "/health":
            self.send_json(
                404,
                {
                    "ok": False,
                    "error": "Not found",
                },
            )
            return

        self.send_json(
            200,
            {
                "ok": True,
                "service": "energy-api",
                "token_configured": bool(API_TOKEN),
            },
        )

    def do_POST(self):

        if self.path != "/energy":
            self.send_json(
                404,
                {
                    "ok": False,
                    "error": "Not found",
                },
            )
            return

        if not self.authorized():
            self.send_json(
                401,
                {
                    "ok": False,
                    "error": "Unauthorized",
                },
            )
            return

        try:
            content_length = int(
                self.headers.get(
                    "Content-Length",
                    "0",
                )
            )
        except ValueError:
            content_length = 0

        if not 0 < content_length <= MAX_BODY_BYTES:
            self.send_json(
                400,
                {
                    "ok": False,
                    "error": "Invalid body size",
                },
            )
            return

        conn = None

        try:
            raw = self.rfile.read(
                content_length
            )

            payload = json.loads(
                raw.decode("utf-8")
            )

            portal = str(
                payload.get("portal")
                or ""
            ).strip().lower()

            portal_id = str(
                payload.get("portal_id")
                or ""
            ).strip()

            if portal not in {
                "immoscout24",
                "immowelt",
            }:
                raise ValueError(
                    "Ungültiges Portal"
                )

            if not portal_id:
                raise ValueError(
                    "portal_id fehlt"
                )

            energy_data = payload.get(
                "energy"
            )

            if not isinstance(
                energy_data,
                dict,
            ):
                raise ValueError(
                    "energy fehlt"
                )

            energy_data = {
                **energy_data,
                "energy_data_source": (
                    energy_data.get(
                        "energy_data_source"
                    )
                    or "browser_userscript"
                ),
            }

            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row

            ensure_energy_columns(conn)

            existing = conn.execute(
                """
                SELECT *
                FROM properties
                WHERE portal = ?
                  AND portal_id = ?
                LIMIT 1
                """,
                (
                    portal,
                    portal_id,
                ),
            ).fetchone()

            if existing is None:
                conn.close()
                conn = None

                self.send_json(
                    404,
                    {
                        "ok": False,
                        "error": (
                            "Objekt nicht in der "
                            "Datenbank gefunden"
                        ),
                    },
                )
                return

            if not is_house_type(
                existing["property_type"]
            ):
                conn.close()
                conn = None

                self.send_json(
                    409,
                    {
                        "ok": False,
                        "error": (
                            "Energiedaten sind nur "
                            "für Haus/Hof vorgesehen"
                        ),
                    },
                )
                return

            old_score = existing["score"]

            property_row, normalized = (
                update_property_energy(
                    conn,
                    portal,
                    portal_id,
                    energy_data,
                )
            )

            scored_property = dict(existing)
            scored_property.update(normalized)

            score_result = score_house(
                scored_property
            )

            conn.execute(
                """
                UPDATE properties
                SET
                    score = ?,
                    rating = ?,
                    is_ko = ?,
                    score_details = ?
                WHERE portal = ?
                  AND portal_id = ?
                """,
                (
                    score_result["score"],
                    score_result["rating"],
                    int(score_result["ko"]),
                    json.dumps(
                        score_result,
                        ensure_ascii=False,
                    ),
                    portal,
                    portal_id,
                ),
            )

            conn.commit()
            conn.close()
            conn = None

            summary = format_energy_summary(
                normalized
            )

            new_score = score_result["score"]

            score_lines = completed_score_lines(
                score_result
            )
            score_lines.append(
                f"📊 Status: {score_result['rating']}"
            )

            if (
                old_score is not None
                and old_score != new_score
            ):
                score_lines.append(
                    "Vorheriger gewichteter Score: "
                    f"{old_score}/100"
                )

            score_text = "\n".join(score_lines)

            send_telegram(
                "⚡ Energiedaten aktualisiert\n\n"
                f"{property_row.get('title') or portal_id}\n"
                f"{portal} | {portal_id}\n"
                f"⚡ {summary}\n"
                f"{score_text}"
            )

            self.send_json(
                200,
                {
                    "ok": True,
                    "portal": portal,
                    "portal_id": portal_id,
                    "title": property_row.get(
                        "title"
                    ),
                    "energy": normalized,
                    "summary": summary,
                    "score": new_score,
                    "rating": score_result[
                        "rating"
                    ],
                },
            )

        except json.JSONDecodeError:
            self.send_json(
                400,
                {
                    "ok": False,
                    "error": "Ungültiges JSON",
                },
            )

        except ValueError as exc:
            self.send_json(
                400,
                {
                    "ok": False,
                    "error": str(exc),
                },
            )

        except Exception as exc:
            print(
                "ENERGY API ERROR: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

            self.send_json(
                500,
                {
                    "ok": False,
                    "error": (
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                },
            )

        finally:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass

                try:
                    conn.close()
                except Exception:
                    pass

    def log_message(
        self,
        format,
        *args,
    ):
        print(
            "ENERGY API:",
            format % args,
            flush=True,
        )


def main():

    if not API_TOKEN:
        raise RuntimeError(
            "ENERGY_API_TOKEN is not configured"
        )

    conn = sqlite3.connect(DB_PATH)
    ensure_energy_columns(conn)
    conn.close()

    print(
        f"Energy API listening on {HOST}:{PORT}",
        flush=True,
    )

    server = ThreadingHTTPServer(
        (
            HOST,
            PORT,
        ),
        Handler,
    )

    server.serve_forever()


if __name__ == "__main__":
    main()
