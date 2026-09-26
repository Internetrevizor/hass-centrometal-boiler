"""Async HTTP client for the Centrometal web-boiler service.

The previous implementation depended on ``lxml`` for parsing two specific bits
of the login flow: extracting the CSRF token from ``/login`` and verifying that
the post-login response contained the loading screen marker. ``lxml`` is a
heavy C-extension that adds install friction on ARM-based Home Assistant hosts
(Raspberry Pi, etc.), so we replaced it with the standard-library
``html.parser`` which is more than enough for those two checks.

TLS certificate verification is always enabled. Certificate failures reported
against this endpoint were traced to outdated CA trust stores on some Home
Assistant hosts rather than anything wrong with the server's certificate
chain, so verification is performed against a current root store instead of
being disabled.

Which store that is comes from the caller. Under Home Assistant the framework
layer injects ``homeassistant.util.ssl.get_default_context``, which is built
once at import time from ``certifi`` (or ``REQUESTS_CA_BUNDLE`` when the user
set one) and shared process-wide. Standalone -- tests, scripts -- the built-in
``build_verified_ssl_context`` is used, which prefers ``certifi`` when it is
installed and falls back to the interpreter's default store when it is not.
Verification is never disabled on any of those paths.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any

import aiohttp

from .const import WEB_BOILER_WEBROOT
from .logging_utils import redact_account

DEFAULT_CLIENT_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10, sock_connect=10, sock_read=20)

# Supplied by the Home Assistant layer so the integration can reuse Home
# Assistant's own cached SSL context instead of building (and paying for) a
# second one. Kept as a plain callable so this package still imports and
# runs with no Home Assistant present.
SSLContextFactory = Callable[[], ssl.SSLContext]

# Keys that identify the installation or its owner. Redacted from debug
# dumps so a log pasted into a GitHub issue does not carry the address of
# someone's house -- the same policy diagnostics.py applies.
_PII_KEYS = frozenset({"address", "place", "city", "country", "countryCode", "email", "phone", "tel"})
_INSTALLATION_PII_KEYS = _PII_KEYS | {"label", "value", "serial", "id"}

# Fragment that appears on the unauthenticated login page. Used to detect
# session expiry on JSON endpoints (which then return the login HTML rather
# than 401, because the upstream service is a server-rendered Symfony app).
_LOGIN_FORM_MARKER = '<form action="/login_check"'

# id of the div that the login response renders when authentication succeeded.
_POST_LOGIN_LOADING_DIV_ID = "id-loading-screen-blackout"


class HttpClientAuthError(Exception):
    """Raised when Centrometal credentials are invalid or expired."""


class HttpClientConnectionError(Exception):
    """Raised when the Centrometal service cannot be reached reliably."""


class _CsrfTokenExtractor(HTMLParser):
    """Find ``<input name="_csrf_token" value="...">`` in the login page.

    Stops at the first match. We don't try to be a full HTML parser; the
    server has rendered the same template for years and the field is unique.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.token: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.token is not None or tag != "input":
            return
        attr_map = dict(attrs)
        if attr_map.get("name") == "_csrf_token":
            value = attr_map.get("value")
            if value:
                self.token = value


class _LoadingDivPresent(HTMLParser):
    """Detect the presence of the post-login loading-screen div."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.found or tag != "div":
            return
        if dict(attrs).get("id") == _POST_LOGIN_LOADING_DIV_ID:
            self.found = True


def _extract_csrf_token(html_text: str) -> str | None:
    parser = _CsrfTokenExtractor()
    parser.feed(html_text)
    parser.close()
    return parser.token


def _login_succeeded(html_text: str) -> bool:
    parser = _LoadingDivPresent()
    parser.feed(html_text)
    parser.close()
    return parser.found


def _redact(value: Any, keys: frozenset[str] | set[str] = _PII_KEYS) -> Any:
    """Return ``value`` with any key in ``keys`` replaced by a marker.

    Recursive and non-destructive: the caller keeps the original payload, the
    log gets the redacted copy. Parameter values themselves are never touched,
    because they are the whole point of reading a debug log.
    """
    if isinstance(value, dict):
        return {k: ("**redacted**" if k in keys else _redact(v, keys)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item, keys) for item in value]
    return value


def build_verified_ssl_context() -> ssl.SSLContext:
    """Build an SSL context that verifies certificates against a current CA bundle.

    Uses ``certifi``'s root store when available so verification does not
    depend on the host's system trust store being up to date -- an outdated
    system store, not a bad server certificate, was the actual cause of past
    verification failures against this endpoint. Falls back to the
    interpreter's own default trust store if ``certifi`` is not installed;
    verification is never disabled either way.
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


async def _make_connector(ssl_context_factory: SSLContextFactory | None = None) -> aiohttp.TCPConnector:
    # build_verified_ssl_context() does blocking disk I/O (reading and
    # parsing the certifi CA bundle via ssl.create_default_context's
    # internal load_verify_locations). Must never run directly on the
    # event loop -- this exact call used to, and Home Assistant's
    # blocking-call detector caught it in production. An injected factory
    # (Home Assistant's cached context) is cheap, but it goes through the
    # same executor hop so no caller can ever reintroduce that bug.
    loop = asyncio.get_running_loop()
    factory = ssl_context_factory or build_verified_ssl_context
    ssl_ctx = await loop.run_in_executor(None, factory)
    return aiohttp.TCPConnector(
        resolver=aiohttp.DefaultResolver(),
        use_dns_cache=True,
        ssl=ssl_ctx,
    )


class HttpClientBase:
    headers: dict[str, str] = {
        "Origin": WEB_BOILER_WEBROOT,
        "Referer": WEB_BOILER_WEBROOT + "/",
    }
    headers_json: dict[str, str] = {
        "Origin": WEB_BOILER_WEBROOT,
        "Referer": WEB_BOILER_WEBROOT + "/",
        "Content-Type": "application/json;charset=UTF-8",
    }

    def __init__(self, username: str, password: str, *, ssl_context_factory: SSLContextFactory | None = None) -> None:
        self.logger = logging.getLogger(__name__)
        self._ssl_context_factory = ssl_context_factory
        self.username = username
        self.password = password
        self.log_account = redact_account(username)
        self.parameter_list: dict[str, Any] = {}
        # Lazy: aiohttp.ClientSession requires a running event loop on modern
        # aiohttp versions. The original code created the session in __init__,
        # which only worked because the integration always constructs HttpClient
        # from inside an async context. We defer creation until first use so
        # that direct construction (tests, scripts) does not crash.
        self.http_session: aiohttp.ClientSession | None = None
        # Guards session creation *and* teardown now that creation has a real
        # await point inside it (the executor hop for building the SSL
        # context). Without this, concurrent first calls (e.g. the parallel
        # requests fired by get_configuration()'s asyncio.gather) could each
        # see no session yet and each build their own, leaking every
        # ClientSession but the last one assigned; and close_session()
        # running concurrently with session creation could hand out a
        # session that's simultaneously being closed.
        self._session_lock = asyncio.Lock()

    async def _ensure_session(self) -> aiohttp.ClientSession:
        # Fast path: avoid lock overhead once a session already exists and
        # is still usable, which is true for the overwhelming majority of
        # calls (only the very first call, or one right after
        # reinitialize_session(), needs to actually create anything).
        session = self.http_session
        if session is not None and not session.closed:
            return session

        async with self._session_lock:
            # Re-check: another caller may have already finished creating
            # (or reinitializing) the session while this one was waiting for
            # the lock.
            session = self.http_session
            if session is None or session.closed:
                # Called without arguments when no factory was injected so a
                # test double for _make_connector keeps its simple signature.
                if self._ssl_context_factory is None:
                    connector = await _make_connector()
                else:
                    connector = await _make_connector(self._ssl_context_factory)
                session = aiohttp.ClientSession(connector=connector, timeout=DEFAULT_CLIENT_TIMEOUT)
                self.http_session = session
            return session

    async def reinitialize_session(self) -> None:
        await self.close_session()
        await self._ensure_session()

    async def close_session(self) -> None:
        # Locked so this can't interleave with _ensure_session() -- e.g. one
        # coroutine closing the session at the exact moment another is
        # about to hand out the very session being closed.
        async with self._session_lock:
            session = self.http_session
            self.http_session = None
            if session is not None:
                await session.close()

    async def _require_session(self) -> aiohttp.ClientSession:
        return await self._ensure_session()

    async def _request_text(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        data: Any | None = None,
        expected_code: int = 200,
    ) -> str:
        full_url = WEB_BOILER_WEBROOT + url
        self.logger.debug("%s %s (%s)", method.upper(), full_url, self.log_account)
        session = await self._require_session()

        kwargs: dict[str, Any] = {"headers": headers}
        if data is not None:
            kwargs["data"] = data
        try:
            async with session.request(method, full_url, **kwargs) as response:
                if response.status != expected_code:
                    raise HttpClientConnectionError(f"{method.upper()} {url} failed with http code {response.status}")
                return await response.text()
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            raise HttpClientConnectionError(f"{method.upper()} request failed for {url}: {err}") from err

    async def _http_get(self, url: str, expected_code: int = 200) -> str:
        return await self._request_text("GET", url, headers=self.headers, expected_code=expected_code)

    async def _http_post(self, url: str, data: Any | None = None, expected_code: int = 200) -> str:
        return await self._request_text("POST", url, headers=self.headers, data=data, expected_code=expected_code)

    async def _http_post_json(self, url: str, data: Any | None = None, expected_code: int = 200) -> dict[str, Any]:
        response_text = await self._request_text(
            "POST",
            url,
            headers=self.headers_json,
            data=data,
            expected_code=expected_code,
        )

        if _LOGIN_FORM_MARKER in response_text:
            raise HttpClientAuthError(f"POST-json {url} session expired (login page returned)")

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as err:
            self.logger.debug(
                "POST-json %s returned non-JSON response (%s): %r",
                url,
                self.log_account,
                response_text[:300],
            )
            raise HttpClientConnectionError(f"POST-json {url} returned non-JSON response") from err

    async def _control_multiple(self, data: dict[str, Any]) -> dict[str, Any]:
        self.logger.debug("Sending control multiple %s (%s)", data, self.log_account)
        response = await self._http_post_json("/api/inst/control/multiple", data=json.dumps(data))
        self.logger.debug("Received response %s (%s)", response, self.log_account)
        return response

    async def _control(self, id: str | int, data: dict[str, Any]) -> dict[str, Any]:
        self.logger.debug("Sending control %s (%s)", data, self.log_account)
        response = await self._http_post_json("/api/inst/control/" + str(id), data=json.dumps(data))
        self.logger.debug("Received response %s (%s)", response, self.log_account)
        return response

    async def _control_advanced(self, id: str | int, data: dict[str, Any]) -> dict[str, Any]:
        self.logger.debug("Sending control advanced %s (%s)", data, self.log_account)
        response = await self._http_post_json("/api/inst/control/advanced/" + str(id), data=json.dumps(data))
        self.logger.debug("Received response %s (%s)", response, self.log_account)
        return response


class HttpClient(HttpClientBase):
    def __init__(self, username: str, password: str, *, ssl_context_factory: SSLContextFactory | None = None) -> None:
        super().__init__(username, password, ssl_context_factory=ssl_context_factory)
        # State populated lazily by the public API. Declared here so attribute
        # access never raises AttributeError before the first call, and so
        # static analysis can see the contract.
        self.csrf_token: str = ""
        self.installations: list[dict[str, Any]] = []
        self.installation_status_all: dict[str, Any] = {}
        self.errors_list: dict[str, Any] = {}

    async def __get_csrf_token(self) -> None:
        self.logger.debug("HttpClient - Fetching CSRF token (%s)", self.log_account)
        html_text = await self._http_get("/login")
        token = _extract_csrf_token(html_text)
        if not token:
            raise HttpClientConnectionError("HttpClient::get_csrf_token failed - cannot find CSRF token")
        self.logger.debug("HttpClient - csrf_token obtained (%s)", self.log_account)
        self.csrf_token = token

    async def __login_check(self) -> None:
        self.logger.info("HttpClient - Logging in... (%s)", self.log_account)
        data = {
            "_csrf_token": self.csrf_token,
            "_username": self.username,
            "_password": self.password,
            "submit": "Log In",
        }
        html_text = await self._http_post("/login_check", data=data)

        if _login_succeeded(html_text):
            self.logger.info("HttpClient - Login successful (%s)", self.log_account)
            return

        if _LOGIN_FORM_MARKER in html_text:
            raise HttpClientAuthError("Invalid Centrometal credentials")

        raise HttpClientConnectionError("Unexpected login response from Centrometal service")

    async def login(self) -> bool:
        await self.__get_csrf_token()
        await self.__login_check()
        return True

    async def get_installations(self) -> list[dict[str, Any]]:
        payload = await self._http_post_json("/data/autocomplete/installation", data=json.dumps({}))
        try:
            self.installations = payload["installations"]
        except (KeyError, TypeError) as err:
            raise HttpClientConnectionError("Installation list response had no 'installations' key") from err
        # json.dumps() of the full payload is not free, and arguments are
        # evaluated before the logger checks the level -- so this only runs
        # when debug logging is actually on.
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                "HttpClient::get_installations -> %s (%s)",
                json.dumps(_redact(self.installations, _INSTALLATION_PII_KEYS)),
                self.log_account,
            )
        return self.installations

    async def get_installation_status_all(self, ids: list[str | int]) -> dict[str, Any]:
        data = {"installations": ids}
        self.installation_status_all = await self._http_post_json(
            "/wdata/data/installation-status-all", data=json.dumps(data)
        )
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                "HttpClient::get_installation_status_all -> %s (%s)",
                json.dumps(_redact(self.installation_status_all)),
                self.log_account,
            )
        return self.installation_status_all

    async def get_parameter_list(self, serial: str) -> dict[str, Any]:
        self.parameter_list[serial] = await self._http_post_json(
            "/wdata/data/parameter-list/" + serial, data=json.dumps({})
        )
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                "HttpClient::get_parameter_list -> %s (%s)",
                json.dumps(_redact(self.parameter_list[serial])),
                self.log_account,
            )
        return self.parameter_list[serial]

    async def get_errors_list(self, id: str | int, *, interval: int = 1440, error_type: str = "*") -> dict[str, Any]:
        """Return the decoded event/error list used by the portal widget."""
        payload = await self._http_post_json(
            "/wdata/data/multi/errors-list/" + str(id),
            data=json.dumps({"interval": str(interval), "errorType": error_type}),
        )
        self.errors_list[str(id)] = payload
        return payload

    async def refresh_device(self, id: str | int) -> dict[str, Any]:
        data = {"messages": {str(id): {"REFRESH": 0}}}
        return await self._control_multiple(data)

    async def rstat_all_device(self, id: str | int) -> dict[str, Any]:
        data = {"messages": {str(id): {"RSTAT": "ALL"}}}
        return await self._control_multiple(data)

    async def get_table_data(self, id: str | int, tableStartIndex: int, tableSubIndex: int) -> dict[str, Any]:
        params = {
            "PRD " + str(tableStartIndex): "VAL",
            "PRD " + str(tableStartIndex + tableSubIndex): "ALV",
        }
        data = {"parameters": params}
        return await self._control_advanced(id, data)

    def get_table_data_all(self, id: str | int, tableStartIndex: int, tableSize: int) -> list:
        # NOTE: this is intentionally synchronous; it produces a list of
        # coroutine objects for the caller to ``await asyncio.gather(...)``.
        return [self.get_table_data(id, tableStartIndex, i) for i in range(1, tableSize + 1)]

    async def set_parameter_value(self, id: str | int, dbindex: int | str, value: float) -> dict[str, Any]:
        """Write an editable settings slot.

        Captured from the portal's own request when the pencil on a settings
        row is used: {"cmd-name": "PWR 67", "cmd-value": 66} sets slot 67
        ("Buffer tank temperature") to 66 C. Same envelope as the boiler
        on/off command, and the value is the plain reading -- slot 67 holds
        40..85 for 40..85 C, so there is no scaling.
        """
        data = {"cmd-name": f"PWR {dbindex}", "cmd-value": value}
        return await self._control(id, data)

    async def turn_device_by_id(self, id: str | int, on: bool) -> dict[str, Any]:
        cmd_value = 1 if on else 0
        data = {"cmd-name": "CMD", "cmd-value": cmd_value}
        return await self._control(id, data)

    async def turn_device_circuit(self, id: str | int, circuit: int, on: bool) -> dict[str, Any]:
        cmd_name = "PWR " + str(circuit)
        cmd_value = 1 if on else 0
        data = {"messages": {str(id): {cmd_name: cmd_value}}}
        return await self._control_multiple(data)
