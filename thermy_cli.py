#!/usr/bin/env python3
"""
Thermal Printer CLI
Command-line interface for Mini Bluetooth Thermal Printers
"""

import asyncio
import argparse
import os
import sys

from thermy import ThermalPrinter, check_requirements


async def main():
    parser = argparse.ArgumentParser(description='Thermal Printer CLI - kitty-printer compatible')
    parser.add_argument('--scan', '-s', action='store_true', help='Scan for available printers')
    parser.add_argument('--text', '-t', help='Text to print')
    parser.add_argument('--file', '-f', help='Text file to print')
    parser.add_argument('--image', '-i', help='Image file to print (PNG, JPG, etc.)')
    parser.add_argument('--qr', help='Generate and print a QR code from text/URL')
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

    printer = ThermalPrinter(on_message=print)

    if args.scan:
        try:
            devices = await printer.scan_devices()
            if devices:
                print(f"\nFound {len(devices)} compatible printer(s):")
                for name, address in devices:
                    print(f"  📱 {name}: {address}")
                print(f"\nTo use a printer, specify its address with --device")
        except Exception as e:
            print(f"❌ {e}")
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
    try:
        await printer.connect(device_address)
    except Exception as e:
        print(f"❌ {e}")
        return

    try:
        # Print content based on arguments
        success = False
        border_width = args.border if args.border is not None else 0

        if args.text:
            success = await printer.print_text(args.text, args.font_size, args.speed, args.energy, args.align, args.invert, border_width)
        elif args.file:
            if os.path.exists(args.file):
                try:
                    with open(args.file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    success = await printer.print_text(content, args.font_size, args.speed, args.energy, args.align, args.invert, border_width)
                except Exception as e:
                    print(f"Error reading file {args.file}: {e}")
            else:
                print(f"❌ File not found: {args.file}")
        elif args.qr:
            success = await printer.print_qr(args.qr, args.speed, args.energy)
        elif args.image:
            success = await printer.print_image(args.image, args.speed, args.energy)
        else:
            print("❌ No content specified. Use --text, --file, --image, or --qr")
            print("\nExamples:")
            print('  python3 thermy.py --text "Hello World" --device AA:BB:CC:DD:EE:FF')
            print('  python3 thermy.py --text "Left\\nAligned" --align left --device AA:BB:CC:DD:EE:FF')
            print('  python3 thermy.py --text "IMPORTANT" --invert --border 2 --font-size 24 --device AA:BB:CC:DD:EE:FF')
            print('  python3 thermy.py --text "WARNING" --border 3 --align center --device AA:BB:CC:DD:EE:FF')
            print('  python3 thermy.py --file document.txt --align center --border 1 --device AA:BB:CC:DD:EE:FF')
            print('  python3 thermy.py --qr "https://example.com" --device AA:BB:CC:DD:EE:FF')
            print('  python3 thermy.py --image photo.jpg --device AA:BB:CC:DD:EE:FF')

        if success:
            print("✅ Operation completed successfully!")

    except KeyboardInterrupt:
        print("\n⚠️  Operation cancelled by user")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

    finally:
        try:
            await printer.disconnect()
        except:
            pass  # Ignore disconnect errors


def main_sync():
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
