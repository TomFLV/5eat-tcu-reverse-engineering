' ---------------------------------------------------------------------------
' RomRaider 1.1.0 for Subaru 5EAT TCU - launcher (no console window)
'
' RomRaider.bat works too, but briefly flashes a console. This launches the
' bundled runtime directly with no window at all. Nothing is installed and
' nothing is left running afterwards.
'
' If something goes wrong, run RomRaider-debug.bat instead - it keeps a console
' and writes console.log, which is the only place some error dialogs leave a
' stack trace.
' ---------------------------------------------------------------------------
Option Explicit

Dim fso, shell, here, javaw, args
Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

here  = fso.GetParentFolderName(WScript.ScriptFullName)
javaw = fso.BuildPath(here, "jre\bin\javaw.exe")

If Not fso.FileExists(javaw) Then
    MsgBox "Bundled Java runtime not found:" & vbCrLf & vbCrLf & javaw & vbCrLf & vbCrLf & _
           "Extract the entire folder, not just RomRaider.jar.", 16, "RomRaider"
    WScript.Quit 1
End If

If Not fso.FileExists(fso.BuildPath(here, "RomRaider.jar")) Then
    MsgBox "RomRaider.jar not found in:" & vbCrLf & vbCrLf & here, 16, "RomRaider"
    WScript.Quit 1
End If

shell.CurrentDirectory = here

args = """" & javaw & """" & _
       " -Xmx1024M" & _
       " -Dawt.useSystemAAFontSettings=lcd" & _
       " -Dswing.aatext=true" & _
       " -Dromraider.theme=dark" & _
       " -Dsun.java2d.uiScale.enabled=true" & _
       " -Dflatlaf.useWindowDecorations=true" & _
       " -Dflatlaf.menuBarEmbedded=true" & _
       " -jar ""RomRaider.jar"""

' 0 = hidden window, False = do not wait
shell.Run args, 0, False

