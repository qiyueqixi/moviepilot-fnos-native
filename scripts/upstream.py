#!/usr/bin/env python3
"""Resolve upstream releases and assemble verified inputs for native FPK builds."""
from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PROXY_SOURCE_FILES = (
    "app/core/config.py",
    "app/utils/http.py",
    "app/modules/bangumi/bangumi.py",
)


def version_tuple(tag: str) -> tuple[int, ...]:
    if not re.fullmatch(r"v?\d+\.\d+\.\d+", tag):
        raise ValueError(f"Not a stable upstream version: {tag}")
    return tuple(map(int, tag.removeprefix("v").split(".")))


def github_json(route: str):
    # gh handles private release authentication without putting tokens in URLs.
    result = subprocess.run(["gh", "api", route], check=True, capture_output=True, text=True, encoding="utf-8")
    return json.loads(result.stdout)


def select_release(releases: list[dict], major: int) -> dict:
    candidates = []
    for release in releases:
        tag = release.get("tag_name", "")
        if release.get("draft") or release.get("prerelease"):
            continue
        try:
            version = version_tuple(tag)
        except ValueError:
            continue
        if version[0] == major:
            candidates.append((version, release))
    if not candidates:
        raise RuntimeError(f"No stable release found for the supported v{major} series")
    return max(candidates, key=lambda item: item[0])[1]


def source_versions(source: Path) -> tuple[str, str]:
    values = {}
    for statement in ast.parse((source / "version.py").read_text(encoding="utf-8")).body:
        if isinstance(statement, ast.Assign):
            for name in statement.targets:
                if isinstance(name, ast.Name) and name.id in {"APP_VERSION", "FRONTEND_VERSION"}:
                    values[name.id] = ast.literal_eval(statement.value)
    backend = values["APP_VERSION"].removeprefix("v")
    frontend = values["FRONTEND_VERSION"].removeprefix("v")
    version_tuple(backend)
    version_tuple(frontend)
    return backend, frontend


def safe_unpack_source(data: bytes, destination: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            parts = member.name.split("/")[1:]
            if not parts or not any(parts):
                continue
            if any(part in {"..", "."} for part in parts) or member.issym() or member.islnk():
                raise ValueError(f"Unexpected source archive entry: {member.name}")
            member.name = "/".join(parts)
            archive.extract(member, destination, filter="data")


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "moviepilot-fnos-builder"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def release_assets_valid(release: dict, version: str, revision: int) -> bool:
    names = {asset["name"] for asset in release.get("assets", []) if asset.get("state") == "uploaded"}
    required = {f"moviepilot_{version}-{revision}_{arch}{suffix}.fpk"
                for arch in ("x86", "arm") for suffix in ("", "_installer")}
    required.add("SHA256SUMS.txt")
    required.update(f"moviepilot-runtime-{arch}-python311.tgz" for arch in ("x86", "arm"))
    return required <= names


def resolve(config: dict, requested: str | None, releases: list[dict]) -> dict:
    selected = select_release(releases, config["supported_major"]) if not requested else {"tag_name": requested}
    version = selected["tag_name"].removeprefix("v")
    if version_tuple(version)[0] != config["supported_major"]:
        raise ValueError(f"v{version} requires a separate major-version migration; this build tracks v{config['supported_major']}")
    revision = config["native_revision"]
    latest = select_release(releases, max(version_tuple(r["tag_name"])[0] for r in releases
                            if re.fullmatch(r"v?\d+\.\d+\.\d+", r.get("tag_name", ""))
                            and not r.get("prerelease") and not r.get("draft")))["tag_name"]
    return {"version": version, "fpk_version": f"{version}-{revision}",
            "release_tag": f"v{version}-fnos.{revision}", "latest_upstream": latest,
            "python": config["python"], "native_revision": revision}


def check(args, config):
    releases = github_json(f"repos/{config['repository']}/releases?per_page=100")
    plan = resolve(config, args.version, releases)
    target = os.environ.get("GITHUB_REPOSITORY", "qiyueqixi/moviepilot-fnos-native")
    existing = [r for r in github_json(f"repos/{target}/releases?per_page=100")
                if r["tag_name"] == plan["release_tag"]]
    plan["build"] = bool(args.force or not existing or not release_assets_valid(existing[0], plan["version"], config["native_revision"]))
    Path(args.plan).parent.mkdir(parents=True, exist_ok=True)
    Path(args.plan).write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            for key, value in plan.items():
                stream.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(f"上游最新：{plan['latest_upstream']}；当前兼容系列：v{config['supported_major']}；目标 FPK：{plan['fpk_version']}。\n\n")
            stream.write("已有完整产物，本次跳过。\n" if not plan["build"] else "将重新校验补丁和依赖并生成 FPK，完成后由用户手动安装。\n")
    print(json.dumps(plan, indent=2))


def prepare(args, config):
    version = args.version.removeprefix("v")
    if version_tuple(version)[0] != config["supported_major"]:
        raise ValueError("Unsupported major version")
    destination = Path(args.source).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"Source directory must be empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    data = download(f"https://codeload.github.com/{config['repository']}/tar.gz/refs/tags/v{version}")
    safe_unpack_source(data, destination)
    backend, frontend = source_versions(destination)
    if backend != version:
        raise ValueError(f"Source version mismatch: {backend} != {version}")
    front_release = github_json(f"repos/{config['frontend_repository']}/releases/tags/v{frontend}")
    assets = [a for a in front_release["assets"] if a["name"] == "dist.zip"]
    if len(assets) != 1:
        raise ValueError(f"Missing frontend dist.zip for v{frontend}")
    metadata = {"version": backend, "frontend": frontend, "source_sha256": hashlib.sha256(data).hexdigest(),
                "frontend_url": assets[0]["browser_download_url"], "python": config["python"],
                "proxy_defaults_sha256": {name: hashlib.sha256((destination / name).read_bytes()).hexdigest()
                                          for name in PROXY_SOURCE_FILES}}
    (destination / "native-upstream.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))


def verify_checksum(path: Path, checksums: Path) -> None:
    entries = {}
    for line in checksums.read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            entries[name.lstrip("*")] = digest
    if hashlib.sha256(path.read_bytes()).hexdigest() != entries.get(path.name):
        raise ValueError(f"Bootstrap SHA-256 mismatch: {path.name}")


def bootstrap(args, config):
    arch = args.platform
    tag = config["bootstrap_tag"]
    repository = os.environ.get("GITHUB_REPOSITORY", "qiyueqixi/moviepilot-fnos-native")
    release = github_json(f"repos/{repository}/releases/tags/{tag}")
    package = next(a["name"] for a in release["assets"]
                   if a["name"].endswith(f"_{arch}_installer.fpk"))
    with tempfile.TemporaryDirectory(prefix="fnos-bootstrap-") as temp:
        directory = Path(temp)
        subprocess.run(["gh", "release", "download", tag, "--repo", repository, "--dir", temp,
                        "--pattern", package, "--pattern", "SHA256SUMS.txt"], check=True)
        verify_checksum(directory / package, directory / "SHA256SUMS.txt")
        resource_dir = ROOT / "fnos/resources"
        resource_dir.mkdir(parents=True, exist_ok=True)
        machine = "x86_64" if arch == "x86" else "aarch64"
        python_tag = config["python"].replace(".", "")
        site = f"sites.cpython-{python_tag}-{machine}-linux-gnu.so"
        needed = {f"app/helper/{site}": site, "app/helper/user.sites.v2.bin": "user.sites.v2.bin"}
        if arch == "arm":
            needed["public/node/bin/node"] = "node-linux-arm64"
        with tarfile.open(directory / package, "r:gz") as outer:
            with tarfile.open(fileobj=outer.extractfile("app.tgz"), mode="r|gz") as inner:
                found = set()
                for member in inner:
                    name = member.name.removeprefix("./")
                    if name in needed:
                        (resource_dir / needed[name]).write_bytes(inner.extractfile(member).read())
                        found.add(name)
        if found != set(needed):
            raise ValueError(f"Bootstrap lacks matching runtime resources: {set(needed) - found}")
    print(f"Verified bootstrap resources for {arch} / Python {config['python']}")


def verify_package(path: Path, expected_version: str) -> None:
    arch = "arm" if "_arm" in path.name else "x86"
    with tarfile.open(path, "r:gz") as outer:
        manifest = outer.extractfile("manifest").read().decode("utf-8-sig")
        values = dict((k.strip(), v.strip()) for k, v in (line.split("=", 1) for line in manifest.splitlines() if "=" in line))
        if values["version"] != expected_version or values["platform"] != arch:
            raise ValueError(f"Wrong FPK metadata: {path.name}")
        data = outer.extractfile("app.tgz").read()
        if hashlib.md5(data).hexdigest() != values["checksum"]:
            raise ValueError(f"Invalid app.tgz checksum: {path.name}")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as inner:
        names = {member.name.removeprefix("./"): member for member in inner}
        if ("runtime/venv.tgz" in names) == ("_installer" in path.name):
            raise ValueError(f"Unexpected runtime layout: {path.name}")
        metadata = json.loads(inner.extractfile(names["runtime/expected.json"]).read())
        runtime = path.parent / f"moviepilot-runtime-{arch}-python311.tgz"
        if metadata["platform"] != arch or metadata["sha256"] != hashlib.sha256(runtime.read_bytes()).hexdigest():
            raise ValueError(f"Runtime does not match FPK: {path.name}")
        if "runtime/venv.tgz" in names and hashlib.sha256(inner.extractfile(names["runtime/venv.tgz"]).read()).hexdigest() != metadata["sha256"]:
            raise ValueError(f"Bundled runtime does not match FPK: {path.name}")
        version_code = inner.extractfile(names["version.py"]).read().decode()
        declared = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(version_code).body
                    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "APP_VERSION"}
        if declared.get("APP_VERSION", "").removeprefix("v") != expected_version.rsplit("-", 1)[0]:
            raise ValueError(f"FPK contains a different upstream version: {path.name}")
        provenance = json.loads(inner.extractfile(names["native-upstream.json"]).read())
        for name in PROXY_SOURCE_FILES:
            digest = hashlib.sha256(inner.extractfile(names[name]).read()).hexdigest()
            if digest != provenance["proxy_defaults_sha256"][name]:
                raise ValueError(f"Upstream proxy behavior was modified: {name}")
        for name in ["public/no-auth.js", "public/service.js", "app/modules/filemanager/storages/local.py"]:
            expected = ROOT / "fnos/resources" / Path(name).name
            if inner.extractfile(names[name]).read() != expected.read_bytes():
                raise ValueError(f"Native adapter missing: {name}")
        sites = [n for n in names if n.startswith("app/helper/sites.")]
        if len(sites) != 1:
            raise ValueError("FPK must have exactly one sites extension")
        for name in [sites[0], "public/node/bin/node"]:
            header = inner.extractfile(names[name]).read(20)
            if header[:4] != b"\x7fELF" or int.from_bytes(header[18:20], "little") != (183 if arch == "arm" else 62):
                raise ValueError(f"Wrong ELF architecture: {name}")
        html = inner.extractfile(names["public/index.html"]).read().decode("utf-8")
        if "no-auth.js" not in html:
            raise ValueError("Native bootstrap script missing from HTML")
        with tempfile.TemporaryDirectory() as temp:
            for number, (attrs, script) in enumerate(re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.DOTALL)):
                if "src=" in attrs or not script.strip():
                    continue
                target = Path(temp) / f"inline-{number}.js"
                target.write_text(script, encoding="utf-8")
                subprocess.run(["node", "--check", str(target)], check=True)
    print(f"Verified {path.name}")


def verify(args, config):
    directory = Path(args.directory)
    paths = sorted(directory.glob(f"moviepilot_{args.version}_*.fpk"))
    expected = 2 if args.platform else 4
    if len(paths) != expected:
        raise ValueError(f"Expected {expected} FPK files, got {len(paths)}")
    for path in paths:
        verify_package(path, args.version)
    assets = paths + sorted(directory.glob("moviepilot-runtime-*-python311.tgz"))
    lines = [f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}" for path in assets]
    (directory / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def notes(args, config):
    directory = Path(args.directory)
    for name in ("OFFLINE_INSTALL_CN.md", "OFFLINE_INSTALL_ARM_CN.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        text = re.sub(r"\b\d+\.\d+\.\d+-\d+\b", args.version, text)
        (directory / name).write_text(text, encoding="utf-8")
    text = (
        f"# MoviePilot fnOS {args.version}\n\n"
        "自动构建已通过飞牛补丁、依赖解析、目标 Python 编译和安装包内容检查。\n\n"
        "- 推荐下载对应架构的完整 FPK，在飞牛应用中心手动升级并保留数据。\n"
        "- 使用拆分包时，必须同时下载本草稿中的对应架构 Python 3.11 运行时，上传到应用文件的 moviepilot/runtime 后启动。\n"
        "- 上游源码、前端版本及源码校验值见 upstream-x86.json / upstream-arm.json；附件校验值见 SHA256SUMS.txt。\n"
        "- 保留飞牛网关、免登录、站点等级和目录授权适配，自动构建不会操作你的 NAS。\n\n"
        f"当前自动跟踪 v{config['supported_major']} 稳定系列。上游 V3 需要 Python 3.14 和独立迁移适配，不会混入本系列。\n\n"
        "本草稿尚未完成新安装和保留数据升级的 fnOS 实机验收，验收后再发布正式 Release。\n"
    )
    (directory / "RELEASE_NOTES.md").write_text(text, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check")
    p.add_argument("--version")
    p.add_argument("--force", action="store_true")
    p.add_argument("--plan", default=".tmp/upstream-plan.json")
    p = sub.add_parser("prepare")
    p.add_argument("--version", required=True)
    p.add_argument("--source", default=".tmp/auto-source")
    p = sub.add_parser("bootstrap")
    p.add_argument("--platform", choices=["x86", "arm"], required=True)
    p = sub.add_parser("verify")
    p.add_argument("--version", required=True)
    p.add_argument("--platform", choices=["x86", "arm"])
    p.add_argument("--directory", default="dist")
    p = sub.add_parser("notes")
    p.add_argument("--version", required=True)
    p.add_argument("--directory", default="dist")
    args = parser.parse_args()
    config = json.loads((ROOT / "upstream.json").read_text(encoding="utf-8"))
    globals()[args.command](args, config)


if __name__ == "__main__":
    main()
