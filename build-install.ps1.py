#!/usr/bin/env python3
"""Regenerate INSTALL-NO-GIT.ps1 — run from repo: python3 here445/build-install.ps1.py"""
import base64
from pathlib import Path

root = Path(__file__).resolve().parent
py_b = base64.b64encode((root / "stock go threw to pull accurte info then hit sit.py").read_bytes()).decode()
bat_b = base64.b64encode((root / "Open BIN Lookup Website.bat").read_bytes()).decode()
zip_b = base64.b64encode((root / "website-source.zip").read_bytes()).decode()

header = """# BIN Lookup setup - NO GIT. Save as INSTALL-NO-GIT.ps1 in Downloads, then run it.

$Target = Join-Path $env:USERPROFILE "Downloads\\here445"
New-Item -ItemType Directory -Force -Path $Target | Out-Null

function Write-B64File($Path, $B64) {
  [IO.File]::WriteAllBytes($Path, [Convert]::FromBase64String($B64))
}

"""

footer = '''
@"
Files are in C:\\Users\\motod\\Downloads\\here445

Double-click: Open BIN Lookup Website.bat
Install Node.js if asked: https://nodejs.org/
"@ | Set-Content -Path (Join-Path $Target "START HERE.txt") -Encoding UTF8

Write-Host ""
Write-Host "SUCCESS. Open this folder and double-click the .bat file:"
Write-Host $Target
Write-Host ""
'''

parts = [
    header,
    f'Write-B64File (Join-Path $Target "Open BIN Lookup Website.bat") "{bat_b}"\n\n',
    f'Write-B64File (Join-Path $Target "stock go threw to pull accurte info then hit sit.py") "{py_b}"\n\n',
    f'Write-B64File (Join-Path $Target "website-source.zip") "{zip_b}"\n\n',
    footer,
]
(root / "INSTALL-NO-GIT.ps1").write_text("".join(parts), encoding="utf-8")
print("Wrote", root / "INSTALL-NO-GIT.ps1")
