#!/usr/bin/env bash
# Explicit administrator operation; never generates or installs a trusted certificate.
set -euo pipefail
: "${1:?Usage: prepare-tls.sh /absolute/fullchain.pem /absolute/privkey.pem [image] [tls-volume] [CA-file]}"
: "${2:?An absolute private-key path is required}"
cert_file="$1"
key_file="$2"
image="${3:-hyx-kms-py:latest}"
tls_volume="${4:-HYX-KMS-PY-tls}"
for selected_file in "$cert_file" "$key_file"; do
  [[ "$selected_file" = /* && -f "$selected_file" ]] || { echo "Existing absolute file paths are required" >&2; exit 64; }
done
docker_args=(run --rm --network none --user root --entrypoint python3)
if [[ -n "${5:-}" ]]; then
  [[ "$5" = /* && -f "$5" ]] || exit 64
  docker_args+=(-v "$5:/input-ca.pem:ro")
fi
docker "${docker_args[@]}" \
  -v "$cert_file:/input-cert.pem:ro" -v "$key_file:/input-key.pem:ro" \
  -v "$tls_volume:/run/tls" "$image" -c '
import os,pwd,shutil,ssl,tempfile,uuid
from pathlib import Path
context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain("/input-cert.pem","/input-key.pem",password=lambda: "")
if Path("/input-ca.pem").exists():
    ssl.create_default_context(cafile="/input-ca.pem")
identity=pwd.getpwnam("hyx")
root=Path("/run/tls")
staging=Path(tempfile.mkdtemp(prefix="cert-",dir=root))
link=root / (".current-"+uuid.uuid4().hex)
try:
    for source,name in (("/input-cert.pem","fullchain.pem"),("/input-key.pem","privkey.pem"),("/input-ca.pem","ca.pem")):
        if not Path(source).exists(): continue
        target=staging/name
        shutil.copyfile(source,target)
        os.chown(target,identity.pw_uid,identity.pw_gid)
        target.chmod(0o600)
    os.chown(staging,identity.pw_uid,identity.pw_gid)
    staging.chmod(0o700)
    link.symlink_to(staging.name)
    os.replace(link,root/"current")
except BaseException:
    link.unlink(missing_ok=True)
    shutil.rmtree(staging)
    raise
'
