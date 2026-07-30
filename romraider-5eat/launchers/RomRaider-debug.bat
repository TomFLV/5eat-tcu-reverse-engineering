@echo off
rem ---------------------------------------------------------------------------
rem Same as RomRaider.bat, but keeps a console and writes console.log.
rem
rem Use this if something goes wrong. RomRaider raises some errors through
rem dialog boxes that never reach its own log file, so stdout and stderr are
rem captured here as well - that is the only place those stack traces appear.
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

echo ==== run started %DATE% %TIME% ==== >> console.log
"jre\bin\java.exe" ^
  -Xmx1024M ^
  -Dawt.useSystemAAFontSettings=lcd ^
  -Dswing.aatext=true ^
  -Dromraider.theme=dark ^
  -Dsun.java2d.uiScale.enabled=true ^
  -Dflatlaf.useWindowDecorations=true ^
  -Dflatlaf.menuBarEmbedded=true ^
  -jar RomRaider.jar %* >> console.log 2>&1

echo.
echo Exited. See console.log in this folder, and %%USERPROFILE%%\.RomRaider\rr_system.log
pause

