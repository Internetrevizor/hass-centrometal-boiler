"""A local imitation of web-boiler.com: the website and the STOMP broker.

Only what the integration's client relies on is reproduced, with the shapes of
the real payloads. Idea and structure follow the AndroFlo fork's tests_ha
(https://github.com/AndroFlo/hass-centrometal-boiler), adapted to this
integration's own client.
"""

from __future__ import annotations

import asyncio
import json

from aiohttp import web
from websockets.asyncio.server import serve

EMAIL = "user@example.com"
PASSWORD = "secret"
CSRF = "csrf-123"


def boiler(device_id: int, serial: str, device_type: str, product: str, params: dict, settings=()) -> dict:
    """One installation of the account and its current parameter values."""
    return {
        "installation": {
            "value": device_id,
            "label": serial,
            "place": "Boiler room",
            "address": "Example Street 1",
            "type": device_type,
            "product": product,
        },
        "params": dict(params),
        "parameter_list": {
            "city": "Example City",
            "parameters": [{"group": "Temperatures", "list": list(settings)}] if settings else [],
        },
    }


# The maintainer's boiler: PelTec II Lambda on hydraulic scheme 43 (buffer +
# DHW on K1), with one editable setting (slot 67, buffer tank temperature).
PELTEC2 = boiler(
    1001,
    "PT2SERIAL",
    "peltec2",
    "PelTec II Lambda",
    {
        "B_STATE": "OFF",
        "B_KONF": "42",
        "B_VER": "v3.03dL",
        "B_PRODNAME": "PelTec II Lambda",
        "B_sng": "36",
        "B_Tk1": "61.5",
        "B_P1": "0",
        "B_P2": "0",
        "B_P3": "0",
        "B_P4": "0",
        "K1B_P": "0",
        "K1B_onOff": "1",
        "B_bup": "0",
        "B_PTV_PRI": "1",
        "PVAL_67_0": "66",
        "PDEF_67_0": "65",
        "PMIN_67_0": "40",
        "PMAX_67_0": "85",
    },
    settings=[
        {
            "dbindex": 67,
            "naslov": "Buffer tank temperature",
            "tip": "temperatura",
            "user": "rw",
            "showButton": True,
            "sufix": "°C",
        }
    ],
)

# A BioTec-Plus whose pellet tank values have not been reported yet.
BIOTEC_PLUS = boiler(
    4242,
    "BIOSERIAL",
    "biopl",
    "BioTec-Plus",
    {"B_STATE": "ON", "B_pbs": "0", "B_Tk1": "65"},
)


class FakeWebsite:
    """aiohttp application recording the commands it receives."""

    def __init__(self, boilers: list[dict]) -> None:
        self.boilers = boilers
        self.commands: list[tuple[str, dict]] = []
        self.command_status = "success"
        self.down = False  # every page answers 503, like during a Centrometal outage
        self.session_expired = False  # JSON endpoints answer with the login page
        self.url = ""
        app = web.Application()
        app.router.add_get("/login", self.login_page)
        app.router.add_post("/login_check", self.login_check)
        app.router.add_post("/data/autocomplete/installation", self.installations)
        app.router.add_post("/wdata/data/installation-status-all", self.statuses)
        app.router.add_post("/wdata/data/parameter-list/{serial}", self.parameter_list)
        app.router.add_post("/wdata/data/multi/errors-list/{id}", self.errors_list)
        app.router.add_post("/api/inst/control/multiple", self.control)
        app.router.add_post("/api/inst/control/{id}", self.control)
        self.app = app

    def _unavailable(self) -> web.Response | None:
        if self.down:
            return web.Response(status=503, text="maintenance")
        if self.session_expired:
            return web.Response(text='<html><form action="/login_check" method="post"></form></html>')
        return None

    async def login_page(self, request: web.Request) -> web.Response:
        if self.down:
            return web.Response(status=503, text="maintenance")
        return web.Response(
            text=f'<html><form action="/login_check"><input type="hidden" name="_csrf_token" value="{CSRF}">'
            "</form></html>",
            content_type="text/html",
        )

    async def login_check(self, request: web.Request) -> web.Response:
        if self.down:
            return web.Response(status=503, text="maintenance")
        form = await request.post()
        ok = form.get("_username") == EMAIL and form.get("_password") == PASSWORD and form.get("_csrf_token") == CSRF
        if ok:
            self.session_expired = False
            body = '<div id="id-loading-screen-blackout"></div>'
        else:
            body = '<form action="/login_check" method="post"></form>'
        return web.Response(text=f"<html><body>{body}</body></html>", content_type="text/html")

    async def installations(self, request: web.Request) -> web.Response:
        if (blocked := self._unavailable()) is not None:
            return blocked
        return web.json_response({"installations": [b["installation"] for b in self.boilers]})

    async def statuses(self, request: web.Request) -> web.Response:
        if (blocked := self._unavailable()) is not None:
            return blocked
        return web.json_response(
            {
                str(b["installation"]["value"]): {
                    "installation": {"country": "Example", "countryCode": "XX"},
                    "params": {name: {"v": value, "ut": "2026-10-22 10:00:00"} for name, value in b["params"].items()},
                }
                for b in self.boilers
            }
        )

    async def parameter_list(self, request: web.Request) -> web.Response:
        if (blocked := self._unavailable()) is not None:
            return blocked
        serial = request.match_info["serial"]
        for b in self.boilers:
            if b["installation"]["label"] == serial:
                return web.json_response(b["parameter_list"])
        return web.Response(status=404)

    async def errors_list(self, request: web.Request) -> web.Response:
        if (blocked := self._unavailable()) is not None:
            return blocked
        return web.json_response({"cols": [{"id": "description"}], "rows": []})

    async def control(self, request: web.Request) -> web.Response:
        if (blocked := self._unavailable()) is not None:
            return blocked
        self.commands.append((request.path, await request.json()))
        return web.json_response({"status": self.command_status})

    def commands_to(self, device_id: int) -> list[dict]:
        return [payload for path, payload in self.commands if path == f"/api/inst/control/{device_id}"]


class FakeBroker:
    """Minimal STOMP broker: CONNECT, SUBSCRIBE, and pushing MESSAGE frames."""

    def __init__(self) -> None:
        self.connections: list = []
        self.subscriptions: dict[str, tuple] = {}  # destination -> (websocket, subscription id)
        self.server = None
        self.url = ""

    async def start(self) -> str:
        self.server = await serve(self.handler, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{port}/ws"
        return self.url

    async def stop(self) -> None:
        self.server.close()
        await self.server.wait_closed()

    async def handler(self, websocket) -> None:
        self.connections.append(websocket)
        try:
            async for message in websocket:
                for frame in str(message).split("\x00"):
                    frame = frame.lstrip("\n")
                    if not frame:
                        continue
                    lines = frame.split("\n")
                    headers = dict(line.split(":", 1) for line in lines[1:] if ":" in line)
                    if lines[0] == "CONNECT":
                        await websocket.send("CONNECTED\nversion:1.1\nheart-beat:0,0\n\n\x00")
                    elif lines[0] == "SUBSCRIBE":
                        self.subscriptions[headers["destination"]] = (websocket, headers["id"])
        except Exception:
            pass  # connection dropped by drop_connections()

    async def publish(self, device_type: str, serial: str, values: dict) -> None:
        """Push a realtime update, as the controller does when a value changes."""
        destination = f"/topic/cm.inst.{device_type}.{serial}"
        websocket, subscription = self.subscriptions[destination]
        await websocket.send(
            f"MESSAGE\nsubscription:{subscription}\ndestination:{destination}\n"
            f"content-type:application/json\n\n{json.dumps(values)}\x00"
        )

    async def drop_connections(self) -> None:
        for websocket in list(self.connections):
            await websocket.close(code=1011, reason="broker restart")
        self.connections.clear()
        self.subscriptions.clear()


async def wait_until(condition, seconds: float = 5.0) -> None:
    """Wait for a Home Assistant state to change; there is no event to await on."""
    async with asyncio.timeout(seconds):
        while not condition():  # noqa: ASYNC110 - polling HA state is the point
            await asyncio.sleep(0.05)
