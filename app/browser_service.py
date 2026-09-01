import json
from http.server import (
    BaseHTTPRequestHandler,
    ThreadingHTTPServer,
)
from urllib.parse import (
    parse_qs,
    urlparse,
)

from playwright.sync_api import sync_playwright


HOST = "0.0.0.0"
PORT = 8080


def fetch_page(url):
    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        context = browser.new_context(
            locale="de-DE",
            user_agent=(
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=45000,
            )

            # Etwas Zeit für JavaScript-Daten geben.
            page.wait_for_timeout(2500)

            final_url = page.url
            html = page.content()
            title = page.title()

            status = (
                response.status
                if response is not None
                else None
            )

            return {
                "ok": True,
                "status": status,
                "url": final_url,
                "title": title,
                "html": html,
            }

        finally:
            context.close()
            browser.close()


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

        self.send_response(
            status_code
        )

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

    def do_GET(self):

        parsed = urlparse(
            self.path
        )

        if parsed.path == "/health":
            self.send_json(
                200,
                {
                    "ok": True,
                },
            )
            return

        if parsed.path != "/fetch":
            self.send_json(
                404,
                {
                    "ok": False,
                    "error": "Not found",
                },
            )
            return

        params = parse_qs(
            parsed.query
        )

        url = (
            params.get("url", [None])[0]
        )

        if not url:
            self.send_json(
                400,
                {
                    "ok": False,
                    "error": "Missing url",
                },
            )
            return

        if not (
            url.startswith("http://")
            or url.startswith("https://")
        ):
            self.send_json(
                400,
                {
                    "ok": False,
                    "error": "Invalid URL",
                },
            )
            return

        try:
            result = fetch_page(
                url
            )

            self.send_json(
                200,
                result,
            )

        except Exception as exc:
            print(
                "BROWSER FETCH ERROR: "
                f"{type(exc).__name__}: "
                f"{exc}",
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

    def log_message(
        self,
        format,
        *args,
    ):
        print(
            "BROWSER:",
            format % args,
            flush=True,
        )


def main():

    print(
        f"Property browser listening "
        f"on {HOST}:{PORT}",
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
