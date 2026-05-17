#Requires -Version 5.1
# Intensity-RGB V2.0 - Windows build script (mirror of build.sh).
#
# UNTESTED ON HARDWARE: this script was authored on a Linux dev box and
# has never been executed against a real Windows + PowerShell + Python
# stack. If you encounter errors:
#   * Missing pye57 wheel - pye57 must be installed by source from
#     vendor/pye57/ (the user may need a MSVC + libE57Format build).
#   * Hidden-import surprises around Qt platform plugins - see
#     build/intensity_rgb.spec.
# File a defect against V2.0.0 release notes if found broken on a fresh
# Windows install.

$ErrorActionPreference = 'Stop'

# Repo root = script's parent
$ROOT = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $ROOT
try {
    Write-Host "Building Intensity-RGB V2.0 Windows bundle from $ROOT"

    if (Test-Path build\work) { Remove-Item -Recurse -Force build\work }
    if (Test-Path dist) { Remove-Item -Recurse -Force dist }

    # Install pyinstaller if needed
    & python -m pip install --user pyinstaller 2>$null

    & pyinstaller --clean --noconfirm `
        --workpath build\work `
        --distpath dist `
        build\intensity_rgb.spec

    if (Test-Path dist\intensity-recolor) {
        Rename-Item -Path dist\intensity-recolor -NewName Intensity-RGB-windows-x86_64
    }

    Push-Location dist
    try {
        $zipName = "Intensity-RGB-windows-x86_64.zip"
        if (Test-Path $zipName) { Remove-Item $zipName }
        Compress-Archive -Path Intensity-RGB-windows-x86_64 -DestinationPath $zipName -Force
        $sizeMB = [math]::Round((Get-Item $zipName).Length / 1MB, 0)
        Write-Host "Bundle size: $sizeMB MB"
        if ($sizeMB -gt 250) {
            Write-Error "Bundle exceeds 250 MB target ($sizeMB MB). Investigate hidden-imports / bundled binaries."
            exit 1
        }
    } finally {
        Pop-Location
    }

    Write-Host "Windows bundle built successfully: dist\Intensity-RGB-windows-x86_64.zip"
}
finally {
    Pop-Location
}
