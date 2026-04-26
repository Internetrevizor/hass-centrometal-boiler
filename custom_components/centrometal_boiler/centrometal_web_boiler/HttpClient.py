from __future__ import annotations

import asyncio
import json
import logging
import socket

import aiohttp
from lxml import html

from .const import WEB_BOILER_WEBROOT
from .logging_utils import redact_account

DEFAULT_CLIENT_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10, sock_connect=10, sock_read=20)


class HttpClientAuthError(Exception):
    """Raised when Centrometal credentials are invalid or expired."""


class HttpClientConnectionError(Exception):
    """Raised when the Centrometal service cannot be reached reliably."""


def _make_connector() -> aiohttp.TCPConnector:
    return aiohttp.TCPConnector(
        resolver=aiohttp.DefaultResolver(),
        use_dns_cache=True,
        family=socket.AF_INET,
    )


class HttpClientBase:
    headers = {"Origin": WEB_BOILER_WEBROOT, "Referer": WEB_BOILER_WEBROOT + "/"}
    headers_json = {
        "Origin": WEB_BOILER_WEBROOT,
        "Referer": WEB_BOILER_WEBROOT + "/",
        "Content-Type": "application/json;charset=UTF-8",
    }

    def __init__(self, username, password):
        self.logger = logging.getLogger(__name__)
        self.username = username
        self.password = password
        self.log_account = redact_account(username)
        self.parameter_list = dict()
        self.http_session = aiohttp.ClientSession(connector=_make_connector(), timeout=DEFAULT_CLIENT_TIMEOUT)

    async def reinitialize_session(self):
        await self.close_session()
        self.http_session = aiohttp.ClientSession(connector=_make_connector(), timeout=DEFAULT_CLIENT_TIMEOUT)

    async def close_session(self):
        if self.http_session is not None:
            await self.http_session.close()
            self.http_session = None

    async def _http_get(self, url, expected_code=200) -> html.HtmlElement:
        full_url = WEB_BOILER_WEBROOT + url
        self.logger.debug("GET %s (%s)", full_url, self.log_account)
        try:
            async with self.http_session.get(full_url, headers=self.headers, ssl=False) as response:
                if response.status != expected_code:
                    raise HttpClientConnectionError(
                        f"HttpClientBase::_http_get {url} failed with http code: {response.status}"
                    )
                response_text = await response.text()
                return html.fromstring(response_text)
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
            raise HttpClientConnectionError(f"GET request failed for {url}: {err}") from err

    async def _http_post(self, url, data=None, expected_code=200) -> html.HtmlElement:
        full_url = WEB_BOILER_WEBROOT + url
        self.logger.debug("POST %s (%s)", full_url, self.log_account)
        try:
            async with self.http_session.post(full_url, headers=self.headers, data=data, ssl=False) as response:
                if response.status != expected_code:
                    raise HttpClientConnectionError(
                        f"HttpClientBase::_http_post {url} failed with http code: {response.status}"
                    )
                response_text = await response.text()
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
            raise HttpClientConnectionError(f"POST request failed for {url}: {err}") from err

        try:
            return html.fromstring(response_text)
        except Exception as err:
            raise HttpClientConnectionError(
                f"HttpClientBase::_http_post {url} failed to parse html content"
            ) from err

    async def _http_post_json(self, url, data=None, expected_code=200) -> dict:
        full_url = WEB_BOILER_WEBROOT + url
        self.logger.debug("POST-json %s (%s)", full_url, self.log_account)
        try:
            async with self.http_session.post(
                full_url, headers=self.headers_json, data=data, ssl=False
            ) as response:
                if response.status != expected_code:
                    raise HttpClientConnectionError(
                        f"HttpClientBase::_http_post_json {url} failed with http code: {response.status}"
                    )
                response_text = await response.text()
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
            raise HttpClientConnectionError(f"POST-json request failed for {url}: {err}") from err

        if '<form action="/login_check"' in response_text:
            raise HttpClientAuthError(
                f"HttpClientBase::_http_post_json {url} session expired (login page returned)"
            )

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as err:
            self.logger.debug(
                "HttpClientBase::_http_post_json %s returned non-JSON response (%s): %r",
                url,
                self.log_account,
                response_text[:300],
            )
            raise HttpClientConnectionError(
                f"HttpClientBase::_http_post_json {url} returned non-JSON response"
            ) from err

    async def _control_multiple(self, data):
        response = await self._http_post_json(
            "/api/inst/control/multiple", data=json.dumps(data)
        )
        self.logger.debug("Sending control multiple %s (%s)", data, self.log_account)
        self.logger.debug("Received response %s (%s)", json.dumps(response), self.log_account)
        return response

    async def _control(self, id, data):
        response = await self._http_post_json(
            "/api/inst/control/" + str(id), data=json.dumps(data)
        )
        self.logger.debug("Sending control %s (%s)", data, self.log_account)
        self.logger.debug("Received response %s (%s)", json.dumps(response), self.log_account)
        return response

    async def _control_advanced(self, id, data):
        response = await self._http_post_json(
            "/api/inst/control/advanced/" + str(id), data=json.dumps(data)
        )
        self.logger.debug("Sending control advanced %s (%s)", data, self.log_account)
        self.logger.debug("Received response %s (%s)", json.dumps(response), self.log_account)
        return response


class HttpClient(HttpClientBase):
    async def __get_csrf_token(self) -> None:
        self.logger.debug("HttpClient - Fetching getCsrfToken (%s)", self.log_account)
        html_doc = await self._http_get("/login")
        input_element = html_doc.xpath('//input[@name="_csrf_token"]')
        if len(input_element) != 1:
            raise HttpClientConnectionError("HttpClient::getCsrfToken failed - cannot find csrf token")

        values = input_element[0].xpath("@value")
        if len(values) != 1:
            raise HttpClientConnectionError("HttpClient::getCsrfToken failed - cannot find csrf token value")

        self.logger.debug("HttpClient - csrf_token obtained (%s)", self.log_account)
        self.csrf_token = values[0]

    async def __login_check(self) -> None:
        self.logger.info("HttpClient - Logging in... (%s)", self.log_account)
        data = {
            "_csrf_token": self.csrf_token,
            "_username": self.username,
            "_password": self.password,
            "submit": "Log In",
        }
        html_doc = await self._http_post("/login_check", data=data)

        loading_div_element = html_doc.xpath('//div[@id="id-loading-screen-blackout"]')
        if len(loading_div_element) == 1:
            self.logger.info("HttpClient - Login successful (%s)", self.log_account)
            return

        login_form = html_doc.xpath('//form[@action="/login_check"]')
        if login_form:
            raise HttpClientAuthError("Invalid Centrometal credentials")

        raise HttpClientConnectionError("Unexpected login response from Centrometal service")

    async def login(self) -> bool:
        await self.__get_csrf_token()
        await self.__login_check()
        return True

    async def get_notifications(self) -> None:
        await self._http_post("/notifications/data/get")

    async def get_installations(self):
        self.installations = await self._http_post_json(
            "/data/autocomplete/installation", data=json.dumps({})
        )
        self.installations = self.installations["installations"]
        self.logger.debug("HttpClient::get_installations -> %s (%s)", json.dumps(self.installations, indent=4), self.log_account)

    async def get_configuration(self) -> None:
        self.configuration = await self._http_post_json(
            "/api/configuration", data=json.dumps({})
        )
        self.logger.debug("HttpClient::get_configuration -> %s (%s)", json.dumps(self.configuration, indent=4), self.log_account)

    async def get_widgetgrid_list(self) -> None:
        self.widgetgrid_list = await self._http_post_json(
            "/api/widgets-grid/list", data=json.dumps({})
        )

    async def get_widgetgrid(self, id):
        data = {"id": str(id), "inst": "null"}
        self.widgetgrid = await self._http_post_json(
            "/api/widgets-grid", data=json.dumps(data)
        )

    async def get_installation_status_all(self, ids: list) -> None:
        data = {"installations": ids}
        self.installation_status_all = await self._http_post_json(
            "/wdata/data/installation-status-all", data=json.dumps(data)
        )
        self.logger.debug("HttpClient::get_installation_status_all -> %s (%s)", json.dumps(self.installation_status_all, indent=4), self.log_account)

    async def get_parameter_list(self, serial) -> None:
        self.parameter_list[serial] = await self._http_post_json(
            "/wdata/data/parameter-list/" + serial, data=json.dumps({})
        )
        self.logger.debug("HttpClient::get_parameter_list -> %s (%s)", json.dumps(self.parameter_list[serial], indent=4), self.log_account)

    async def refresh_device(self, id) -> None:
        data = {"messages": {str(id): {"REFRESH": 0}}}
        return await self._control_multiple(data)

    async def rstat_all_device(self, id) -> None:
        data = {"messages": {str(id): {"RSTAT": "ALL"}}}
        return await self._control_multiple(data)

    async def get_table_data(self, id, tableStartIndex, tableSubIndex) -> None:
        params = {"PRD " + str(tableStartIndex): "VAL", "PRD " + str(tableStartIndex + tableSubIndex): "ALV"}
        data = {"parameters": params}
        return await self._control_advanced(id, data)

    def get_table_data_all(self, id, tableStartIndex, tableSize):
        tasks = []
        for i in range(1, tableSize + 1):
            tasks.append(self.get_table_data(id, tableStartIndex, i))
        return tasks

    async def turn_device_by_id(self, id, on):
        cmd_value = 1 if on else 0
        data = {"cmd-name": "CMD", "cmd-value": cmd_value}
        return await self._control(id, data)

    async def turn_device_circuit(self, id, circuit, on):
        cmd_name = "PWR " + str(circuit)
        cmd_value = 1 if on else 0
        data = {"messages": {str(id): {cmd_name: cmd_value}}}
        return await self._control_multiple(data)
