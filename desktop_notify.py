"""Windows desktop toast notifications (works while the app window is closed, via the background service)."""
import subprocess
import sys


def toast(title, body=""):
    if sys.platform != "win32":
        return False
    title, body = (title or "CSE AI Agent")[:90], (body or " ")[:240]
    try:
        from winotify import Notification
        Notification(app_id="CSE AI Agent", title=title, msg=body, duration="long").show()
        return True
    except ImportError:
        pass
    except Exception:
        pass
    try:   # fallback without extra packages
        q = lambda x: x.replace("'", "''")
        ps = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
              "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information; "
              f"$n.Visible = $true; $n.ShowBalloonTip(9000, '{q(title)}', '{q(body)}', [System.Windows.Forms.ToolTipIcon]::None); "
              "Start-Sleep -Seconds 10; $n.Dispose()")
        subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                         creationflags=0x08000000)
        return True
    except Exception:
        return False
