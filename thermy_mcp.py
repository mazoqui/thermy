#!/usr/bin/env python3
"""
Thermal Printer MCP Server
Exposes thermal printer functionality as MCP tools for AI agents.
"""

import asyncio
import os
import sys

from mcp.server.fastmcp import FastMCP

from thermy import ThermalPrinter, check_requirements

mcp = FastMCP("thermy")

# Module-level state
_printer = ThermalPrinter()
_lock = asyncio.Lock()
_idle_task: asyncio.Task | None = None
_idle_timeout = 300  # 5 minutes


def _reset_idle_timer():
    """Reset the idle disconnect timer."""
    global _idle_task
    if _idle_task and not _idle_task.done():
        _idle_task.cancel()
    try:
        loop = asyncio.get_running_loop()
        _idle_task = loop.create_task(_idle_disconnect())
    except RuntimeError:
        pass


async def _idle_disconnect():
    """Disconnect printer after idle timeout."""
    await asyncio.sleep(_idle_timeout)
    async with _lock:
        await _printer.disconnect()


async def _ensure_connected(device_address: str | None = None) -> str:
    """Connect if not already connected. Returns status message."""
    if _printer.client and _printer.client.is_connected:
        return "already connected"
    addr = device_address or os.environ.get("THERMY_DEVICE")
    if not addr:
        raise ValueError(
            "No device address. Set THERMY_DEVICE environment variable "
            "or call the connect tool with a device_address."
        )
    await _printer.connect(addr)
    return f"connected to {addr}"


@mcp.tool()
async def scan(timeout: int = 30) -> dict:
    """Scan for available Bluetooth thermal printers nearby.

    Args:
        timeout: Scan duration in seconds (default 30)
    """
    messages = []
    _printer._msg = messages.append
    try:
        async with _lock:
            devices = await _printer.scan_devices(timeout=timeout)
        return {
            "success": True,
            "devices": [{"name": name, "address": addr} for name, addr in devices],
            "output": "\n".join(messages),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "output": "\n".join(messages)}
    finally:
        _printer._msg = lambda msg: None


@mcp.tool()
async def connect(device_address: str | None = None) -> dict:
    """Connect to a thermal printer via Bluetooth.

    Args:
        device_address: Bluetooth address (e.g. AA:BB:CC:DD:EE:FF). Uses THERMY_DEVICE env var if omitted.
    """
    messages = []
    _printer._msg = messages.append
    try:
        async with _lock:
            status = await _ensure_connected(device_address)
        _reset_idle_timer()
        return {"success": True, "message": status, "output": "\n".join(messages)}
    except Exception as e:
        return {"success": False, "error": str(e), "output": "\n".join(messages)}
    finally:
        _printer._msg = lambda msg: None


@mcp.tool()
async def disconnect() -> dict:
    """Disconnect from the thermal printer."""
    messages = []
    _printer._msg = messages.append
    try:
        async with _lock:
            await _printer.disconnect()
        return {"success": True, "message": "disconnected", "output": "\n".join(messages)}
    except Exception as e:
        return {"success": False, "error": str(e), "output": "\n".join(messages)}
    finally:
        _printer._msg = lambda msg: None


@mcp.tool()
async def print_text(
    text: str,
    font_size: int = 16,
    align: str = "center",
    invert: bool = False,
    border: int = 0,
    speed: int = 35,
    energy: int = 8000,
    device_address: str | None = None,
) -> dict:
    """Print text to the thermal printer.

    Args:
        text: Text to print (supports \\n for newlines)
        font_size: Font size in pixels (default 16)
        align: Text alignment - left, center, or right (default center)
        invert: Invert colors for white text on black background
        border: Border frame thickness 0-10 pixels (default 0, no border)
        speed: Print speed 10-90, lower is better quality (default 35)
        energy: Thermal energy level (default 8000)
        device_address: Bluetooth address to auto-connect to if not connected
    """
    messages = []
    _printer._msg = messages.append
    try:
        async with _lock:
            conn_status = await _ensure_connected(device_address)
            messages.append(conn_status)
            await _printer.print_text(text, font_size, speed, energy, align, invert, border)
        _reset_idle_timer()
        return {"success": True, "message": "Text printed successfully", "output": "\n".join(messages)}
    except Exception as e:
        return {"success": False, "error": str(e), "output": "\n".join(messages)}
    finally:
        _printer._msg = lambda msg: None


@mcp.tool()
async def print_image(
    image_path: str,
    speed: int = 45,
    energy: int = 8000,
    device_address: str | None = None,
) -> dict:
    """Print an image file to the thermal printer.

    Args:
        image_path: Path to image file (PNG, JPG, etc.)
        speed: Print speed 10-90, lower is better quality (default 45)
        energy: Thermal energy level (default 8000)
        device_address: Bluetooth address to auto-connect to if not connected
    """
    messages = []
    _printer._msg = messages.append
    try:
        async with _lock:
            conn_status = await _ensure_connected(device_address)
            messages.append(conn_status)
            await _printer.print_image(image_path, speed, energy)
        _reset_idle_timer()
        return {"success": True, "message": "Image printed successfully", "output": "\n".join(messages)}
    except Exception as e:
        return {"success": False, "error": str(e), "output": "\n".join(messages)}
    finally:
        _printer._msg = lambda msg: None


@mcp.tool()
async def print_qr(
    data: str,
    speed: int = 45,
    energy: int = 8000,
    device_address: str | None = None,
) -> dict:
    """Generate and print a QR code to the thermal printer.

    Args:
        data: Text or URL to encode as a QR code
        speed: Print speed 10-90, lower is better quality (default 45)
        energy: Thermal energy level (default 8000)
        device_address: Bluetooth address to auto-connect to if not connected
    """
    messages = []
    _printer._msg = messages.append
    try:
        async with _lock:
            conn_status = await _ensure_connected(device_address)
            messages.append(conn_status)
            await _printer.print_qr(data, speed, energy)
        _reset_idle_timer()
        return {"success": True, "message": "QR code printed successfully", "output": "\n".join(messages)}
    except Exception as e:
        return {"success": False, "error": str(e), "output": "\n".join(messages)}
    finally:
        _printer._msg = lambda msg: None


if __name__ == "__main__":
    mcp.run()
