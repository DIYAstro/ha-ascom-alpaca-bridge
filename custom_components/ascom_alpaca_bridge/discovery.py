"""Discovery of Alpaca servers using UDP broadcast."""
import asyncio
import json
import logging
import socket

from .const import DISCOVERY_PORT

LOGGER = logging.getLogger(__package__)

DISCOVERY_MSG = b"alpacadiscovery1"

class AlpacaDiscoveryProtocol(asyncio.DatagramProtocol):
    """Protocol for ASCOM Alpaca discovery."""

    def __init__(self, responses):
        """Initialize."""
        self.responses = responses

    def datagram_received(self, data, addr):
        """Handle received datagram."""
        try:
            msg = data.decode("utf-8")
            if "AlpacaPort" in msg:
                payload = json.loads(msg)
                ip = addr[0]
                port = payload.get("AlpacaPort")
                if port:
                    self.responses.append({"host": ip, "port": port})
        except Exception as err:
            LOGGER.debug("Error parsing discovery response from %s: %s", addr, err)

async def async_discover_alpaca_servers(timeout: int = 3) -> list:
    """Discover ASCOM Alpaca servers on the local network."""
    loop = asyncio.get_running_loop()
    responses = []

    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setblocking(False)

    try:
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: AlpacaDiscoveryProtocol(responses),
            sock=sock
        )
        
        # Send broadcast to standard discovery port
        transport.sendto(DISCOVERY_MSG, ("255.255.255.255", DISCOVERY_PORT))
        
        # Wait for responses
        await asyncio.sleep(timeout)
        
    except Exception as err:
        LOGGER.error("Discovery failed: %s", err)
    finally:
        if 'transport' in locals():
            transport.close()
            sock.close()

    # Deduplicate by host:port
    unique_responses = []
    seen = set()
    for r in responses:
        key = f"{r['host']}:{r['port']}"
        if key not in seen:
            seen.add(key)
            unique_responses.append(r)
            
    return unique_responses
