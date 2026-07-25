#!/usr/bin/env python3
"""Build the native MoviePilot app.tgz into an fnOS FPK archive."""
from __future__ import annotations

import argparse
import hashlib
import io
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FNOS = ROOT / "fnos"
PLATFORM_RESOURCES = {
    "x86": {
        "sites": "sites.cpython-311-x86_64-linux-gnu.so",
        "runtime": "venv-runtime.tgz",
    },
    "arm": {
        "sites": "sites.cpython-311-aarch64-linux-gnu.so",
        "runtime": "venv-runtime-arm.tgz",
        "node": "node-linux-arm64",
    },
}


def normalize(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    if info.isdir() or info.name == "cmd" or info.name.startswith("cmd/"):
        info.mode = 0o755
    elif info.name == "public/node/bin/node":
        info.mode = 0o755
    else:
        info.mode = 0o644
    return info


def add_path(tar: tarfile.TarFile, path: Path, name: str) -> None:
    tar.add(path, arcname=name, recursive=True, filter=normalize)


def read_manifest() -> dict[str, str]:
    values = {}
    for line in (FNOS / "manifest").read_text(encoding="utf-8-sig").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def patch_resource_auth(data: bytes) -> bytes:
    """Allow cookie-only resources when the native package runs without auth."""
    text = data.decode("utf-8").replace("\r\r\n", "\n").replace("\r\n", "\n")
    needle = (
        "    # 验证并解析资源访问令牌\n"
        "    return __verify_token(token=resource_token, purpose=\"resource\")"
    )
    replacement = (
        "    if os.getenv(\"MOVIEPILOT_NO_AUTH\") == \"1\":\n"
        "        return __create_superuser_token_payload()\n"
        "    # 验证并解析资源访问令牌\n"
        "    return __verify_token(token=resource_token, purpose=\"resource\")"
    )
    if replacement not in text:
        if needle not in text:
            raise SystemExit("MoviePilot resource-token patch target was not found")
        text = text.replace(needle, replacement, 1)
    return text.encode("utf-8")


def prepare_app_tgz(source: Path, include_runtime: bool, platform: str) -> Path:
    """Normalize permissions and place desktop UI and required resources in app.tgz."""
    output = Path(tempfile.mkstemp(suffix=".tgz")[1])
    resource_dir = FNOS / "resources"
    platform_resources = PLATFORM_RESOURCES[platform]
    sites_resource = platform_resources["sites"]
    resources = {
        f"app/helper/{sites_resource}": resource_dir / sites_resource,
        "app/helper/user.sites.v2.bin": resource_dir / "user.sites.v2.bin",
    }
    resources["app/modules/filemanager/storages/local.py"] = resource_dir / "local.py"
    resources["public/no-auth.js"] = resource_dir / "no-auth.js"
    resources["public/service.js"] = resource_dir / "service.js"
    if node_resource := platform_resources.get("node"):
        resources["public/node/bin/node"] = resource_dir / node_resource
    if include_runtime:
        resources["runtime/venv.tgz"] = FNOS / "runtime" / platform_resources["runtime"]
    missing = [str(path) for path in resources.values() if not path.is_file()]
    if missing:
        raise SystemExit(f"MoviePilot runtime resources are missing: {', '.join(missing)}")
    with tarfile.open(source, "r:gz") as archive, tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT) as target:
        for member in archive.getmembers():
            member.name = member.name.lstrip("./")
            if not member.name:
                continue
            if member.name in resources or member.name.startswith("app/helper/sites."):
                continue
            normalize(member)
            if member.isfile():
                data = archive.extractfile(member).read()
                if member.name == "app/core/security.py":
                    data = patch_resource_auth(data)
                member.size = len(data)
                target.addfile(member, io.BytesIO(data))
            else:
                target.addfile(member)
        target.add(FNOS / "ui", arcname="ui", recursive=True, filter=normalize)
        for name, path in resources.items():
            target.add(path, arcname=name, recursive=False, filter=normalize)
    return output


def build(version: str, platform: str, include_runtime: bool, output_name: str | None) -> Path:
    if platform not in PLATFORM_RESOURCES:
        raise SystemExit(f"Unsupported platform: {platform}; choose one of {', '.join(PLATFORM_RESOURCES)}")
    source_app_tgz = ROOT / "app.tgz"
    if not source_app_tgz.is_file():
        raise SystemExit("app.tgz is missing; run scripts/apps/moviepilot/build.sh first")
    app_tgz = prepare_app_tgz(source_app_tgz, include_runtime, platform)
    try:
        out_dir = ROOT / "dist"
        out_dir.mkdir(exist_ok=True)
        out = out_dir / (output_name or f"moviepilot_{version}_{platform}.fpk")
        values = read_manifest()
        values.update(version=version, platform=platform, checksum=hashlib.md5(app_tgz.read_bytes()).hexdigest())
        manifest_data = ("\n".join(f"{key} = {value}" for key, value in values.items()) + "\n").encode("utf-8-sig")
        with tarfile.open(out, "w:gz", format=tarfile.PAX_FORMAT) as tar:
            for name in ("ICON.PNG", "ICON_256.PNG", "LICENSE", "LICENSE.en"):
                add_path(tar, FNOS / name, name)
            info = tarfile.TarInfo("manifest")
            info.size = len(manifest_data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(manifest_data))
            for directory in ("cmd", "config", "wizard"):
                path = FNOS / directory
                if path.exists():
                    add_path(tar, path, directory)
            protocol_file = FNOS / "moviepilot.sc"
            if protocol_file.exists():
                add_path(tar, protocol_file, protocol_file.name)
            add_path(tar, app_tgz, "app.tgz")
        return out
    finally:
        try:
            app_tgz.unlink(missing_ok=True)
        except PermissionError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default=read_manifest().get("version", "0.0.0"))
    parser.add_argument("--platform", default="x86")
    parser.add_argument("--without-runtime", action="store_true")
    parser.add_argument("--output-name")
    args = parser.parse_args()
    print(build(args.version, args.platform, not args.without_runtime, args.output_name))


if __name__ == "__main__":
    main()
