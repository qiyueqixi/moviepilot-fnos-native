#!/usr/bin/env python3
"""Replace native x86 wheels in the fnOS Python 3.11 runtime with ARM64 wheels."""
from __future__ import annotations

import argparse
import csv
import email
import os
import shutil
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "fnos" / "runtime" / "venv-runtime.tgz"
DEFAULT_WHEELS = ROOT / ".tmp" / "arm-wheels"
DEFAULT_OUTPUT = ROOT / "fnos" / "runtime" / "venv-runtime-arm.tgz"


def normalized_name(value: str) -> str:
    return value.lower().replace("-", "_").replace(".", "_")


def is_elf(path: Path) -> bool:
    try:
        with path.open("rb") as stream:
            return stream.read(4) == b"\x7fELF"
    except OSError:
        return False


def elf_machine(path: Path) -> int:
    with path.open("rb") as stream:
        header = stream.read(20)
    if len(header) < 20 or header[:4] != b"\x7fELF":
        raise ValueError(f"Not an ELF file: {path}")
    byteorder = "little" if header[5] == 1 else "big"
    return int.from_bytes(header[18:20], byteorder)


def wheel_identity(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as wheel:
        metadata_name = next(name for name in wheel.namelist() if name.endswith(".dist-info/METADATA"))
        metadata = email.message_from_bytes(wheel.read(metadata_name))
    return normalized_name(metadata["Name"]), metadata["Version"]


def native_distributions(site_packages: Path) -> dict[tuple[str, str], Path]:
    elf_paths = {path.resolve() for path in site_packages.rglob("*") if path.is_file() and is_elf(path)}
    result: dict[tuple[str, str], Path] = {}
    owned: set[Path] = set()
    for dist_info in site_packages.glob("*.dist-info"):
        record = dist_info / "RECORD"
        metadata_file = dist_info / "METADATA"
        if not record.is_file() or not metadata_file.is_file():
            continue
        metadata = email.message_from_bytes(metadata_file.read_bytes())
        with record.open(encoding="utf-8", errors="replace", newline="") as stream:
            paths = {(site_packages / row[0]).resolve() for row in csv.reader(stream) if row}
        native_files = paths & elf_paths
        if native_files:
            key = (normalized_name(metadata["Name"]), metadata["Version"])
            result[key] = dist_info
            owned.update(native_files)
    unowned = sorted(str(path) for path in elf_paths - owned)
    if unowned:
        raise RuntimeError("Native files are not owned by a wheel:\n" + "\n".join(unowned))
    return result


def remove_distribution_files(site_packages: Path, dist_info: Path) -> None:
    venv = site_packages.parents[2].resolve()
    with (dist_info / "RECORD").open(encoding="utf-8", errors="replace", newline="") as stream:
        paths = [(site_packages / row[0]).resolve() for row in csv.reader(stream) if row]
    for path in paths:
        try:
            path.relative_to(venv)
        except ValueError as exc:
            raise RuntimeError(f"Wheel RECORD escapes the runtime: {path}") from exc
        # Existing console scripts are architecture independent and already have the correct layout.
        if path.is_relative_to(site_packages) and (path.is_file() or path.is_symlink()):
            path.unlink()
    for directory in sorted({path.parent for path in paths}, key=lambda item: len(item.parts), reverse=True):
        if directory.is_relative_to(site_packages) and directory.exists():
            try:
                directory.rmdir()
            except OSError:
                pass


def install_wheel(wheel_path: Path, site_packages: Path) -> None:
    with zipfile.ZipFile(wheel_path) as wheel:
        for member in wheel.infolist():
            name = member.filename
            parts = Path(name).parts
            if ".data" in name:
                data_index = next((index for index, part in enumerate(parts) if part.endswith(".data")), None)
                if data_index is None or len(parts) <= data_index + 2:
                    continue
                scheme = parts[data_index + 1]
                if scheme not in {"purelib", "platlib"}:
                    continue
                relative = Path(*parts[data_index + 2 :])
            else:
                relative = Path(*parts)
            destination = site_packages / relative
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with wheel.open(member) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)


def normalize_tar_info(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    if info.isdir() or info.issym() or info.name.startswith("venv/bin/"):
        info.mode = 0o755
    else:
        info.mode = 0o644
    return info


def build(source: Path, wheels_dir: Path, output: Path) -> None:
    wheels = {wheel_identity(path): path for path in wheels_dir.glob("*.whl")}
    with tempfile.TemporaryDirectory(prefix="moviepilot-arm-runtime-") as temp:
        workspace = Path(temp)
        with tarfile.open(source, "r:gz") as archive:
            # A venv intentionally links bin/python3 to fnOS /usr/bin/python3.
            archive.extractall(workspace, filter="fully_trusted")
        venv = workspace / "venv"
        site_packages = venv / "lib" / "python3.11" / "site-packages"
        native = native_distributions(site_packages)
        missing = sorted(f"{name}=={version}" for name, version in native if (name, version) not in wheels)
        if missing:
            raise RuntimeError("Missing ARM64 wheels:\n" + "\n".join(missing))
        for identity, dist_info in sorted(native.items()):
            remove_distribution_files(site_packages, dist_info)
            install_wheel(wheels[identity], site_packages)

        wrong_arch = []
        elf_count = 0
        for path in venv.rglob("*"):
            if path.is_file() and is_elf(path):
                elf_count += 1
                if elf_machine(path) != 183:
                    wrong_arch.append(str(path.relative_to(venv)))
        if wrong_arch:
            raise RuntimeError("Non-AArch64 ELF files remain:\n" + "\n".join(wrong_arch))

        output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output, "w:gz", format=tarfile.PAX_FORMAT, compresslevel=6) as archive:
            archive.add(venv, arcname="venv", recursive=True, filter=normalize_tar_info)
        print(f"Built {output} with {len(native)} replaced distributions and {elf_count} AArch64 ELF files")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--wheels", type=Path, default=DEFAULT_WHEELS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.source.resolve(), args.wheels.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
