#!/usr/bin/env python3
"""Build the native MoviePilot app.tgz into an fnOS FPK archive."""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import re
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


def patch_no_auth_level(name: str, data: bytes) -> bytes:
    """Keep no-login enabled while reporting the real site-auth level."""
    text = data.decode("utf-8").replace("\r\n", "\n")
    if name == "app/core/security.py":
        old = (
            "    if os.getenv(\"MOVIEPILOT_NO_AUTH\") == \"1\":\n"
            "        return schemas.TokenPayload(sub=0, username=settings.SUPERUSER, "
            "super_user=True, level=99, purpose=\"authentication\")"
        )
        new = (
            "    if os.getenv(\"MOVIEPILOT_NO_AUTH\") == \"1\":\n"
            "        from app.helper.sites import SitesHelper  # noqa\n"
            "        return schemas.TokenPayload(sub=0, username=settings.SUPERUSER, "
            "super_user=True, level=SitesHelper().auth_level, purpose=\"authentication\")"
        )
    elif name == "app/api/endpoints/login.py":
        old = (
            "    if os.getenv(\"MOVIEPILOT_NO_AUTH\") == \"1\":\n"
            "        access_token = security.create_access_token(userid=0, username=settings.SUPERUSER, "
            "super_user=True, expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))\n"
            "        return schemas.Token(access_token=access_token, token_type=\"bearer\", "
            "super_user=True, user_id=0, user_name=settings.SUPERUSER, level=99, permissions={}, wizard=False)"
        )
        new = (
            "    if os.getenv(\"MOVIEPILOT_NO_AUTH\") == \"1\":\n"
            "        level = SitesHelper().auth_level\n"
            "        access_token = security.create_access_token(userid=0, username=settings.SUPERUSER, "
            "super_user=True, expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), level=level)\n"
            "        return schemas.Token(access_token=access_token, token_type=\"bearer\", "
            "super_user=True, user_id=0, user_name=settings.SUPERUSER, level=level, permissions={}, wizard=False)"
        )
    else:
        return data
    if new not in text:
        if old not in text:
            raise SystemExit(f"MoviePilot no-auth level patch target was not found: {name}")
        text = text.replace(old, new, 1)
    return text.encode("utf-8")


def patch_frontend_index(data: bytes) -> bytes:
    """Repair known syntax damage in the MoviePilot frontend release."""
    text = data.decode("utf-8").replace("\r\n", "\n")
    for marker in (
        "const launchThemePalettes = {",
        "if ('caches' in window) {",
        "function syncThemeFavicon(primaryColor) {",
        "revealOriginalLoadingLogo()",
        "const storedLoaderColor =",
        "function syncInitialViewport(force) {",
    ):
        text = re.sub(
            rf"(?m)^([ \t]*//[^\r\n]*?)([ \t]+{re.escape(marker)}[^\r\n]*)$",
            r"\1\n\2",
            text,
        )
    text = re.sub(r"(?m)^([ \t]*//[^\r\n]*?)([ \t]+\})$", r"\1\n\2", text)
    text = re.sub(
        r"(?m)^([ \t]*console\.log\('\[VersionChecker\].*?)(?<!')\)$",
        r"\1')",
        text,
    )
    text = re.sub(r"(?m)^([ \t]*text:[ \t]*'[^'\r\n]*)(,)$", r"\1'\2", text)
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
    resources["public/backend-supervisor.sh"] = resource_dir / "backend-supervisor.sh"
    resources["public/loading-background.jpg"] = resource_dir / "loading-background.jpg"
    if node_resource := platform_resources.get("node"):
        resources["public/node/bin/node"] = resource_dir / node_resource
    if include_runtime:
        resources["runtime/venv.tgz"] = FNOS / "runtime" / platform_resources["runtime"]
    runtime_path = FNOS / "runtime" / platform_resources["runtime"]
    if not runtime_path.is_file():
        raise SystemExit(f"Matching runtime is required for full and split packages: {runtime_path}")
    runtime_metadata = json.dumps({
        "python": "3.11", "platform": platform,
        "sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
    }, sort_keys=True).encode("utf-8")
    missing = [str(path) for path in resources.values() if not path.is_file()]
    if missing:
        raise SystemExit(f"MoviePilot runtime resources are missing: {', '.join(missing)}")
    with tarfile.open(source, "r:gz") as archive, tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT) as target:
        for member in archive.getmembers():
            member.name = member.name.lstrip("./")
            if not member.name:
                continue
            if member.name in resources or member.name == "runtime/expected.json" or member.name.startswith("app/helper/sites."):
                continue
            normalize(member)
            if member.isfile():
                data = archive.extractfile(member).read()
                if member.name == "app/core/security.py":
                    data = patch_resource_auth(data)
                    data = patch_no_auth_level(member.name, data)
                elif member.name == "app/api/endpoints/login.py":
                    data = patch_no_auth_level(member.name, data)
                elif member.name == "public/index.html":
                    data = patch_frontend_index(data)
                member.size = len(data)
                target.addfile(member, io.BytesIO(data))
            else:
                target.addfile(member)
        target.add(FNOS / "ui", arcname="ui", recursive=True, filter=normalize)
        for name, path in resources.items():
            target.add(path, arcname=name, recursive=False, filter=normalize)
        info = tarfile.TarInfo("runtime/expected.json")
        info.size = len(runtime_metadata)
        info.mode = 0o644
        target.addfile(info, io.BytesIO(runtime_metadata))
    return output


def build(version: str, platform: str, include_runtime: bool, output_name: str | None) -> Path:
    if platform not in PLATFORM_RESOURCES:
        raise SystemExit(f"Unsupported platform: {platform}; choose one of {', '.join(PLATFORM_RESOURCES)}")
    source_app_tgz = ROOT / "app.tgz"
    if not source_app_tgz.is_file():
        raise SystemExit("app.tgz is missing; run scripts/apps/moviepilot/build.sh first")
    with tarfile.open(source_app_tgz, "r:gz") as source:
        member = next((m for m in source if m.name.removeprefix("./") == "version.py"), None)
        if member is None:
            raise SystemExit("app.tgz does not declare its upstream version")
        declarations = ast.parse(source.extractfile(member).read().decode("utf-8"))
        source_version = next((ast.literal_eval(node.value).removeprefix("v")
                               for node in declarations.body if isinstance(node, ast.Assign)
                               and any(isinstance(target, ast.Name) and target.id == "APP_VERSION" for target in node.targets)), None)
        if source_version != version.rsplit("-", 1)[0]:
            raise SystemExit(f"FPK version {version} does not match app.tgz upstream {source_version}")
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
