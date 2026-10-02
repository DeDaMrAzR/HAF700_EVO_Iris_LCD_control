Option Explicit

' This Source Code Form is subject to the terms of the Mozilla Public
' License, v. 2.0. If a copy of the MPL was not distributed with this
' file, You can obtain one at https://mozilla.org/MPL/2.0/.

' WScript launches the windowed Python interpreter without first creating a
' Command Prompt window. Keep this tiny launcher beside app.py so moving the
' complete APP directory does not bake in the workspace's current drive path.
Dim fileSystem, shell, appDirectory, pythonwPath, command
Set fileSystem = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

appDirectory = fileSystem.GetParentFolderName(WScript.ScriptFullName)
pythonwPath = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Python\bin\pythonw.exe"

If Not fileSystem.FileExists(pythonwPath) Then
    ' Fall back to PATH/App Execution Alias on Python installations that do not
    ' use the local bin directory found on the development machine.
    pythonwPath = "pythonw.exe"
End If

command = Chr(34) & pythonwPath & Chr(34) & " " & Chr(34) & appDirectory & "\app.py" & Chr(34)

' Window style 0 is hidden and False means the launcher returns immediately.
' The actual Tk application still creates and owns its normal visible window.
shell.Run command, 0, False
