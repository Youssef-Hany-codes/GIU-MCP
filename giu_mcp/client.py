"""HTTP client for the GIU sites.

Both portal.giu-uni.de and cms.giu-uni.de are IIS / ASP.NET WebForms apps behind
Windows (NTLM) authentication, so every request goes through one requests.Session
with HttpNtlmAuth. ASP.NET postbacks (dropdowns, "Show" buttons) are replayed by
re-posting the page's hidden form state.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests_ntlm import HttpNtlmAuth

from .config import PORTAL_HOME, Settings, load_settings

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36 giu-mcp/0.1"
)
ALLOWED_HOSTS = {"portal.giu-uni.de", "cms.giu-uni.de"}


class GiuError(RuntimeError):
    pass


class AuthError(GiuError):
    pass


class PortalBounce(GiuError):
    """The portal sent us back to Home.aspx: its session state was not set up yet."""


@dataclass
class Page:
    url: str
    status: int
    html: str

    @property
    def soup(self) -> BeautifulSoup:
        return BeautifulSoup(self.html, "lxml")


class GiuClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings
        self._session: requests.Session | None = None
        self._lock = threading.RLock()
        self._portal_ready = False
        self._cache: dict[str, tuple[float, Page]] = {}

    # ------------------------------------------------------------------ session
    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = load_settings()
        return self._settings

    def _new_session(self) -> requests.Session:
        s = requests.Session()
        s.auth = HttpNtlmAuth(self.settings.ntlm_user, self.settings.password)
        s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        return s

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            self._session = self._new_session()
        return self._session

    def reset(self) -> None:
        with self._lock:
            if self._session is not None:
                self._session.close()
            self._session = None
            self._portal_ready = False
            self._cache.clear()

    # ------------------------------------------------------------------ requests
    @staticmethod
    def _check_host(url: str) -> None:
        host = urlparse(url).hostname or ""
        if host not in ALLOWED_HOSTS:
            raise GiuError(f"Refusing to send GIU credentials to {host!r}")

    def _send(self, method: str, url: str, **kw) -> requests.Response:
        """One hop, no redirects, with a single fresh-session retry for stale NTLM auth."""
        with self._lock:
            try:
                resp = self.session.request(method, url, allow_redirects=False, **kw)
            except requests.ConnectionError:
                # A dropped keep-alive connection breaks the NTLM handshake; retry once fresh.
                self.reset()
                resp = self.session.request(method, url, allow_redirects=False, **kw)
            if resp.status_code == 401:
                # Session/connection auth went stale: rebuild once before giving up.
                self.reset()
                resp = self.session.request(method, url, allow_redirects=False, **kw)
        if resp.status_code == 401:
            raise AuthError(
                "GIU rejected the username/password (HTTP 401). With the Claude Desktop "
                "extension, fix them in Settings > Desktop app > Extensions > GIU MCP > Configure; otherwise "
                "run `giu-mcp login` again."
            )
        return resp

    def _request(self, method: str, url: str, **kw) -> requests.Response:
        # Redirects are followed by hand so every hop is host-checked *before* the
        # NTLM handshake, never after.
        kw.setdefault("timeout", self.settings.timeout)
        for _ in range(10):
            self._check_host(url)
            resp = self._send(method, url, **kw)
            if not resp.is_redirect:
                return resp
            url = urljoin(resp.url, resp.headers["Location"])
            if resp.status_code in (301, 302, 303) and method != "GET":
                method = "GET"
                kw.pop("data", None)
            resp.close()
        raise GiuError("Too many redirects")

    def _ensure_portal(self, url: str) -> None:
        # The portal only initialises its session state when Home.aspx loads; without
        # that, every postback is bounced back to Home.
        if urlparse(url).hostname == "portal.giu-uni.de" and not self._portal_ready:
            with self._lock:
                if not self._portal_ready:
                    self._portal_ready = True  # set first: the GET below re-enters here
                    if url.split("?")[0].lower() != PORTAL_HOME.lower():
                        try:
                            self.get(PORTAL_HOME)
                        except Exception:
                            self._portal_ready = False
                            raise

    def _finish(self, requested: str, resp: requests.Response) -> Page:
        resp.raise_for_status()
        final = urlparse(resp.url)
        if final.path.lower().endswith("/systemmessage.aspx"):
            msg = parse_qs(final.query).get("err", ["The portal refused this page."])[0]
            raise GiuError(f"Portal message: {msg}")
        if (
            final.hostname == "portal.giu-uni.de"
            and final.path.lower().endswith("/extstudent/home.aspx")
            and not urlparse(requested).path.lower().endswith("/home.aspx")
        ):
            self._portal_ready = False
            raise PortalBounce("Portal redirected to Home.aspx")
        return Page(resp.url, resp.status_code, resp.text)

    def get(self, url: str, ttl: float = 0, **kw) -> Page:
        """GET a page. With ttl > 0, reuse a copy fetched within the last `ttl` seconds."""
        if ttl and url in self._cache and time.monotonic() - self._cache[url][0] < ttl:
            return self._cache[url][1]
        self._ensure_portal(url)
        page = self._finish(url, self._request("GET", url, **kw))
        if ttl:
            self._cache[url] = (time.monotonic(), page)
        return page

    def post(self, url: str, data: dict, **kw) -> Page:
        self._ensure_portal(url)
        return self._finish(url, self._request("POST", url, data=data, **kw))

    # ------------------------------------------------------------------ webforms
    @staticmethod
    def form_state(soup: BeautifulSoup, form_id: str | None = None) -> tuple[str | None, dict]:
        """Return (action, fields) for the page's main form, as a browser would submit it."""
        form = soup.find("form", id=form_id) if form_id else soup.find("form")
        if form is None:
            raise GiuError("Page has no form to post back")
        fields: dict[str, str] = {}
        for inp in form.find_all("input"):
            name = inp.get("name")
            if not name:
                continue
            typ = (inp.get("type") or "text").lower()
            if typ in {"submit", "button", "image", "reset", "file"}:
                continue
            if typ in {"checkbox", "radio"} and not inp.has_attr("checked"):
                continue
            fields[name] = inp.get("value", "on" if typ in {"checkbox", "radio"} else "")
        for sel in form.find_all("select"):
            name = sel.get("name")
            if not name:
                continue
            opt = sel.find("option", selected=True) or sel.find("option")
            fields[name] = opt.get("value", opt.get_text(strip=True)) if opt else ""
        for ta in form.find_all("textarea"):
            if ta.get("name"):
                fields[ta["name"]] = ta.get_text()
        return form.get("action"), fields

    def postback(
        self,
        page: Page,
        event_target: str = "",
        event_argument: str = "",
        fields: dict | None = None,
        submit: tuple[str, str] | None = None,
    ) -> Page:
        """Replay an ASP.NET postback from `page` (like changing a dropdown or clicking a button)."""
        action, data = self.form_state(page.soup)
        data["__EVENTTARGET"] = event_target
        data["__EVENTARGUMENT"] = event_argument
        if fields:
            data.update(fields)
        if submit:
            data[submit[0]] = submit[1]
        url = urljoin(page.url, action) if action else page.url
        return self.post(url, data)

    # ------------------------------------------------------------------ files
    def fetch_bytes(self, url: str, max_bytes: int = 200 * 1024 * 1024) -> tuple[bytes, str]:
        """Download a file into memory. Returns (content, final_url)."""
        resp = self._request("GET", url, stream=True)
        resp.raise_for_status()
        buf = bytearray()
        for chunk in resp.iter_content(chunk_size=1 << 16):
            buf.extend(chunk)
            if len(buf) > max_bytes:
                resp.close()
                raise GiuError(f"File is larger than {max_bytes // (1024 * 1024)} MB")
        return bytes(buf), resp.url

    def download(self, url: str, dest: Path, overwrite: bool = False) -> tuple[Path, bool]:
        """Stream `url` to the file `dest`. Returns (path, downloaded) — False if it already existed."""
        if dest.exists() and not overwrite:
            return dest, False
        dest.parent.mkdir(parents=True, exist_ok=True)
        resp = self._request("GET", url, stream=True)
        resp.raise_for_status()
        tmp = dest.with_name(dest.name + ".part")
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
        tmp.replace(dest)
        return dest, True


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return name[:180] or "download"


_client: GiuClient | None = None


def get_client() -> GiuClient:
    global _client
    if _client is None:
        _client = GiuClient()
    return _client
