from __future__ import annotations

import functools
import http.server
import socketserver
import threading
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "sites"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401
        pass

    def send_error(self, code, message=None, explain=None):
        # Plain 404s (no HTML body) so the scanner's robots/sitemap probes behave like a real server.
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(b"not found")


class SiteServer:
    def __init__(self, root: Path):
        handler = functools.partial(_Quiet, directory=str(root))
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/index.html"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture(scope="session")
def bad_site():
    s = SiteServer(FIXTURES / "bad_site")
    yield s
    s.stop()


@pytest.fixture(scope="session")
def good_site():
    s = SiteServer(FIXTURES / "good_site")
    yield s
    s.stop()


@pytest.fixture
def settings(tmp_path, monkeypatch):
    from engine.config import Settings

    monkeypatch.setenv("CE_MODE", "dry_run")
    monkeypatch.setenv("CE_LLM__PROVIDER", "fake")
    monkeypatch.setenv("CE_COMPANY__POSTAL_ADDRESS", "1 Test St, Testville, TS 00000")
    monkeypatch.setenv("CE_COMPANY__LEGAL_NAME", "Test Co LLC")
    monkeypatch.setenv("CE_COMPANY__WEBSITE", "https://testco.example")
    monkeypatch.setenv("CE_COMPANY__FROM_EMAIL", "alex@outreach.testco.example")
    monkeypatch.setenv("CE_COMPANY__REPLY_DOMAIN", "outreach.testco.example")
    s = Settings(_env_file=None, database_path=tmp_path / "engine.db", workdir=tmp_path)
    s.workdir.mkdir(parents=True, exist_ok=True)
    return s


@pytest.fixture(scope="session")
def browser():
    from engine.config import ScanningSettings
    from engine.scanning.browser import open_browser

    with open_browser(ScanningSettings()) as b:
        yield b
