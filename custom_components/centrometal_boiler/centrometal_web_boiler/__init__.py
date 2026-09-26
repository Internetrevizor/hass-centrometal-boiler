"""Framework-agnostic Centrometal web-boiler client.

Nothing in this package imports Home Assistant. Everything that needs the
framework (entities, config entries, event-loop helpers) lives in the parent
package. What the framework layer needs from here is re-exported below and
listed in ``__all__`` so the re-exports survive a stricter lint config.
"""

from .backoff import next_retry_delay
from .const import (
    WEB_BOILER_STOMP_DEVICE_TOPIC,
    WEB_BOILER_STOMP_LOGIN_PASSCODE,
    WEB_BOILER_STOMP_LOGIN_USERNAME,
    WEB_BOILER_STOMP_URL,
    WEB_BOILER_WEBROOT,
)
from .HttpClient import HttpClient, HttpClientAuthError, HttpClientConnectionError
from .HttpHelper import HttpHelper, HttpHelperLookupError
from .logging_utils import redact_account
from .WebBoilerClient import WebBoilerClient
from .WebBoilerDeviceCollection import DeviceLookupError, WebBoilerDeviceCollection
from .WebBoilerWsClient import WebBoilerWsClient

__all__ = [
    "WEB_BOILER_STOMP_DEVICE_TOPIC",
    "WEB_BOILER_STOMP_LOGIN_PASSCODE",
    "WEB_BOILER_STOMP_LOGIN_USERNAME",
    "WEB_BOILER_STOMP_URL",
    "WEB_BOILER_WEBROOT",
    "DeviceLookupError",
    "HttpClient",
    "HttpClientAuthError",
    "HttpClientConnectionError",
    "HttpHelper",
    "HttpHelperLookupError",
    "WebBoilerClient",
    "WebBoilerDeviceCollection",
    "WebBoilerWsClient",
    "next_retry_delay",
    "redact_account",
]
