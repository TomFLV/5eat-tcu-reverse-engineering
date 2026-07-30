@echo off
rem ---------------------------------------------------------------------------
rem RomRaider 1.1.0 for Subaru 5EAT TCU - standalone launcher
rem
rem Uses the bundled Java runtime in .\jre, so nothing needs to be installed.
rem Dark theme by default; pass -Dromraider.theme=light or =system to change it.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

if not exist "jre\bin\javaw.exe" (
  echo ERROR: bundled runtime missing - expected jre\bin\javaw.exe
  echo Extract the whole folder, not just RomRaider.jar.
  pause
  exit /b 1
)

start "" "jre\bin\javaw.exe" ^
  -Xmx1024M ^
  -Dawt.useSystemAAFontSettings=lcd ^
  -Dswing.aatext=true ^
  -Dromraider.theme=dark ^
  -Dsun.java2d.uiScale.enabled=true ^
  -Dflatlaf.useWindowDecorations=true ^
  -Dflatlaf.menuBarEmbedded=true ^
  -jar RomRaider.jar %*

