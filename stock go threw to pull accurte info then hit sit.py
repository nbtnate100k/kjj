"""
Double-click (or use Open BIN Lookup Website.bat) in:
  C:\\Users\\motod\\Downloads\\here445

First run downloads the website into this folder (needs Git + Node.js).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import webbrowser

HOST = "127.0.0.1"
PORT = 43123
SITE_URL = f"http://{HOST}:{PORT}"
REPO_URL = "https://origin.cursor.com/git/kewz/tmp-cd1a0b5301a42995.git"
SKIP_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        ".next",
        "here445",
        "BIN-Lookup-Windows",
        "bin thing",
        "uploads",
        "terminals",
        "tmp-scaffold",
    }
)


def pause_before_exit() -> None:
    print()
    if sys.platform == "win32":
        os.system("pause")
    else:
        try:
            input("Press Enter to exit...")
        except (EOFError, KeyboardInterrupt):
            pass


def find_project_root(start_dir: str) -> str | None:
    current = os.path.abspath(start_dir)
    for _ in range(8):
        if os.path.isfile(os.path.join(current, "package.json")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def find_npm() -> str | None:
    return shutil.which("npm") or shutil.which("npm.cmd")


def find_git() -> str | None:
    return shutil.which("git")


def bootstrap_from_zip(project_dir: str) -> bool:
    import zipfile

    zip_path = os.path.join(project_dir, "website-source.zip")
    if not os.path.isfile(zip_path):
        return False
    print("Extracting website-source.zip into this folder...")
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(project_dir)
    return os.path.isfile(os.path.join(project_dir, "package.json"))


def bootstrap_project(project_dir: str) -> bool:
    if os.path.isfile(os.path.join(project_dir, "package.json")):
        return True

    if bootstrap_from_zip(project_dir):
        print("Website files ready (from zip).\n")
        return True

    git = find_git()
    if not git:
        print("Missing website files. Either:")
        print("  1. Put website-source.zip in this folder, or")
        print("  2. Install Git: https://git-scm.com/download/win")
        print("  3. Run INSTALL-NO-GIT.ps1 from the project (creates all files)")
        print(f"\nFolder: {project_dir}")
        return False

    print("=" * 60)
    print("FIRST TIME — downloading BIN lookup website into this folder")
    print("=" * 60)
    print(project_dir)
    print()

    tmp = tempfile.mkdtemp(prefix="binlookup-setup-")
    try:
        subprocess.check_call([git, "clone", "--depth", "1", REPO_URL, tmp])
        for name in os.listdir(tmp):
            if name in SKIP_NAMES:
                continue
            src = os.path.join(tmp, name)
            dst = os.path.join(project_dir, name)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
        ok = os.path.isfile(os.path.join(project_dir, "package.json"))
        if ok:
            print("\nDownload complete.\n")
        return ok
    except subprocess.CalledProcessError:
        print("\nDownload failed. Check internet connection and Git install.")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def wait_for_site(url: str, timeout_sec: float = 120.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.6)
    return False


def find_cli_path(script_dir: str, project_root: str | None) -> str | None:
    candidates = [
        os.path.join(script_dir, "bin-lookup-cli.py"),
        os.path.join(script_dir, "scripts", "bin-lookup-cli.py"),
    ]
    if project_root:
        candidates.append(os.path.join(project_root, "scripts", "bin-lookup-cli.py"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def run_cli(script_dir: str, extra_args: list[str]) -> int:
    root = find_project_root(script_dir) or find_project_root(os.getcwd())
    if not root and bootstrap_project(script_dir):
        root = script_dir
    cli_path = find_cli_path(script_dir, root)
    if not cli_path:
        print("CLI not found. Run without --cli to download the website first.")
        pause_before_exit()
        return 1
    return subprocess.call([sys.executable, cli_path, *extra_args])


def ensure_npm_dependencies(project_root: str, npm: str) -> None:
    if os.path.isdir(os.path.join(project_root, "node_modules")):
        return
    print("Installing website dependencies (npm install)...")
    subprocess.check_call([npm, "install"], cwd=project_root, shell=False)


def start_dev_server(project_root: str, npm: str) -> subprocess.Popen[bytes]:
    command = [npm, "run", "dev", "--", "-p", str(PORT), "-H", HOST]
    if sys.platform == "win32":
        return subprocess.Popen(
            command,
            cwd=project_root,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    return subprocess.Popen(command, cwd=project_root)


def launch_website(script_dir: str) -> int:
    npm = find_npm()
    if not npm:
        print("Install Node.js: https://nodejs.org/")
        pause_before_exit()
        return 1

    project_root = find_project_root(script_dir) or find_project_root(os.getcwd())
    if not project_root:
        if not bootstrap_project(script_dir):
            pause_before_exit()
            return 1
        project_root = script_dir

    try:
        ensure_npm_dependencies(project_root, npm)
    except subprocess.CalledProcessError:
        print("npm install failed.")
        pause_before_exit()
        return 1

    print("=" * 60)
    print("BIN CARD LOOKUP — starting website")
    print("=" * 60)
    print(f"Folder: {project_root}")
    print(f"URL:    {SITE_URL}\n")

    server = start_dev_server(project_root, npm)

    if not wait_for_site(SITE_URL):
        print("Site did not start in time.")
        server.terminate()
        pause_before_exit()
        return 1

    print("Opening browser...")
    webbrowser.open(SITE_URL)
    print("\nRunning — close this window to stop the server.\n")

    try:
        return server.wait()
    except KeyboardInterrupt:
        server.terminate()
        return 0


def main() -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description="BIN lookup launcher")
    parser.add_argument("--cli", action="store_true", help="Terminal lookup tool")
    args, rest = parser.parse_known_args()

    try:
        if args.cli:
            code = run_cli(script_dir, rest)
            if code != 0:
                pause_before_exit()
            sys.exit(code)
        code = launch_website(script_dir)
        if code not in (0, None):
            pause_before_exit()
    except Exception:
        print("\n*** ERROR ***")
        import traceback

        traceback.print_exc()
        pause_before_exit()


if __name__ == "__main__":
    main()
