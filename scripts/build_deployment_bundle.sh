#!/bin/sh
# Assemble one offline bundle containing the image, provisioning scripts, and docs.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
version=$(sed -n '1{s/\r$//;p;}' "$root/VERSION")
printf '%s\n' "$version" | grep -Eq '^[0-9A-Za-z][0-9A-Za-z._-]*$' || {
    echo "VERSION must start with a single release identifier" >&2
    exit 65
}
platform=${PLATFORM:-linux-amd64}
image_name="hyx-kms-py-${version}-${platform}"
image_archive="$root/dist/$image_name.tar"
image_checksum="$image_archive.sha256"
bundle_name="hyx-kms-py-${version}-${platform}-deployment"
bundle_archive="$root/dist/$bundle_name.tar.gz"
bundle_metadata="$root/dist/hyx-kms-py-${version}-linux-amd64.bundle.json"
sbom="$root/dist/hyx-kms-py-${version}-sbom.cdx.json"

for path in "$image_archive" "$image_checksum" "$bundle_metadata" "$sbom"; do
    [ -f "$path" ] || {
        echo "Required release artifact is missing: $path" >&2
        exit 66
    }
done

stage=$(mktemp -d "${TMPDIR:-/tmp}/hyx-kms-release.XXXXXX")
cleanup() {
    rm -rf "$stage"
}
trap cleanup EXIT HUP INT TERM

package_root="$stage/$bundle_name"
install -d "$package_root/image" "$package_root/docker/hyx-kms-py" "$package_root/docs"

install -m 0644 \
    "$image_archive" \
    "$image_checksum" \
    "$bundle_metadata" \
    "$sbom" \
    "$package_root/image/"
install -m 0644 "$root/VERSION" "$root/LICENSE" "$root/CHANGELOG.md" "$package_root/"
install -m 0644 "$root/docker/hyx-kms-py/DEPLOYMENT.md" "$package_root/DEPLOYMENT.md"
install -m 0644 "$root/docs/"*.md "$package_root/docs/"
install -m 0644 "$root/docs/"*.csv "$package_root/docs/"
install -m 0755 \
    "$root/docker/hyx-kms-py/prepare-tls.sh" \
    "$root/docker/hyx-kms-py/run.sh" \
    "$package_root/docker/hyx-kms-py/"

(
    cd "$package_root"
    find . -type f ! -name SHA256SUMS -print | LC_ALL=C sort |
        while IFS= read -r file; do
            if command -v sha256sum >/dev/null 2>&1; then
                sha256sum "$file"
            else
                shasum -a 256 "$file"
            fi
        done > SHA256SUMS
)

install -d "$root/dist"
tar -C "$stage" -czf "$bundle_archive" "$bundle_name"
if command -v sha256sum >/dev/null 2>&1; then
    (cd "$root/dist" && sha256sum "$bundle_name.tar.gz") > "$bundle_archive.sha256"
else
    (cd "$root/dist" && shasum -a 256 "$bundle_name.tar.gz") > "$bundle_archive.sha256"
fi

printf '%s\n' "$bundle_archive"
