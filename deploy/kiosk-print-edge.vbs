' Launch the booth in Edge without a console window.
' Double-click this file; it runs kiosk-print-edge.cmd from the same folder.
Set shell = CreateObject("WScript.Shell")
folder = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
shell.Run "cmd /c """ & folder & "kiosk-print-edge.cmd""", 0, False
