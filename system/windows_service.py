"""Frozen SCM entry point. Installation is handled by the elevated installer."""
import json
import sys
import threading
from pathlib import Path

import servicemanager
import win32service
import win32serviceutil

from windows_helper import HelperState, load_token, serve, token_path


def resource_root():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parents[1]


class NorthstarService(win32serviceutil.ServiceFramework):
    _svc_name_ = "NorthstarVPNHelper"
    _svc_display_name_ = "Northstar VPN Helper"
    _svc_description_ = "Owns Northstar's OpenVPN session and mandatory IPv6 firewall guard."

    def __init__(self, args):
        super().__init__(args)
        self.stopped = threading.Event()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=60000)
        self.stopped.set()

    def SvcShutdown(self):
        self.SvcStop()

    def SvcDoRun(self):
        state = HelperState(resource_root() / "profiles")
        try:
            # Never take the service secret, profile root, executable or bind
            # address from an interactive user's environment or command line.
            token = load_token(token_path().read_text(encoding="utf-8").strip())
            serve("127.0.0.1", 8799, token, state, self.stopped)
        except Exception:
            servicemanager.LogErrorMsg("Northstar helper could not start. Check installation permissions and port 8799.")
            raise
        finally:
            # Graceful SCM stop closes the tunnel before releasing its guard.
            state.disconnect()


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        print(json.dumps({"service": NorthstarService._svc_name_, "resources": str(resource_root()),
                          "profiles": len(list((resource_root() / "profiles").glob("*/*.ovpn")))}))
    else:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(NorthstarService)
        servicemanager.StartServiceCtrlDispatcher()
