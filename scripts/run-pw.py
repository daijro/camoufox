import argparse
import json
import os
import shutil
import time
from pathlib import Path

from _mixin import find_src_dir, get_moz_target, temp_cd
from playwright.sync_api import sync_playwright

LOCAL_PATH = Path(os.path.abspath(__file__)).parent

CONFIG = {
    'window.outerWidth': 1920,
    'window.outerHeight': 1080,
}


def launch_playwright(executable_path):
    """Launch playwright Firefox with unlimited time"""
    with sync_playwright() as p:
        print('Launching browser.', executable_path)
        browser = p.firefox.launch(
            executable_path=executable_path,
            headless=False,
            args=[
                '--stderr',
                str(LOCAL_PATH / 'debug.log'),
                '--config',
                json.dumps(CONFIG),
            ],
        )
        page = browser.new_page()
        url = os.getenv('URL') or 'https://google.com'
        page.goto(url)
        try:
            time.sleep(1e9)
        except:
            print('Closing...')
        finally:
            browser.close()


def get_args():
    """Get CLI parameters"""
    parser = argparse.ArgumentParser(
        description='Package Camoufox for different operating systems.'
    )
    parser.add_argument('--version', required=True, help='Camoufox version')
    parser.add_argument('--release', required=True, help='Camoufox release number')
    return parser.parse_args()


def main():
    """Run the browser with Playwright"""
    args = get_args()

    src_dir = find_src_dir('.', args.version, args.release)
    moz_target = get_moz_target(target='linux', arch='x86_64')

    launcher_path = os.path.abspath(os.path.join('.', 'legacy', 'launcher', 'dist', 'launch'))

    with temp_cd(src_dir):
        print(f'Looking for file: obj-{moz_target}/dist/bin/camoufox-bin')
        with temp_cd(f'obj-{moz_target}/dist/bin'):
            if os.path.exists('camoufox-bin'):
                # Copy launcher_path to . if we are using camoufox-bin
                shutil.copy(launcher_path, '.')
                file_name = 'launch'
            elif os.path.exists('firefox-bin'):
                # Or else just use firefox-bin
                file_name = 'firefox-bin'
            else:
                raise FileNotFoundError(f'Binary not found: obj-{moz_target}/dist/bin')
        file_path = os.path.abspath(f'obj-{moz_target}/dist/bin/{file_name}')

    with temp_cd(os.path.dirname(file_path)):
        launch_playwright(file_path)


if __name__ == '__main__':
    main()
