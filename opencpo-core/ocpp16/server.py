"""
OCPP 1.6j WebSocket Server.

Accepts charger connections, routes messages to handler.
"""
import asyncio
import logging
from typing import Callable

import websockets
from websockets.asyncio.server import ServerConnection

from config import config
from security.charger_auth import authenticate_upgrade, cp_id_from_path

logger = logging.getLogger(__name__)


class OCPP16Server:
    """OCPP 1.6j WebSocket server."""

    def __init__(self, on_connect: Callable, on_disconnect: Callable):
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._connections: dict[str, ServerConnection] = {}
        self._server = None

    async def serve(self, host: str | None = None, port: int | None = None) -> None:
        """Start the WebSocket server (host/port default to the configuration)."""
        self._server = await websockets.serve(
            self._handler,
            host if host is not None else config.ocpp.ocpp16_host,
            port if port is not None else config.ocpp.ocpp16_port,
            subprotocols=["ocpp1.6"],
            process_request=authenticate_upgrade,   # charger authentication (HTTP 401/403/429)
            ping_interval=None,  # Disable WS pings — use OCPP heartbeats instead (Maxpower doesn't respond to WS pings)
            ping_timeout=None,
            max_size=65536,
            logger=logger,
        )
        logger.info(
            f"OCPP 1.6j server listening on "
            f"ws://{config.ocpp.ocpp16_host}:{config.ocpp.ocpp16_port}"
        )
        await self._server.wait_closed()

    async def _handler(self, websocket: ServerConnection) -> None:
        """Handle a new charger connection."""
        # Extract charge point ID from URL path: /ocpp/CP001 → CP001
        cp_id = cp_id_from_path(websocket.request.path if websocket.request else "")

        # Verify subprotocol
        if websocket.subprotocol != "ocpp1.6":
            logger.warning(f"Rejected {cp_id}: wrong subprotocol {websocket.subprotocol}")
            await websocket.close(1002, "Subprotocol not supported")
            return

        logger.info(f"Charger connected: {cp_id} (OCPP 1.6j)")
        self._connections[cp_id] = websocket

        try:
            # on_connect handles the message loop
            await self._on_connect(cp_id, websocket)

        except websockets.exceptions.ConnectionClosed as e:
            logger.info(f"Charger disconnected: {cp_id} (code={e.code})")
        except Exception as e:
            logger.error(f"Error handling {cp_id}: {e}", exc_info=True)
        finally:
            self._connections.pop(cp_id, None)
            await self._on_disconnect(cp_id)

    async def send_to(self, cp_id: str, message: str) -> bool:
        """Send a message to a specific charge point."""
        ws = self._connections.get(cp_id)
        if ws is None:
            return False
        try:
            await ws.send(message)
            return True
        except Exception:
            return False

    async def disconnect(self, cp_id: str, code: int = 1008, reason: str = "credentials revoked") -> bool:
        """Close a live connection (used when a charger's credentials are revoked)."""
        ws = self._connections.get(cp_id)
        if ws is None:
            return False
        await ws.close(code, reason)
        return True

    def is_connected(self, cp_id: str) -> bool:
        return cp_id in self._connections

    @property
    def connected_count(self) -> int:
        return len(self._connections)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
