"""Private-file checks shared by TLS keys and other local runtime secrets."""
import os
from pathlib import Path
import shutil
import stat
import subprocess

IS_WINDOWS = os.name == 'nt'


def _windows_acl_is_private(path):
    """Require a DACL limited to the service account, SYSTEM and Administrators."""
    executable = shutil.which('powershell.exe') or shutil.which('powershell')
    if not executable:
        raise ValueError('Cannot verify Windows ACL for a secret file: PowerShell is unavailable')
    script = r'''
param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = 'Stop'
$acl = Get-Acl -LiteralPath $Path
$current = ([Security.Principal.WindowsIdentity]::GetCurrent()).User.Value
$allowed = @($current, 'S-1-5-18', 'S-1-5-32-544')
try {
    $owner = $acl.Owner | ForEach-Object {
        ([Security.Principal.NTAccount]$_).Translate([Security.Principal.SecurityIdentifier]).Value
    }
} catch {
    exit 3
}
if ($allowed -notcontains $owner) { exit 3 }
foreach ($rule in $acl.Access) {
    if ($rule.AccessControlType -ne 'Allow') { continue }
    try {
        $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    } catch {
        exit 3
    }
    if ($allowed -notcontains $sid) { exit 3 }
}
Write-Output 'PRIVATE'
'''
    try:
        result = subprocess.run(
            [executable, '-NoProfile', '-NonInteractive', '-Command', script, str(path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError('Cannot verify Windows ACL for a secret file') from exc
    if result.returncode != 0 or result.stdout.strip() != 'PRIVATE':
        raise ValueError(
            'Secret file Windows ACL permits identities other than the service '
            'account, SYSTEM or Administrators'
        )


def require_private_file(path, description):
    """Reject group/world access so secrets stay owner-readable only."""
    source = Path(path)
    if source.is_symlink():
        raise ValueError('%s must not be a symbolic link' % description)
    if IS_WINDOWS:
        _windows_acl_is_private(source)
    else:
        file_status = source.stat()
        if not stat.S_ISREG(file_status.st_mode):
            raise ValueError('%s must be a regular file' % description)
        if file_status.st_mode & 0o077:
            raise ValueError('%s must not be accessible to group or other users' % description)
    return source
