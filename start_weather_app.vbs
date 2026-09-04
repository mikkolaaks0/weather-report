Option Explicit
Dim shell, appDir, exitCode, errorMessage
Set shell = CreateObject("WScript.Shell")
appDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = appDir
exitCode = shell.Run("""" & appDir & "\start_weather_app.bat""", 0, True)
If exitCode <> 0 Then
    errorMessage = "Weather Report could not start. Install Python 3.10 or newer with Tkinter, or check the project's .venv environment."
    If WScript.Interactive And LCase(Right(WScript.FullName, 11)) = "wscript.exe" Then
        MsgBox errorMessage, vbExclamation, "Weather Report"
    Else
        WScript.Echo errorMessage
    End If
End If
WScript.Quit exitCode
