' Launch Michi with no console window. Used by the autostart task and
' handy as a desktop shortcut once you trust her to run quietly.
Option Explicit

Dim shell, fso, here, python, args
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Parent of the install\ folder = project root
here = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
python = here & "\.venv\Scripts\pythonw.exe"

If Not fso.FileExists(python) Then
    MsgBox "Michi isn't set up yet - run setup.bat first." & vbCrLf & vbCrLf & _
           "Looked for:" & vbCrLf & python, vbExclamation, "Michi"
    WScript.Quit 1
End If

shell.CurrentDirectory = here
' 0 = hidden window, False = don't wait for it to finish
shell.Run """" & python & """ -m michi --tray", 0, False
