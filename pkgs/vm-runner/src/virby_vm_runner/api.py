"""Vfkit API Client."""

import asyncio
import logging
import random
from functools import wraps
from json import JSONDecodeError

import httpx

from .exceptions import VMRuntimeError

logging.getLogger("httpcore.connection").setLevel(logging.ERROR)
logging.getLogger("httpcore.http11").setLevel(logging.ERROR)


class VirtualMachineState:
    """Enumeration of virtual machine states returned by vfkit's RESTful API."""

    RUNNING = "VirtualMachineStateRunning"
    STOPPED = "VirtualMachineStateStopped"
    PAUSED = "VirtualMachineStatePaused"
    ERROR = "VirtualMachineStateError"
    STARTING = "VirtualMachineStateStarting"
    PAUSING = "VirtualMachineStatePausing"
    RESUMING = "VirtualMachineStateResuming"
    STOPPING = "VirtualMachineStateStopping"
    SAVING = "VirtualMachineStateSaving"
    RESTORING = "VirtualMachineStateRestoring"


def retry_on_failure(max_retries=3, base_delay=0.1):
    """Decorator to retry operations with exponential backoff."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except (httpx.ConnectError, httpx.TimeoutException):
                    if attempt == max_retries:
                        raise
                    delay = base_delay * (2**attempt) + random.uniform(0, 0.1)
                    await asyncio.sleep(delay)
            return None

        return wrapper

    return decorator


class VfkitAPIClient:
    """Client for interacting with vfkit's RESTful API."""

    def __init__(self, api_port: int, is_running_check: callable = None):
        """Initialize the vfkit API client.

        Args:
            api_port: Port number where the vfkit API is running
            is_running_check: Optional callable that returns True if VM is running
        """
        self._vfkit_api_port = api_port
        self._is_running_check = is_running_check
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with connection pooling."""
        if self._client is None:
            async with self._client_lock:
                if self._client is None:  # Double-check locking
                    self._client = httpx.AsyncClient(
                        timeout=httpx.Timeout(5.0, connect=2.0),
                        limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
                        http2=False,  # Disable HTTP/2 for simplicity
                    )
        return self._client

    async def close(self):
        """Close HTTP client and cleanup resources."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def get(self, endpoint: str) -> dict:
        """Make a GET request to vfkit's RESTful API.

        Args:
            endpoint: API endpoint to call

        Returns:
            dict | None: JSON response from the API, or None if no content
        """
        return await self._call_api(endpoint, "GET")

    async def post(self, endpoint: str, data: dict | None = None) -> dict:
        """Make a POST request to vfkit's RESTful API.

        Args:
            endpoint: API endpoint to call
            data: JSON data to send in the request

        Returns:
            dict | None: JSON response from the API, or None if no content
        """
        return await self._call_api(endpoint, "POST", data)

    @retry_on_failure(max_retries=2, base_delay=0.1)
    async def _call_api(self, endpoint: str, method: str = "GET", data: dict | None = None) -> dict:
        """Make a request to vfkit's RESTful API.

        Args:
            endpoint: API endpoint to call
            method: HTTP method to use (default: GET)
            data: JSON data to send in the request (default: None)

        Returns:
            dict | None: JSON response from the API, or None if no content
        """
        if self._is_running_check and not self._is_running_check():
            raise VMRuntimeError("Cannot make API request: VM is not running")

        url = f"http://localhost:{self._vfkit_api_port}{endpoint}"

        try:
            client = await self._get_client()
            response = await client.request(method, url, json=data)
            response.raise_for_status()

            if response.content:
                try:
                    return response.json()
                except (ValueError, JSONDecodeError):
                    return None
            return None

        except httpx.HTTPError as e:
            raise VMRuntimeError(f"vfkit API request failed: {e}")
        except Exception as e:
            raise VMRuntimeError(f"Unexpected error in vfkit API request: {e}")
