#!/usr/bin/env python3
"""
Thermal Printer CLI
Command-line interface for Mini Bluetooth Thermal Printers
"""

import asyncio
import argparse
import os
import sys
from typing import List, Optional, Union
from PIL import Image, ImageDraw, ImageFont
import struct

try:
    from bleak import BleakClient, BleakScanner
    from bleak.exc import BleakDBusError, BleakError
    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False
    BleakClient = None
    BleakScanner = None
    BleakDBusError = Exception
    BleakError = Exception


class CatProtocol:
    """Python implementation of cat-protocol.ts for thermal printer communication"""
    
    # CRC8 lookup table from cat-protocol.ts
    CRC8_TABLE = [
        0x00, 0x07, 0x0e, 0x09, 0x1c, 0x1b, 0x12, 0x15, 0x38, 0x3f, 0x36, 0x31,
        0x24, 0x23, 0x2a, 0x2d, 0x70, 0x77, 0x7e, 0x79, 0x6c, 0x6b, 0x62, 0x65,
        0x48, 0x4f, 0x46, 0x41, 0x54, 0x53, 0x5a, 0x5d, 0xe0, 0xe7, 0xee, 0xe9,
        0xfc, 0xfb, 0xf2, 0xf5, 0xd8, 0xdf, 0xd6, 0xd1, 0xc4, 0xc3, 0xca, 0xcd,
        0x90, 0x97, 0x9e, 0x99, 0x8c, 0x8b, 0x82, 0x85, 0xa8, 0xaf, 0xa6, 0xa1,
        0xb4, 0xb3, 0xba, 0xbd, 0xc7, 0xc0, 0xc9, 0xce, 0xdb, 0xdc, 0xd5, 0xd2,
        0xff, 0xf8, 0xf1, 0xf6, 0xe3, 0xe4, 0xed, 0xea, 0xb7, 0xb0, 0xb9, 0xbe,
        0xab, 0xac, 0xa5, 0xa2, 0x8f, 0x88, 0x81, 0x86, 0x93, 0x94, 0x9d, 0x9a,
        0x27, 0x20, 0x29, 0x2e, 0x3b, 0x3c, 0x35, 0x32, 0x1f, 0x18, 0x11, 0x16,
        0x03, 0x04, 0x0d, 0x0a, 0x57, 0x50, 0x59, 0x5e, 0x4b, 0x4c, 0x45, 0x42,
        0x6f, 0x68, 0x61, 0x66, 0x73, 0x74, 0x7d, 0x7a, 0x89, 0x8e, 0x87, 0x80,
        0x95, 0x92, 0x9b, 0x9c, 0xb1, 0xb6, 0xbf, 0xb8, 0xad, 0xaa, 0xa3, 0xa4,
        0xf9, 0xfe, 0xf7, 0xf0, 0xe5, 0xe2, 0xeb, 0xec, 0xc1, 0xc6, 0xcf, 0xc8,
        0xdd, 0xda, 0xd3, 0xd4, 0x69, 0x6e, 0x67, 0x60, 0x75, 0x72, 0x7b, 0x7c,
        0x51, 0x56, 0x5f, 0x58, 0x4d, 0x4a, 0x43, 0x44, 0x19, 0x1e, 0x17, 0x10,
        0x05, 0x02, 0x0b, 0x0c, 0x21, 0x26, 0x2f, 0x28, 0x3d, 0x3a, 0x33, 0x34,
        0x4e, 0x49, 0x40, 0x47, 0x52, 0x55, 0x5c, 0x5b, 0x76, 0x71, 0x78, 0x7f,
        0x6a, 0x6d, 0x64, 0x63, 0x3e, 0x39, 0x30, 0x37, 0x22, 0x25, 0x2c, 0x2b,
        0x06, 0x01, 0x08, 0x0f, 0x1a, 0x1d, 0x14, 0x13, 0xae, 0xa9, 0xa0, 0xa7,
        0xb2, 0xb5, 0xbc, 0xbb, 0x96, 0x91, 0x98, 0x9f, 0x8a, 0x8d, 0x84, 0x83,
        0xde, 0xd9, 0xd0, 0xd7, 0xc2, 0xc5, 0xcc, 0xcb, 0xe6, 0xe1, 0xe8, 0xef,
        0xfa, 0xfd, 0xf4, 0xf3
    ]
    
    # Command definitions from cat-protocol.ts
    class Command:
        APPLY_ENERGY = 0xbe
        GET_DEVICE_STATE = 0xa3
        GET_DEVICE_INFO = 0xa8
        UPDATE_DEVICE = 0xa9
        SET_DPI = 0xa4
        LATTICE = 0xa6
        RETRACT = 0xa0
        FEED = 0xa1
        SPEED = 0xbd
        ENERGY = 0xaf
        BITMAP = 0xa2
    
    class CommandType:
        TRANSFER = 0
        RESPONSE = 1
    
    class StateFlag:
        OUT_OF_PAPER = 1 << 0
        COVER = 1 << 1
        OVERHEAT = 1 << 2
        LOW_POWER = 1 << 3
        PAUSE = 1 << 4
        BUSY = 0x80
    
    @staticmethod
    def crc8(data: bytes) -> int:
        """Calculate CRC8 checksum using lookup table from cat-protocol.ts"""
        crc = 0
        for byte in data:
            crc = CatProtocol.CRC8_TABLE[(crc ^ byte) & 0xff]
        return crc & 0xff
    
    @staticmethod
    def reverse_bits(i: int) -> int:
        """Reverse bits of a byte (from cat-protocol.ts)"""
        i = ((i & 0b10101010) >> 1) | ((i & 0b01010101) << 1)
        i = ((i & 0b11001100) >> 2) | ((i & 0b00110011) << 2)
        return ((i & 0b11110000) >> 4) | ((i & 0b00001111) << 4)
    
    @staticmethod
    def bytes_from_int(i: int, length: int = 1, big_endian: bool = False) -> bytes:
        """Convert integer to byte array (from cat-protocol.ts)"""
        result = []
        p = 0
        while i != 0 and p < length:
            result.append(i & 0xff)
            i >>= 8
            p += 1
        while len(result) < length:
            result.append(0)
        if big_endian:
            result.reverse()
        return bytes(result)


class CatPrinter:
    """Python implementation of CatPrinter class from cat-protocol.ts"""
    
    def __init__(self, model: str, write_func, dry_run: bool = False):
        self.model = model
        self.write = write_func
        self.dry_run = dry_run
        self.mtu = 200
        self.buffer = bytearray(self.mtu)
        self.buffer_size = 0
        self.state = {
            'out_of_paper': 0,
            'cover': 0,
            'overheat': 0,
            'low_power': 0,
            'pause': 0,
            'busy': 0
        }
        
        # Predefined commands from cat-protocol.ts
        self.pause_cmd = bytes([0x51, 0x78, 0xa3, 0x01, 0x01, 0x00, 0x10, 0x70, 0xff])
        self.resume_cmd = bytes([0x51, 0x78, 0xa3, 0x01, 0x01, 0x00, 0x00, 0x00, 0xff])
    
    def is_new_model(self) -> bool:
        """Check if printer is a new model (GB03 or MX series)"""
        return self.model == 'GB03' or self.model.startswith('MX')
    
    def compress_ok(self) -> bool:
        """Check if compression is supported"""
        return self.is_new_model()
    
    def make(self, command: int, payload: bytes, cmd_type: int = CatProtocol.CommandType.TRANSFER) -> bytes:
        """Make command bytes (from cat-protocol.ts)"""
        payload_len = len(payload)
        return bytes([
            0x51, 0x78, command, cmd_type,
            payload_len & 0xff, payload_len >> 8
        ]) + payload + bytes([CatProtocol.crc8(payload), 0xff])
    
    def pend(self, data: bytes):
        """Add data to buffer"""
        for i in range(len(data)):
            self.buffer[self.buffer_size] = data[i]
            self.buffer_size += 1
    
    async def flush(self):
        """Flush buffer to printer"""
        while self.state['pause']:
            await asyncio.sleep(0.1)
        if self.buffer_size == 0:
            return
        await self.write(bytes(self.buffer[:self.buffer_size]))
        self.buffer_size = 0
        await asyncio.sleep(0.02)
    
    async def send(self, data: bytes):
        """Send data to printer (buffer if needed)"""
        if self.buffer_size + len(data) > self.mtu:
            await self.flush()
        self.pend(data)
    
    async def draw(self, line: bytes):
        """Draw bitmap line"""
        return await self.send(self.make(CatProtocol.Command.BITMAP, line))
    
    async def draw_pbm(self, line: bytes):
        """Draw PBM format line (with bit reversal)"""
        reversed_line = bytes([CatProtocol.reverse_bits(b) for b in line])
        return await self.draw(reversed_line)
    
    async def apply_energy(self):
        """Apply energy command"""
        return await self.send(self.make(CatProtocol.Command.APPLY_ENERGY, CatProtocol.bytes_from_int(0x01)))
    
    async def get_device_state(self):
        """Get device state"""
        return await self.send(self.make(CatProtocol.Command.GET_DEVICE_STATE, CatProtocol.bytes_from_int(0x00)))
    
    async def get_device_info(self):
        """Get device info"""
        return await self.send(self.make(CatProtocol.Command.GET_DEVICE_INFO, CatProtocol.bytes_from_int(0x00)))
    
    async def update_device(self):
        """Update device"""
        return await self.send(self.make(CatProtocol.Command.UPDATE_DEVICE, CatProtocol.bytes_from_int(0x00)))
    
    async def set_dpi(self, dpi: int = 200):
        """Set DPI"""
        return await self.send(self.make(CatProtocol.Command.SET_DPI, CatProtocol.bytes_from_int(50)))
    
    async def start_lattice(self):
        """Start lattice"""
        payload = bytes([0xaa, 0x55, 0x17, 0x38, 0x44, 0x5f, 0x5f, 0x5f, 0x44, 0x38, 0x2c])
        return await self.send(self.make(CatProtocol.Command.LATTICE, payload))
    
    async def end_lattice(self):
        """End lattice"""
        payload = bytes([0xaa, 0x55, 0x17, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x17])
        return await self.send(self.make(CatProtocol.Command.LATTICE, payload))
    
    async def retract(self, points: int):
        """Retract paper"""
        return await self.send(self.make(CatProtocol.Command.RETRACT, CatProtocol.bytes_from_int(points, 2)))
    
    async def feed(self, points: int):
        """Feed paper"""
        return await self.send(self.make(CatProtocol.Command.FEED, CatProtocol.bytes_from_int(points, 2)))
    
    async def set_speed(self, value: int):
        """Set print speed"""
        return await self.send(self.make(CatProtocol.Command.SPEED, CatProtocol.bytes_from_int(value)))
    
    async def set_energy(self, value: int):
        """Set energy level"""
        return await self.send(self.make(CatProtocol.Command.ENERGY, CatProtocol.bytes_from_int(value, 2)))
    
    async def prepare_camera(self):
        """Prepare camera (for certain models)"""
        cmd = bytes([0x51, 0x78, 0xbc, 0x00, 0x01, 0x02, 0x01, 0x2d, 0xff])
        return await self.send(cmd)
    
    async def prepare(self, speed: int, energy: int):
        """Prepare printer for printing"""
        await self.flush()
        await self.get_device_state()
        await self.prepare_camera()
        await self.set_dpi()
        await self.set_speed(speed)
        await self.set_energy(energy)
        await self.apply_energy()
        await self.update_device()
        await self.start_lattice()
        await self.flush()
    
    async def finish(self, extra_feed: int):
        """Finish printing"""
        await self.flush()
        await self.end_lattice()
        await self.set_speed(8)
        await self.feed(extra_feed)
        await self.get_device_state()
        await self.flush()


class ThermalPrinterCLI:
    """Main CLI class combining cat-protocol with thermal_printer.py Bluetooth handling"""
    
    # Bluetooth service and characteristic UUIDs from thermal_printer.py
    WRITE_UUID_GUIDS = [
        "0000AE01-0000-1000-8000-00805F9B34FB",
        "0000FF02-0000-1000-8000-00805F9B34FB", 
        "0000AB01-0000-1000-8000-00805F9B34FB"
    ]
    
    SERVICE_UUID_GUIDS = [
        "0000AE00-0000-1000-8000-00805F9B34FB",
        "0000FF00-0000-1000-8000-00805F9B34FB",
        "0000AB00-0000-1000-8000-00805F9B34FB"
    ]
    
    # Supported printer models (from thermal_printer.py)
    SUPPORTED_PRINTERS = [
        "XW001", "XW002", "XW003", "XW004", "XW005", "XW006", "XW007", "XW008", "XW009",
        "JX001", "JX002", "JX003", "JX004", "JX005", "JX006", 
        "M01", "PR07", "PR02", 
        "GB01", "GB02", "GB03", "GB04", 
        "LY01", "LY02", "LY03", "LY10", 
        "AI01", "GT01", "MX10"
    ]
    
    def __init__(self):
        self.client: Optional[BleakClient] = None
        self.write_characteristic = None
        self.printer: Optional[CatPrinter] = None
        self.paper_width = 384  # Default paper width in pixels
        
    async def scan_devices(self, timeout: int = 30) -> List[tuple]:
        """Scan for compatible thermal printers (from thermal_printer.py)"""
        if not BLEAK_AVAILABLE:
            print("Error: Bluetooth support not available. Install with: pip install bleak")
            return []
        
        print("Scanning for thermal printers...")
        
        try:
            devices = await BleakScanner.discover(timeout=timeout)
            
            compatible_devices = []
            for device in devices:
                if device.name and any(printer in device.name for printer in self.SUPPORTED_PRINTERS):
                    compatible_devices.append((device.name, device.address))
                    print(f"Found compatible printer: {device.name} ({device.address})")
            
            if not compatible_devices:
                print("No compatible thermal printers found.")
                print("Make sure your printer is powered on and in pairing mode.")
            
            return compatible_devices
            
        except Exception as e:
            print(f"Bluetooth scan error: {e}")
            return []
    
    async def connect(self, device_address: str) -> bool:
        """Connect to thermal printer (from thermal_printer.py)"""
        if not BLEAK_AVAILABLE:
            print("Error: Bluetooth support not available.")
            return False
            
        print(f"Connecting to {device_address}...")
        
        try:
            self.client = BleakClient(device_address, timeout=10)
            await self.client.connect()
            
            if self.client.is_connected:
                print(f"Connected to printer at {device_address}")
                await self._find_write_characteristic()
                
                # Initialize CatPrinter with write function
                self.printer = CatPrinter("GB01", self._write_to_characteristic)
                return True
            else:
                print(f"Failed to connect to {device_address}")
                return False
                        
        except Exception as e:
            print(f"Connection error: {e}")
            return False
    
    async def _find_write_characteristic(self):
        """Find the correct write characteristic (from thermal_printer.py)"""
        services = self.client.services
        
        for service in services:
            for char in service.characteristics:
                if char.uuid.upper() in [uuid.upper() for uuid in self.WRITE_UUID_GUIDS]:
                    try:
                        # Test the characteristic
                        test_cmd = bytes([0x51, 0x78, 0xa8, 0x00, 0x01, 0x00, 0x00, 0x00, 0xff])
                        await self.client.write_gatt_char(char, test_cmd)
                        self.write_characteristic = char
                        print(f"Found write characteristic: {char.uuid}")
                        return
                    except:
                        continue
        
        if not self.write_characteristic:
            print("Warning: Could not find specific write characteristic, using default")
    
    async def _write_to_characteristic(self, data: bytes) -> None:
        """Write data to printer characteristic"""
        if not self.client or not self.client.is_connected:
            raise Exception("Printer not connected")
        
        try:
            if self.write_characteristic:
                await self.client.write_gatt_char(self.write_characteristic, data)
            else:
                # Fallback: try to write to any writable characteristic
                services = self.client.services
                for service in services:
                    for char in service.characteristics:
                        if "write" in char.properties:
                            await self.client.write_gatt_char(char, data)
                            break
            
            await asyncio.sleep(0.01)
            
        except Exception as e:
            print(f"Write error: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from printer"""
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            print("Disconnected from printer")
    
    def text_to_bitmap(self, text: str, font_size: int = 16, align: str = 'center', invert: bool = False, border: int = 0) -> Image.Image:
        """Convert text to bitmap image matching web app behavior"""
        margin = 10
        
        # Try to load a font (prefer sans-serif like web app)
        try:
            # Try DejaVu Sans (similar to web default sans-serif)
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
        except:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", font_size)
            except:
                try:
                    font = ImageFont.truetype("/System/Library/Fonts/Monaco.ttf", font_size)
                except:
                    font = ImageFont.load_default()
        
        # Calculate text dimensions (handle multiline properly)
        lines = text.split('\n')
        max_width = 0
        line_heights = []
        
        temp_img = Image.new('RGBA', (1, 1), (255, 255, 255, 255))
        temp_draw = ImageDraw.Draw(temp_img)
        
        # Calculate proper line spacing based on font size
        line_spacing = max(font_size // 4, 4)  # 25% of font size, minimum 4 pixels
        
        for line in lines:
            # Handle empty lines
            if not line.strip():
                line_heights.append(font_size)
                continue
                
            bbox = temp_draw.textbbox((0, 0), line, font=font)
            line_width = bbox[2] - bbox[0]
            line_height = bbox[3] - bbox[1]
            max_width = max(max_width, line_width)
            line_heights.append(max(line_height, font_size // 2))  # Minimum height
        
        # Calculate total height with proper spacing
        total_height = sum(line_heights) + (len(lines) - 1) * line_spacing
        
        print(f"Multiline text: {len(lines)} lines, max_width={max_width}, total_height={total_height}")
        
        # Add border space to dimensions
        border_margin = border * 2 if border > 0 else 0  # Border on all sides
        top_border_padding = max(border + 6, 10) if border > 0 else 0  # Extra padding at top for border visibility
        text_top_padding = border * 2 if border > 0 else 0  # Additional space between top border and text
        
        # Create bitmap with exact paper width
        img_width = self.paper_width
        img_height = max(total_height + 2 * margin + border_margin + top_border_padding + text_top_padding, 50)  # Minimum height
        
        if border > 0:
            print(f"Adding border: width={border}px, top_padding={top_border_padding}px")
        
        # Choose colors based on invert setting
        if invert:
            bg_color = (0, 0, 0, 255)      # Black background
            text_color = (255, 255, 255, 255)  # White text
            border_color = (255, 255, 255, 255)  # White border
            print("Using inverted colors: white text on black background")
        else:
            bg_color = (255, 255, 255, 255)    # White background
            text_color = (0, 0, 0, 255)        # Black text
            border_color = (0, 0, 0, 255)     # Black border
            print("Using normal colors: black text on white background")
        
        # Create RGBA image (like web app canvas)
        img = Image.new('RGBA', (img_width, img_height), bg_color)
        draw = ImageDraw.Draw(img)
        
        # Calculate text alignment
        print(f"Text alignment: {align}")
        
        def get_line_x_position(line_width):
            # Account for border when calculating positions
            effective_margin = margin + border
            
            if align == 'left':
                return effective_margin
            elif align == 'right':
                return img_width - effective_margin - line_width
            else:  # center (default)
                return (img_width - line_width) // 2
        
        # Draw border if requested (simple approach)
        if border > 0:
            # Draw border lines directly on the main image
            # Top border - positioned with extra padding
            top_y = top_border_padding
            draw.rectangle([0, top_y, img_width-1, top_y + border - 1], fill=border_color)
            
            # Bottom border
            bottom_y = img_height - border
            draw.rectangle([0, bottom_y, img_width-1, img_height-1], fill=border_color)
            
            # Left border
            draw.rectangle([0, top_y, border-1, img_height-1], fill=border_color)
            
            # Right border
            draw.rectangle([img_width-border, top_y, img_width-1, img_height-1], fill=border_color)
            
            print(f"Drew border: top_y={top_y}, bottom_y={bottom_y}, border_width={border}")
        
        # Add extra padding between border and text for better visual balance
        text_top_padding = border * 2 if border > 0 else 0  # Additional space between top border and text
        y_offset = margin + border + top_border_padding + text_top_padding
        for i, line in enumerate(lines):
            if line.strip():  # Only draw non-empty lines
                # Calculate line width for this specific line
                bbox = draw.textbbox((0, 0), line, font=font)
                line_width = bbox[2] - bbox[0]
                
                # Get x position based on alignment
                line_x = get_line_x_position(line_width)
                
                draw.text((line_x, y_offset), line, fill=text_color, font=font)
                print(f"Line {i+1}: '{line}' at x={line_x}, y={y_offset} (width={line_width})")
            else:
                print(f"Line {i+1}: empty line at y={y_offset}")
            
            # Move to next line with proper spacing
            y_offset += line_heights[i] + line_spacing
        
        print(f"Created text bitmap: {img_width}x{img_height}, font_size={font_size}")
        
        # Save debug image
        try:
            debug_path = '/tmp/debug_text_original.png'
            img.save(debug_path)
            print(f"Debug: Saved original text bitmap to {debug_path}")
        except Exception as e:
            print(f"Debug: Failed to save original bitmap: {e}")
        
        return img
    
    def image_to_bitmap(self, image_path: str) -> Image.Image:
        """Load and process image file - convert to BMP-like format since BMP printing works"""
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")
        
        img = Image.open(image_path)
        
        # Convert to RGB first to eliminate transparency (like BMP format)
        if img.mode in ('RGBA', 'LA') or 'transparency' in img.info:
            # Create white background for transparent images
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'RGBA':
                background.paste(img, mask=img.split()[-1])  # Use alpha channel as mask
            else:
                background.paste(img)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        print(f"Converted image to RGB (no transparency): {img.width}x{img.height}")
        
        # Resize to fit paper width while maintaining aspect ratio
        if img.width > self.paper_width:
            height = int(img.height * (self.paper_width / img.width))
            img = img.resize((self.paper_width, height))
        elif img.width < self.paper_width // 2:
            # Scale up small images
            scale = self.paper_width // img.width
            width = img.width * scale
            height = img.height * scale
            img = img.resize((width, height), resample=Image.NEAREST)
        
        # Center image if narrower than paper
        if img.width < self.paper_width:
            pad_amount = (self.paper_width - img.width) // 2
            padded_image = Image.new("RGB", (self.paper_width, img.height), (255, 255, 255))
            padded_image.paste(img, box=(pad_amount, 0))
            img = padded_image
        
        print(f"Final image size: {img.width}x{img.height}")
        
        # Convert to RGBA for consistency with bitmap processing
        img = img.convert('RGBA')
        
        return img
    
    def rgba_to_bits(self, rgba_data: bytes, width: int, height: int) -> bytes:
        """Convert RGBA data to printer bits using web app algorithm"""
        # Convert bytes to 32-bit integers (RGBA pixels)
        rgba_array = []
        for i in range(0, len(rgba_data), 4):
            # Little endian: R, G, B, A -> RGBA
            r, g, b, a = rgba_data[i:i+4]
            rgba_int = r | (g << 8) | (b << 16) | (a << 24)
            rgba_array.append(rgba_int)
        
        # Exact implementation of rgbaToBits from Preview.tsx
        length = len(rgba_array) // 8
        result = bytearray(length)
        
        i = 0
        for p in range(length):
            result[p] = 0
            for d in range(8):
                if i < len(rgba_array):
                    # Extract pixel value and apply mask (first 8 bits)
                    pixel_val = rgba_array[i] & 0xff
                    # Set bit if pixel is dark (text should print, background shouldn't)
                    if pixel_val < 128:  # Dark pixel = print this bit
                        result[p] |= (1 << d)
                i += 1
            # Don't invert - the web app inversion might be for different printer behavior
            # result[p] ^= 0b11111111
        
        return bytes(result)
    
    def apply_threshold_dither(self, img_data: bytes, width: int, height: int) -> bytes:
        """Apply threshold dithering like web app for text"""
        result = bytearray(len(img_data))
        for i in range(0, len(img_data), 4):
            # Convert RGBA to grayscale
            r, g, b, a = img_data[i:i+4]
            # Standard grayscale conversion
            gray = int(r * 0.2125 + g * 0.7154 + b * 0.0721)
            # Threshold dithering: > 128 = white, <= 128 = black
            gray = 255 if gray > 128 else 0
            # Set RGBA values
            result[i:i+4] = [gray, gray, gray, a]
        return bytes(result)
    
    def apply_floyd_steinberg_dither(self, img_data: bytes, width: int, height: int) -> bytes:
        """Apply Floyd-Steinberg dithering exactly like web app ditherSteinberg function"""
        # Convert RGBA to grayscale first (matching web app's rgbaToGray with alpha_as_white=true)
        mono = []
        for i in range(0, len(img_data), 4):
            r, g, b, a = img_data[i:i+4]
            
            # Handle transparency like web app (alpha_as_white=true)
            alpha = a / 255.0  # Normalize alpha to 0-1
            if alpha < 1.0:  # Transparent pixel
                # Make transparent areas white (web app logic)
                alpha_inv = 1.0 - alpha
                r += (255 - r) * alpha_inv
                g += (255 - g) * alpha_inv  
                b += (255 - b) * alpha_inv
            else:
                # Apply alpha blending for semi-transparent
                r *= alpha
                g *= alpha
                b *= alpha
            
            # Standard grayscale conversion (same as web app)
            gray = r * 0.2125 + g * 0.7154 + b * 0.0721
            mono.append(gray)
        
        # Apply Floyd-Steinberg dithering (exact algorithm from image_worker.js lines 41-56)
        p = 0
        for j in range(height):
            for i in range(width):
                m = mono[p]
                n = 255 if m > 128 else 0  # Threshold at 128 like web app
                o = m - n  # Error
                mono[p] = n
                
                # Distribute error to neighboring pixels (exact same conditions as web app)
                if i >= 0 and i < width - 1 and j >= 0 and j < height:
                    mono[p + 1] += o * 7 / 16
                if i >= 1 and i < width and j >= 0 and j < height - 1:
                    mono[p + width - 1] += o * 3 / 16
                if i >= 0 and i < width and j >= 0 and j < height - 1:
                    mono[p + width] += o * 5 / 16
                if i >= 0 and i < width - 1 and j >= 0 and j < height - 1:
                    mono[p + width + 1] += o * 1 / 16
                p += 1
        
        # Convert back to RGBA
        result = bytearray(len(img_data))
        for i in range(len(mono)):
            gray = int(max(0, min(255, mono[i])))
            rgba_idx = i * 4
            result[rgba_idx:rgba_idx+4] = [gray, gray, gray, 255]
        
        return bytes(result)
    
    def bitmap_to_print_data(self, img: Image.Image, is_image: bool = False) -> List[bytes]:
        """Convert bitmap to printer data lines using web app method"""
        # Ensure image is exactly paper width
        if img.width != self.paper_width:
            if img.width > self.paper_width:
                img = img.resize((self.paper_width, int(img.height * self.paper_width / img.width)))
            else:
                # Center the image
                pad_amount = (self.paper_width - img.width) // 2
                padded_image = Image.new("RGBA", (self.paper_width, img.height), (255, 255, 255, 255))
                padded_image.paste(img, box=(pad_amount, 0))
                img = padded_image
        
        # Convert to RGBA if not already
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        print(f"Processing {img.width}x{img.height} bitmap ({'image' if is_image else 'text'} mode)")
        
        # Get raw RGBA data
        rgba_data = img.tobytes()
        
        # Choose dithering algorithm based on content type (like web app)
        if is_image:
            # Use Floyd-Steinberg dithering for images (preserves detail)
            dithered_data = self.apply_floyd_steinberg_dither(rgba_data, img.width, img.height)
            debug_name = 'debug_image_dithered.png'
        else:
            # Use threshold dithering for text (clean edges)
            dithered_data = self.apply_threshold_dither(rgba_data, img.width, img.height)
            debug_name = 'debug_text_dithered.png'
        
        # Save debug dithered image
        try:
            dithered_img = Image.frombytes('RGBA', (img.width, img.height), dithered_data)
            debug_path = f'/tmp/{debug_name}'
            dithered_img.save(debug_path)
            print(f"Debug: Saved dithered bitmap to {debug_path}")
        except Exception as e:
            print(f"Debug: Failed to save dithered bitmap: {e}")
        
        # Convert to printer bits using web app algorithm
        bits = self.rgba_to_bits(dithered_data, img.width, img.height)
        
        # Debug: print first few bytes of bit data
        print(f"Debug: First 16 bytes of bit data: {bits[:16].hex()}")
        print(f"Debug: Total bit data length: {len(bits)} bytes")
        
        # Split into lines (each line is width/8 bytes)
        bytes_per_line = img.width // 8
        lines = []
        for y in range(img.height):
            start_idx = y * bytes_per_line
            end_idx = start_idx + bytes_per_line
            lines.append(bits[start_idx:end_idx])
        
        return lines
    
    async def print_text(self, text: str, font_size: int = 16, speed: int = 35, energy: int = 8000, align: str = 'center', invert: bool = False, border: int = 0) -> bool:
        """Print text content"""
        if not self.printer:
            print("Error: Printer not connected")
            return False
        
        # Handle escaped newlines from command line
        text = text.replace('\\n', '\n').replace('\\t', '\t')
        print(f"Text to print: {repr(text)}")
        
        print("Converting text to bitmap...")
        bitmap = self.text_to_bitmap(text, font_size, align, invert, border)
        
        print("Converting bitmap to print data...")
        lines = self.bitmap_to_print_data(bitmap, is_image=False)  # Text mode
        
        print("Preparing printer...")
        await self.printer.prepare(speed, energy)
        
        print(f"Sending {len(lines)} lines to printer...")
        for i, line in enumerate(lines):
            await self.printer.draw(line)
            
            if i % 50 == 0:  # Progress indicator
                print(f"Progress: {i+1}/{len(lines)}")
        
        print("Finishing print job...")
        await self.printer.finish(50)  # Feed some extra paper
        
        print("Text printed successfully!")
        return True
    
    async def print_image(self, image_path: str, speed: int = 45, energy: int = 8000) -> bool:
        """Print image file"""
        if not self.printer:
            print("Error: Printer not connected")
            return False
        
        print(f"Loading image: {image_path}")
        try:
            bitmap = self.image_to_bitmap(image_path)
        except Exception as e:
            print(f"Error loading image: {e}")
            return False
        
        print("Converting bitmap to print data...")
        lines = self.bitmap_to_print_data(bitmap, is_image=True)  # Image mode
        
        print("Preparing printer...")
        await self.printer.prepare(speed, energy)
        
        print(f"Sending {len(lines)} lines to printer...")
        for i, line in enumerate(lines):
            await self.printer.draw(line)
            
            if i % 50 == 0:  # Progress indicator
                print(f"Progress: {i+1}/{len(lines)}")
        
        print("Finishing print job...")
        await self.printer.finish(50)  # Feed some extra paper
        
        print("Image printed successfully!")
        return True


def check_requirements():
    """Check if system requirements are met"""
    issues = []
    
    if not BLEAK_AVAILABLE:
        issues.append("Missing required package 'bleak'. Install with: pip install bleak")
    
    try:
        import PIL
    except ImportError:
        issues.append("Missing required package 'Pillow'. Install with: pip install Pillow")
    
    return issues


async def main():
    parser = argparse.ArgumentParser(description='Thermal Printer CLI - kitty-printer compatible')
    parser.add_argument('--scan', '-s', action='store_true', help='Scan for available printers')
    parser.add_argument('--text', '-t', help='Text to print')
    parser.add_argument('--file', '-f', help='Text file to print')
    parser.add_argument('--image', '-i', help='Image file to print (PNG, JPG, etc.)')
    parser.add_argument('--device', '-d', help='Bluetooth device address')
    parser.add_argument('--font-size', type=int, default=16, help='Font size for text (default: 16)')
    parser.add_argument('--align', choices=['left', 'center', 'right'], default='center', help='Text alignment (default: center)')
    parser.add_argument('--invert', action='store_true', help='Invert colors: white text on black background')
    parser.add_argument('--border', type=int, choices=list(range(1, 11)), help='Add border frame around text (1-10 pixels thick)')
    parser.add_argument('--speed', type=int, default=35, help='Print speed (10-90, lower=better quality)')
    parser.add_argument('--energy', type=int, default=8000, help='Energy level (default: 8000)')
    parser.add_argument('--check-requirements', action='store_true', help='Check system requirements')
    
    args = parser.parse_args()
    
    # Check requirements if requested
    if args.check_requirements:
        print("Checking system requirements...")
        issues = check_requirements()
        if issues:
            print("Issues found:")
            for issue in issues:
                print(f"  ❌ {issue}")
            print("\nPlease resolve these issues before using the printer.")
        else:
            print("  ✅ All requirements are met!")
        return
    
    # Quick requirements check
    issues = check_requirements()
    if issues:
        print("System requirements not met:")
        for issue in issues:
            print(f"  ❌ {issue}")
        print("\nRun --check-requirements for help.")
        return
    
    printer_cli = ThermalPrinterCLI()
    
    if args.scan:
        devices = await printer_cli.scan_devices()
        if devices:
            print(f"\nFound {len(devices)} compatible printer(s):")
            for name, address in devices:
                print(f"  📱 {name}: {address}")
            print(f"\nTo use a printer, specify its address with --device")
        return
    
    # Get device address
    device_address = args.device
    if not device_address:
        print("❌ No device address specified.")
        print("Options:")
        print("  1. Run --scan to find available printers")
        print("  2. Use --device AA:BB:CC:DD:EE:FF with a known address")
        return
    
    # Connect to printer
    print("🔗 Connecting to printer...")
    if not await printer_cli.connect(device_address):
        print("❌ Connection failed.")
        return
    
    try:
        # Print content based on arguments
        success = False
        border_width = args.border if args.border is not None else 0
        
        if args.text:
            success = await printer_cli.print_text(args.text, args.font_size, args.speed, args.energy, args.align, args.invert, border_width)
        elif args.file:
            if os.path.exists(args.file):
                try:
                    with open(args.file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    success = await printer_cli.print_text(content, args.font_size, args.speed, args.energy, args.align, args.invert, border_width)
                except Exception as e:
                    print(f"Error reading file {args.file}: {e}")
            else:
                print(f"❌ File not found: {args.file}")
        elif args.image:
            success = await printer_cli.print_image(args.image, args.speed, args.energy)
        else:
            print("❌ No content specified. Use --text, --file, or --image")
            print("\nExamples:")
            print('  python3 thermy.py --text "Hello World" --device AA:BB:CC:DD:EE:FF')
            print('  python3 thermy.py --text "Left\\nAligned" --align left --device AA:BB:CC:DD:EE:FF')
            print('  python3 thermy.py --text "IMPORTANT" --invert --border 2 --font-size 24 --device AA:BB:CC:DD:EE:FF')
            print('  python3 thermy.py --text "WARNING" --border 3 --align center --device AA:BB:CC:DD:EE:FF')
            print('  python3 thermy.py --file document.txt --align center --border 1 --device AA:BB:CC:DD:EE:FF')
            print('  python3 thermy.py --image photo.jpg --device AA:BB:CC:DD:EE:FF')
        
        if success:
            print("✅ Operation completed successfully!")
        
    except KeyboardInterrupt:
        print("\n⚠️  Operation cancelled by user")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
    
    finally:
        try:
            await printer_cli.disconnect()
        except:
            pass  # Ignore disconnect errors


if __name__ == "__main__":
    asyncio.run(main())