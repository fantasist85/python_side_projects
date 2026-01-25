#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build script for MouseKeepAwake executable
Creates a minimal size exe file using PyInstaller
"""

import os
import sys
import shutil
import subprocess


def check_dependencies():
    """Check if all required dependencies are installed"""
    print("\nChecking dependencies...")

    # Check PyInstaller
    try:
        import PyInstaller
        print(f"✓ PyInstaller {PyInstaller.__version__} found")
        return True
    except ImportError:
        print("✗ PyInstaller not found!")
        print("\nPlease install PyInstaller:")
        print("  pip install pyinstaller")
        print("\nOr install all requirements:")
        print("  pip install -r requirements.txt")
        return False


def build_executable():
    """Build executable using PyInstaller with optimization options"""

    print("=" * 60)
    print("Building MouseKeepAwake executable...")
    print("=" * 60)

    # PyInstaller command with optimization options
    # Use 'python -m PyInstaller' for better compatibility
    cmd = [
        sys.executable,  # Use current Python interpreter
        '-m', 'PyInstaller',
        '--onefile',  # Single executable file
        '--noconsole',  # No console window (GUI mode)
        '--name=MouseKeepAwake',  # Output filename
        '--clean',  # Clean cache before building
        '--noconfirm',  # Replace output without asking

        # Optimize imports (exclude unnecessary modules)
        '--exclude-module=tkinter',
        '--exclude-module=matplotlib',
        '--exclude-module=numpy',
        '--exclude-module=pandas',
        '--exclude-module=scipy',
        '--exclude-module=PyQt5',
        '--exclude-module=PyQt6',
        '--exclude-module=PySide2',
        '--exclude-module=PySide6',

        # UPX compression (if available) - uncomment if UPX is installed
        # '--upx-dir=/path/to/upx',

        'main.py'
    ]

    print(f"\nRunning command: {' '.join(cmd)}\n")

    try:
        # Run PyInstaller
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print("Warnings:", result.stderr)

        print("\n" + "=" * 60)
        print("Build completed successfully!")
        print("=" * 60)

        # Show output file location
        exe_path = os.path.join('dist', 'MouseKeepAwake.exe')
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"\nExecutable location: {os.path.abspath(exe_path)}")
            print(f"File size: {size_mb:.2f} MB")

        print("\nCleaning up build files...")
        # Clean up build directory (optional)
        if os.path.exists('build'):
            shutil.rmtree('build')
        if os.path.exists('MouseKeepAwake.spec'):
            os.remove('MouseKeepAwake.spec')

        print("Build artifacts cleaned up.")
        print("\nYou can now run: dist/MouseKeepAwake.exe")

    except subprocess.CalledProcessError as e:
        print(f"\n❌ Build failed!")
        print(f"Error code: {e.returncode}")
        print(f"\nCommand that failed:")
        print(f"  {' '.join(cmd)}")
        if e.stdout:
            print(f"\nStandard output:")
            print(e.stdout)
        if e.stderr:
            print(f"\nError output:")
            print(e.stderr)
        print("\nTroubleshooting:")
        print("1. Make sure PyInstaller is installed: pip install pyinstaller")
        print("2. Check if main.py exists in the current directory")
        print("3. Try running: python -m PyInstaller --version")
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"\n❌ File not found error: {e}")
        print("\nPossible causes:")
        print("1. PyInstaller is not installed")
        print("   Solution: pip install pyinstaller")
        print("2. Python Scripts folder is not in PATH")
        print(f"   Current Python: {sys.executable}")
        print("\nTry installing PyInstaller:")
        print("  pip install pyinstaller")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        print(f"Error type: {type(e).__name__}")
        import traceback
        print("\nFull traceback:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    print("MouseKeepAwake Build Script")
    print("=" * 60)

    # Check if we're in the right directory
    if not os.path.exists('main.py'):
        print("\n❌ Error: main.py not found!")
        print("Please run this script from the MouseKeepAwake directory.")
        print(f"\nCurrent directory: {os.getcwd()}")
        print("\nUsage:")
        print("  cd path/to/MouseKeepAwake")
        print("  python build_exe.py")
        sys.exit(1)

    print(f"Current directory: {os.getcwd()}")
    print(f"Python executable: {sys.executable}")
    print(f"Python version: {sys.version}")

    # Check dependencies
    if not check_dependencies():
        sys.exit(1)

    # Build
    build_executable()
