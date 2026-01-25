#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MouseKeepAwake - Prevents screensaver by moving mouse cursor
Simple, lightweight background application
"""

import time
import threading
from pynput import mouse
from pynput.mouse import Controller, Button
import pystray
from PIL import Image, ImageDraw
import sys

try:
    from config import IDLE_TIMEOUT, MOVEMENT_PIXELS, MOVEMENT_DELAY, CHECK_INTERVAL
except ImportError:
    # Default values if config.py is not found
    IDLE_TIMEOUT = 30
    MOVEMENT_PIXELS = 1
    MOVEMENT_DELAY = 0.05
    CHECK_INTERVAL = 1


class MouseKeepAwake:
    """Prevents screensaver by detecting mouse inactivity and moving cursor"""

    def __init__(self, idle_timeout=30):
        self.idle_timeout = idle_timeout  # seconds
        self.mouse_controller = Controller()
        self.last_activity = time.time()
        self.running = False
        self.enabled = True
        self.lock = threading.Lock()
        self.monitor_thread = None
        self.checker_thread = None

    def on_move(self, x, y):
        """Callback for mouse movement"""
        with self.lock:
            self.last_activity = time.time()

    def on_click(self, x, y, button, pressed):
        """Callback for mouse clicks"""
        with self.lock:
            self.last_activity = time.time()

    def on_scroll(self, x, y, dx, dy):
        """Callback for mouse scroll"""
        with self.lock:
            self.last_activity = time.time()

    def move_mouse_slightly(self):
        """Move mouse cursor by configured pixels and back"""
        try:
            current_pos = self.mouse_controller.position
            # Move by configured pixels to the right
            self.mouse_controller.position = (current_pos[0] + MOVEMENT_PIXELS, current_pos[1])
            time.sleep(MOVEMENT_DELAY)  # Small delay
            # Move back to original position
            self.mouse_controller.position = current_pos
        except Exception as e:
            print(f"Error moving mouse: {e}")

    def check_idle(self):
        """Check if mouse has been idle and move it if necessary"""
        while self.running:
            try:
                time.sleep(CHECK_INTERVAL)  # Check at configured interval

                if not self.enabled:
                    continue

                with self.lock:
                    idle_time = time.time() - self.last_activity

                if idle_time >= self.idle_timeout:
                    self.move_mouse_slightly()
                    with self.lock:
                        self.last_activity = time.time()

            except Exception as e:
                print(f"Error in idle checker: {e}")

    def start(self):
        """Start monitoring mouse activity"""
        if self.running:
            return

        self.running = True
        self.last_activity = time.time()

        # Start mouse listener
        self.listener = mouse.Listener(
            on_move=self.on_move,
            on_click=self.on_click,
            on_scroll=self.on_scroll
        )
        self.listener.start()

        # Start idle checker thread
        self.checker_thread = threading.Thread(target=self.check_idle, daemon=True)
        self.checker_thread.start()

    def stop(self):
        """Stop monitoring"""
        self.running = False
        if hasattr(self, 'listener'):
            self.listener.stop()

    def toggle(self):
        """Toggle enabled state"""
        self.enabled = not self.enabled
        return self.enabled


def create_icon_image():
    """Create a simple icon for system tray"""
    # Create a 64x64 image with a simple mouse cursor icon
    width = 64
    height = 64
    image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(image)

    # Draw a simple mouse cursor shape
    draw.polygon([
        (20, 10),
        (20, 50),
        (30, 42),
        (38, 54),
        (42, 52),
        (34, 40),
        (44, 40)
    ], fill='black', outline='black')

    return image


def main():
    """Main application entry point"""
    app = MouseKeepAwake(idle_timeout=IDLE_TIMEOUT)
    app.start()

    # System tray icon setup
    icon_image = create_icon_image()

    def on_quit(icon, item):
        """Quit application"""
        app.stop()
        icon.stop()

    def on_toggle(icon, item):
        """Toggle enabled state"""
        enabled = app.toggle()
        # Update menu to show current state
        icon.title = f"MouseKeepAwake {'(Enabled)' if enabled else '(Disabled)'}"

    def get_enabled_state(item):
        """Get current enabled state for menu"""
        return app.enabled

    # Create system tray menu
    menu = pystray.Menu(
        pystray.MenuItem(
            'Enabled',
            on_toggle,
            checked=get_enabled_state,
            default=True
        ),
        pystray.MenuItem('Quit', on_quit)
    )

    # Create system tray icon
    icon = pystray.Icon(
        'MouseKeepAwake',
        icon_image,
        'MouseKeepAwake (Enabled)',
        menu
    )

    # Run the icon (this blocks)
    icon.run()


if __name__ == '__main__':
    main()
