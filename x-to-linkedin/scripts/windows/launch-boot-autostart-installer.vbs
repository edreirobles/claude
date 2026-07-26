Set shellApp = CreateObject("Shell.Application")
shellApp.ShellExecute "powershell.exe", "-NoProfile -ExecutionPolicy Bypass -File ""C:\Users\victo\claude\x-to-linkedin\scripts\windows\install-boot-autostart.ps1""", "", "runas", 1
