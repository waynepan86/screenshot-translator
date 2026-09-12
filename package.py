"""Build using the audited spec and this interpreter's dependencies."""
import subprocess
import sys
from pathlib import Path


def run():
    root = Path(__file__).resolve().parent
    try:
        import PyInstaller
    except ImportError:
        raise SystemExit('Install build dependencies first: python -m pip install pyinstaller')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', str(root / '截图工具.spec')], cwd=root, check=True)
    print('Packaging complete:', root / 'dist' / '截图工具.exe')


if __name__ == '__main__':
    run()
