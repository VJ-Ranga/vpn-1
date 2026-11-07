import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "scripts" / "install-windows-service.ps1"


def test_nsis_uses_native_x64_powershell_for_both_actions():
    text = (ROOT / "scripts" / "windows-installer.nsh").read_text()
    assert text.count("$WINDIR\\Sysnative\\WindowsPowerShell") == 2
    assert "$SYSDIR\\WindowsPowerShell" not in text


def test_installer_sets_file_acls_separately_from_directory_acls():
    text = INSTALL.read_text()
    assert "Protect-AppTree $installDir" in text
    assert "O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;GRGX;;;BU)" in text
    assert "O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;BU)" in text
    assert "/T /Q" not in text


@pytest.mark.skipif(os.name != "nt", reason="Windows CIM schema")
def test_service_registration_types_match_the_actual_windows_schema():
    text = INSTALL.read_text()
    assert "ServiceType = [byte]16" in text
    assert "ErrorControl = [byte]1" in text
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "(Get-CimClass Win32_Service).CimClassMethods['Create'].Parameters | "
         "Where-Object { $_.Name -in @('ServiceType','ErrorControl') } | "
         "Select-Object Name,@{Name='Type';Expression={$_.CimType.ToString()}} | ConvertTo-Json -Compress"],
        capture_output=True, text=True, check=True, timeout=20,
    )
    assert {item["Type"] for item in json.loads(result.stdout)} == {"UInt8"}


@pytest.mark.skipif(os.name != "nt", reason="Windows ACL parser")
def test_installed_file_dacl_has_effective_read_execute_for_normal_users():
    text = INSTALL.read_text()
    sddl = re.search(r"SetSecurityDescriptorSddlForm\('(O:BAG:BAD:P\(A;;FA[^']+)'\)", text).group(1)
    # Parse the descriptor in memory only; do not change filesystem permissions.
    command = (
        "$acl=New-Object Security.AccessControl.FileSecurity;"
        f"$acl.SetSecurityDescriptorSddlForm('{sddl}');"
        "$acl.GetAccessRules($true,$false,[Security.Principal.SecurityIdentifier]) | "
        "Select-Object @{Name='Sid';Expression={$_.IdentityReference.Value}},"
        "@{Name='Rights';Expression={$_.FileSystemRights.ToString()}},"
        "@{Name='Propagation';Expression={$_.PropagationFlags.ToString()}} | ConvertTo-Json -Compress"
    )
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
                            capture_output=True, text=True, check=True, timeout=10)
    rules = {item["Sid"]: item for item in json.loads(result.stdout)}
    assert set(rules) == {"S-1-5-18", "S-1-5-32-544", "S-1-5-32-545"}
    assert rules["S-1-5-32-545"]["Propagation"] == "None"
    # In-memory descriptors retain the GR|GX generic mask; Windows maps it
    # to ReadAndExecute when the descriptor is applied to an actual file.
    assert rules["S-1-5-32-545"]["Rights"] in {"-1610612736", "ReadAndExecute, Synchronize"}
    assert "FullControl" in rules["S-1-5-32-544"]["Rights"]
