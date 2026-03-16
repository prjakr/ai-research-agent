Dim fso, sh, d, py
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")
d  = fso.GetParentFolderName(WScript.ScriptFullName)
py = "C:\Users\user\AppData\Local\Programs\Python\Python314\pythonw.exe"
sh.CurrentDirectory = d
sh.Run Chr(34) & py & Chr(34) & " -X utf8 launch.py", 0, False
