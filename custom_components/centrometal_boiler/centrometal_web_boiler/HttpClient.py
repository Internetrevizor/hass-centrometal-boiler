"""Async HTTP client for the Centrometal web-boiler service.

The previous implementation depended on ``lxml`` for parsing two specific bits
of the login flow: extracting the CSRF token from ``/login`` and verifying that
the post-login response contained the loading screen marker. ``lxml`` is a
heavy C-extension that adds install friction on ARM-based Home Assistant hosts
(Raspberry Pi, etc.), so we replaced it with the standard-library
``html.parser`` which is more than enough for those two checks.

The upstream Centrometal endpoint may present an incomplete certificate chain on
some Home Assistant/Python hosts. For compatibility, this integration defaults
to skipping certificate verification for this specific cloud endpoint. Users who
wish to enforce strict verification can set ``CENTROMETAL_VERIFY_SSL=1``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from html.parser import HTMLParser
from typing import Any

import aiohttp

from .const import WEB_BOILER_WEBROOT
from .logging_utils import redact_account

DEFAULT_CLIENT_TIMEOUT = aiohttp.ClientTimeout(
    total=30, connect=10, sock_connect=10, sock_read=20
)

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
    return parser.token


def _login_succeeded(html_text: str) -> bool:
    parser = _LoadingDivPresent()
    parser.feed(html_text)
    return parser.found


TLS_VERIFY_ENV = "CENTROMETAL_VERIFY_SSL"
_TRUE_VALUES = {"1", "true", "yes", "on", "strict"}
_FALSE_VALUES = {"0", "false", "no", "off", "insecure"}


def _tls_verify_mode() -> str:
    """Return TLS verification mode: ``off`` (default), ``strict`` or ``auto``.

    The Centrometal endpoint has historically presented incomplete certificate
    chains on some Home Assistant/Python installations. Defaulting to ``off``
    avoids repeated certificate warnings and keeps existing installations working.
    Set ``CENTROMETAL_VERIFY_SSL=1`` to require strict certificate verification,
    or ``CENTROMETAL_VERIFY_SSL=auto`` to try verified TLS first and fallback only
    on certificate errors.
    """

    value = os.environ.get(TLS_VERIFY_ENV, "0").strip().lower()
    if value in _TRUE_VALUES:
        return "strict"
    if value in _FALSE_VALUES:
        return "off"
    if value == "auto":
        return "auto"
    return "off"


def _ssl_request_value() -> bool | None:
    return False if _tls_verify_mode() == "off" else None


def _is_certificate_error(err: BaseException) -> bool:
    return isinstance(
        err,
        (
            aiohttp.ClientConnectorCertificateError,
            aiohttp.ClientConnectorSSLError,
            aiohttp.ClientSSLError,
        ),
    )


def _make_connector() -> aiohttp.TCPConnector:
    return aiohttp.TCPConnector(
        resolver=aiohttp.DefaultResolver(),
        use_dns_cache=True,
        family=socket.AF_INET,
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

    def __init__(self, username: str, password: str) -> None:
        self.logger = logging.getLogger(__name__)
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

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self.http_session is None:
            self.http_session = aiohttp.ClientSession(
                connector=_make_connector(), timeout=DEFAULT_CLIENT_TIMEOUT
            )
        return self.http_session

    async def reinitialize_session(self) -> None:
        await self.close_session()
        self._ensure_session()

    async def close_session(self) -> None:
        if self.http_session is not None:
            await self.http_session.close()
            self.http_session = None

    def _require_session(self) -> aiohttp.ClientSession:
        return self._ensure_session()

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
        session = self._require_session()

        async def do_request(ssl_value: bool | None) -> str:
            kwargs: dict[str, Any] = {"headers": headers}
            if data is not None:
                kwargs["data"] = data
            if ssl_value is not None:
                kwargs["ssl"] = ssl_value
            async with session.request(method, full_url, **kwargs) as response:
                if response.status != expected_code:
                    raise HttpClientConnectionError(
                        f"{method.upper()} {url} failed with http code {response.status}"
                    )
                return await response.text()

        try:
            return await do_request(_ssl_request_value())
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
            if _tls_verify_mode() == "auto" and _is_certificate_error(err):
                self.logger.debug(
                    "TLS certificate verification failed for %s; retrying without verification because %s=auto. Error: %s",
                    WEB_BOILER_WEBROOT,
                    TLS_VERIFY_ENV,
                    err,
                )
                try:
                    return await do_request(False)
                except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as retry_err:
                    raise HttpClientConnectionError(
                        f"{method.upper()} request failed for {url}: {retry_err}"
                    ) from retry_err
            raise HttpClientConnectionError(
                f"{method.upper()} request failed for {url}: {err}"
            ) from err

    async def _http_get(self, url: str, expected_code: int = 200) -> str:
        return await self._request_text(
            "GET", url, headers=self.headers, expected_code=expected_code
        )

    async def _http_post(
        self, url: str, data: Any | None = None, expected_code: int = 200
    ) -> str:
        return await self._request_text(
            "POST", url, headers=self.headers, data=data, expected_code=expected_code
        )

    async def _http_post_json(
        self, url: str, data: Any | None = None, expected_code: int = 200
    ) -> dict[str, Any]:
        response_text = await self._request_text(
            "POST",
            url,
            headers=self.headers_json,
            data=data,
            expected_code=expected_code,
        )

        if _LOGIN_FORM_MARKER in response_text:
            raise HttpClientAuthError(
                f"POST-json {url} session expired (login page returned)"
            )

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as err:
            self.logger.debug(
                "POST-json %s returned non-JSON response (%s): %r",
                url,
                self.log_account,
                response_text[:300],
            )
            raise HttpClientConnectionError(
                f"POST-json {url} returned non-JSON response"
            ) from err

    async def _control_multiple(self, data: dict[str, Any]) -> dict[str, Any]:
        self.logger.debug("Sending control multiple %s (%s)", data, self.log_account)
        response = await self._http_post_json(
            "/api/inst/control/multiple", data=json.dumps(data)
        )
        self.logger.debug("Received response %s (%s)", response, self.log_account)
        return response

    async def _control(self, id: str | int, data: dict[str, Any]) -> dict[str, Any]:
        self.logger.debug("Sending control %s (%s)", data, self.log_account)
        response = await self._http_post_json(
            "/api/inst/control/" + str(id), data=json.dumps(data)
        )
        self.logger.debug("Received response %s (%s)", response, self.log_account)
        return response

    async def _control_advanced(self, id: str | int, data: dict[str, Any]) -> dict[str, Any]:
        self.logger.debug("Sending control advanced %s (%s)", data, self.log_account)
        response = await self._http_post_json(
            "/api/inst/control/advanced/" + str(id), data=json.dumps(data)
        )
        self.logger.debug("Received response %s (%s)", response, self.log_account)
        return response


class HttpClient(HttpClientBase):
    def __init__(self, username: str, password: str) -> None:
        super().__init__(username, password)
        # State populated lazily by the public API. Declared here so attribute
        # access never raises AttributeError before the first call, and so
        # static analysis can see the contract.
        self.csrf_token: str = ""
        self.installations: list[dict[str, Any]] = []
        self.configuration: dict[str, Any] = {}
        self.widgetgrid_list: dict[str, Any] = {}
        self.widgetgrid: dict[str, Any] = {}
        self.installation_status_all: dict[str, Any] = {}
        self.grid: dict[str, Any] = {}

    async def __get_csrf_token(self) -> None:
        self.logger.debug("HttpClient - Fetching CSRF token (%s)", self.log_account)
        html_text = await self._http_get("/login")
        token = _extract_csrf_token(html_text)
        if not token:
            raise HttpClientConnectionError(
                "HttpClient::get_csrf_token failed - cannot find CSRF token"
            )
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

    async def get_notifications(self) -> None:
        await self._http_post("/notifications/data/get")

    async def get_installations(self) -> list[dict[str, Any]]:
        payload = await self._http_post_json(
            "/data/autocomplete/installation", data=json.dumps({})
        )
        self.installations = payload["installations"]
        self.logger.debug(
            "HttpClient::get_installations -> %s (%s)",
            json.dumps(self.installations, indent=4),
            self.log_account,
        )
        return self.installations

    async def get_configuration(self) -> dict[str, Any]:
        self.configuration = await self._http_post_json(
            "/api/configuration", data=json.dumps({})
        )
        self.logger.debug(
            "HttpClient::get_configuration -> %s (%s)",
            json.dumps(self.configuration, indent=4),
            self.log_account,
        )
        return self.configuration

    async def get_widgetgrid_list(self) -> dict[str, Any]:
        self.widgetgrid_list = await self._http_post_json(
            "/api/widgets-grid/list", data=json.dumps({})
        )
        return self.widgetgrid_list

    async def get_widgetgrid(self, id: str | int) -> dict[str, Any]:
        data = {"id": str(id), "inst": "null"}
        self.widgetgrid = await self._http_post_json(
            "/api/widgets-grid", data=json.dumps(data)
        )
        return self.widgetgrid

    async def get_installation_status_all(self, ids: list[str | int]) -> dict[str, Any]:
        data = {"installations": ids}
        self.installation_status_all = await self._http_post_json(
            "/wdata/data/installation-status-all", data=json.dumps(data)
        )
        self.logger.debug(
            "HttpClient::get_installation_status_all -> %s (%s)",
            json.dumps(self.installation_status_all, indent=4),
            self.log_account,
        )
        return self.installation_status_all

    async def get_parameter_list(self, serial: str) -> dict[str, Any]:
        self.parameter_list[serial] = await self._http_post_json(
            "/wdata/data/parameter-list/" + serial, data=json.dumps({})
        )
        self.logger.debug(
            "HttpClient::get_parameter_list -> %s (%s)",
            json.dumps(self.parameter_list[serial], indent=4),
            self.log_account,
        )
        return self.parameter_list[serial]

    async def refresh_device(self, id: str | int) -> dict[str, Any]:
        data = {"messages": {str(id): {"REFRESH": 0}}}
        return await self._control_multiple(data)

    async def rstat_all_device(self, id: str | int) -> dict[str, Any]:
        data = {"messages": {str(id): {"RSTAT": "ALL"}}}
        return await self._control_multiple(data)

    async def get_table_data(
        self, id: str | int, tableStartIndex: int, tableSubIndex: int
    ) -> dict[str, Any]:
        params = {
            "PRD " + str(tableStartIndex): "VAL",
            "PRD " + str(tableStartIndex + tableSubIndex): "ALV",
        }
        data = {"parameters": params}
        return await self._control_advanced(id, data)

    def get_table_data_all(
        self, id: str | int, tableStartIndex: int, tableSize: int
    ) -> list:
        # NOTE: this is intentionally synchronous; it produces a list of
        # coroutine objects for the caller to ``await asyncio.gather(...)``.
        return [
            self.get_table_data(id, tableStartIndex, i)
            for i in range(1, tableSize + 1)
        ]

    async def turn_device_by_id(self, id: str | int, on: bool) -> dict[str, Any]:
        cmd_value = 1 if on else 0
        data = {"cmd-name": "CMD", "cmd-value": cmd_value}
        return await self._control(id, data)

    async def turn_device_circuit(
        self, id: str | int, circuit: int, on: bool
    ) -> dict[str, Any]:
        cmd_name = "PWR " + str(circuit)
        cmd_value = 1 if on else 0
        data = {"messages": {str(id): {cmd_name: cmd_value}}}
        return await self._control_multiple(data)
