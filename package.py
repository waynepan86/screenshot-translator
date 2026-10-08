"""Build the runtime, verify it, then create portable and setup packages."""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from app_version import APP_VERSION


def smoke(executable, report):
    environment = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    completed = subprocess.run([str(executable), '--self-test', str(report)],
                               cwd=executable.parent, env=environment, timeout=180)
    if not report.exists():
        raise RuntimeError('Packaged runtime did not complete its self-test')
    result = json.loads(report.read_text(encoding='utf-8'))
    if completed.returncode or not result.get('ok') or result.get('version') != APP_VERSION:
        raise RuntimeError('Packaged self-test failed: ' + str(report))
    return result


def find_compiler(explicit):
    candidates = [explicit, os.environ.get('ISCC'), shutil.which('ISCC.exe')]
    candidates += [str(Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Inno Setup 6/ISCC.exe'),
                   str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Inno Setup 7/ISCC.exe')]
    return next((Path(path).resolve() for path in candidates if path and Path(path).is_file()), None)


def create_portable_archive(bundle, portable, archive, root):
    # Enumerate build outputs rather than the portable directory, which may
    # already hold a tester's config/data from a previous run.
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for path in bundle.rglob('*'):
            relative = path.relative_to(bundle)
            if path.is_file() and relative.parts[0] != 'data' and path.name not in ('config.json', 'portable.flag') and path.suffix != '.log' and relative not in (Path('README.md'), Path('USER_GUIDE.md')):
                output.write(path, str(Path(portable.name) / relative))
        output.write(root / 'README.md', str(Path(portable.name) / 'README.md'))
        output.writestr(f'{portable.name}/portable.flag', 'Store application data in ./data.\n')
        output.writestr(f'{portable.name}/data/', '')


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-build', action='store_true')
    parser.add_argument('--iscc', help='Path to the Inno Setup compiler')
    parser.add_argument('--portable-only', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    os.chdir(root)
    compiler = find_compiler(args.iscc)
    if not args.portable_only and compiler is None:
        raise SystemExit('Install Inno Setup or pass --iscc PATH; --portable-only explicitly skips Setup.')
    if not args.skip_build:
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm', str(root / '截图工具.spec')], check=True)
    bundle = root / 'dist' / 'ScreenshotTranslator'
    shutil.copy2(root / 'README.md', bundle / 'README.md')
    # The offline guide lives in _internal for the About dialog. Only README
    # is exposed next to the executable, including when reusing old builds.
    (bundle / 'USER_GUIDE.md').unlink(missing_ok=True)
    release = root / 'dist' / f'v{APP_VERSION}'
    release.mkdir(parents=True, exist_ok=True)
    smoke(bundle / 'ScreenshotTranslator.exe', release / 'standard-self-test.json')
    portable = release / f'ScreenshotTranslator-{APP_VERSION}-Portable'
    shutil.copytree(bundle, portable, dirs_exist_ok=True)
    (portable / 'portable.flag').write_text('Keep this file to store all application data in ./data.\n', encoding='utf-8')
    (portable / 'data').mkdir(exist_ok=True)
    shutil.copy2(root / 'README.md', portable / 'README.md')
    (portable / 'USER_GUIDE.md').unlink(missing_ok=True)
    result = smoke(portable / 'ScreenshotTranslator.exe', release / 'portable-self-test.json')
    if not result.get('portable'):
        raise RuntimeError('Portable marker was not detected')
    archive = release / f'ScreenshotTranslator-{APP_VERSION}-Portable.zip'
    create_portable_archive(bundle, portable, archive, root)
    artifacts = [archive]
    if compiler and not args.portable_only:
        subprocess.run([str(compiler), f'/DAppVersion={APP_VERSION}', f'/DBundleDir={bundle}',
                        f'/DReleaseDir={release}', str(root / 'setup.iss')], check=True)
        artifacts.append(release / f'ScreenshotTranslator-{APP_VERSION}-Setup.exe')
    for path in artifacts:
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        path.with_suffix(path.suffix + '.sha256').write_text(f'{digest}  {path.name}\n', encoding='utf-8')
        print('Created:', path)


if __name__ == '__main__':
    run()
