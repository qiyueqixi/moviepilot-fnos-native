import os
import shutil
from pathlib import Path
from typing import Optional, List

from app import schemas
from app.core.config import global_vars
from app.helper.directory import DirectoryHelper
from app.log import logger
from app.modules.filemanager.storages import StorageBase, transfer_process
from app.schemas.types import StorageSchema
from app.utils.system import SystemUtils


class LocalStorage(StorageBase):
    """
    本地文件操作
    """

    # 存储类型
    schema = StorageSchema.Local
    # 支持的整理方式
    transtype = {
        "copy": "复制",
        "move": "移动",
        "link": "硬链接",
        "softlink": "软链接"
    }

    # 文件块大小，默认10MB
    chunk_size = 10 * 1024 * 1024

    @staticmethod
    def __allowed_roots() -> tuple[Path, ...]:
        raw_paths = ""
        paths_file = os.getenv("MOVIEPILOT_ALLOWED_PATHS_FILE", "")
        if paths_file:
            try:
                raw_paths = Path(paths_file).read_text(encoding="utf-8").strip()
            except OSError:
                return ()
        else:
            raw_paths = os.getenv("TRIM_DATA_ACCESSIBLE_PATHS", "").strip()

        roots = []
        for value in raw_paths.split(":"):
            if not value:
                continue
            try:
                root = Path(value).resolve(strict=False)
            except (OSError, RuntimeError):
                continue
            if root not in roots:
                roots.append(root)
        return tuple(roots)

    @classmethod
    def __is_allowed(cls, path: str | Path) -> bool:
        try:
            candidate = Path(path).resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError):
            return False
        return any(
            candidate == root or root in candidate.parents
            for root in cls.__allowed_roots()
        )

    def init_storage(self):
        """
        初始化
        """
        pass

    def check(self) -> bool:
        """
        检查存储是否可用
        """
        return True

    def __get_fileitem(self, path: Path) -> schemas.FileItem:
        """
        获取文件项
        """
        return schemas.FileItem(
            storage=self.schema.value,
            type="file",
            path=path.as_posix(),
            name=path.name,
            basename=path.stem,
            extension=path.suffix[1:],
            size=path.stat().st_size,
            modify_time=path.stat().st_mtime,
        )

    def __get_diritem(self, path: Path) -> schemas.FileItem:
        """
        获取目录项
        """
        return schemas.FileItem(
            storage=self.schema.value,
            type="dir",
            path=path.as_posix() + "/",
            name=path.name,
            basename=path.stem,
            modify_time=path.stat().st_mtime,
        )

    def list(self, fileitem: schemas.FileItem) -> List[schemas.FileItem]:
        """
        浏览文件
        """
        # 返回结果
        ret_items = []
        path = fileitem.path
        if not fileitem.path or fileitem.path == "/":
            for root in self.__allowed_roots():
                if root.is_dir():
                    ret_items.append(self.__get_diritem(root))
            return ret_items
        else:
            if SystemUtils.is_windows():
                path = path.lstrip("/")
            elif not path.startswith("/"):
                path = "/" + path

        if not self.__is_allowed(path):
            return []

        # 遍历目录
        path_obj = Path(path)
        if not path_obj.exists():
            logger.warn(f"【本地】目录不存在：{path}")
            return []

        # 如果是文件
        if path_obj.is_file():
            ret_items.append(self.__get_fileitem(path_obj))
            return ret_items

        # 扁历所有目录
        for item in SystemUtils.list_sub_directory(path_obj):
            ret_items.append(self.__get_diritem(item))

        # 遍历所有文件，不含子目录
        for item in SystemUtils.list_sub_file(path_obj):
            ret_items.append(self.__get_fileitem(item))
        return ret_items

    def create_folder(self, fileitem: schemas.FileItem, name: str) -> Optional[schemas.FileItem]:
        """
        创建目录
        :param fileitem: 父目录
        :param name: 目录名
        """
        if not fileitem.path:
            return None
        path_obj = Path(fileitem.path) / name
        if not self.__is_allowed(fileitem.path) or not self.__is_allowed(path_obj):
            return None
        if not path_obj.exists():
            path_obj.mkdir(parents=True, exist_ok=True)
        return self.__get_diritem(path_obj)

    def get_folder(self, path: Path) -> Optional[schemas.FileItem]:
        """
        获取目录
        """
        if not self.__is_allowed(path):
            return None
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        return self.__get_diritem(path)

    def get_item(self, path: Path) -> Optional[schemas.FileItem]:
        """
        获取文件或目录，不存在返回None
        """
        if not self.__is_allowed(path) or not path.exists():
            return None
        if path.is_file():
            return self.__get_fileitem(path)
        return self.__get_diritem(path)

    def detail(self, fileitem: schemas.FileItem) -> Optional[schemas.FileItem]:
        """
        获取文件详情
        """
        path_obj = Path(fileitem.path)
        if not self.__is_allowed(path_obj) or not path_obj.exists():
            return None
        return self.__get_fileitem(path_obj)

    def delete(self, fileitem: schemas.FileItem) -> bool:
        """
        删除文件
        """
        if not fileitem.path:
            return False
        path_obj = Path(fileitem.path)
        if not self.__is_allowed(path_obj):
            return False
        if not path_obj.exists():
            return True
        try:
            if path_obj.is_file():
                path_obj.unlink()
            else:
                shutil.rmtree(path_obj, ignore_errors=True)
        except Exception as e:
            logger.error(f"【本地】删除文件失败：{e}")
            return False
        return True

    def rename(self, fileitem: schemas.FileItem, name: str) -> bool:
        """
        重命名文件
        """
        path_obj = Path(fileitem.path)
        target_path = path_obj.parent / name
        if not self.__is_allowed(path_obj) or not self.__is_allowed(target_path):
            return False
        if not path_obj.exists():
            return False
        try:
            path_obj.rename(path_obj.parent / name)
        except Exception as e:
            logger.error(f"【本地】重命名文件失败：{e}")
            return False
        return True

    def download(self, fileitem: schemas.FileItem, path: Path = None) -> Optional[Path]:
        """
        下载文件
        """
        source = Path(fileitem.path)
        return source if self.__is_allowed(source) else None

    def _copy_with_progress(self, src: Path, dest: Path):
        """
        分块复制文件并回调进度
        """
        total_size = src.stat().st_size
        copied_size = 0
        progress_callback = transfer_process(src.as_posix())
        try:
            with open(src, "rb") as fsrc, open(dest, "wb") as fdst:
                while True:
                    if global_vars.is_transfer_stopped(src.as_posix()):
                        logger.info(f"【本地】{src} 复制已取消！")
                        return False
                    buf = fsrc.read(self.chunk_size)
                    if not buf:
                        break
                    fdst.write(buf)
                    copied_size += len(buf)
                    # 更新进度
                    if progress_callback:
                        percent = copied_size / total_size * 100
                        progress_callback(percent)
            # 保留文件时间戳、权限等信息
            shutil.copystat(src, dest)
            return True
        except Exception as e:
            logger.error(f"【本地】复制文件 {src} 失败：{e}")
            return False
        finally:
            progress_callback(100)

    def upload(
            self,
            fileitem: schemas.FileItem,
            path: Path,
            new_name: Optional[str] = None
    ) -> Optional[schemas.FileItem]:
        """
        上传文件（带进度）
        """
        try:
            dir_path = Path(fileitem.path)
            target_path = dir_path / (new_name or path.name)
            if not self.__is_allowed(dir_path) or not self.__is_allowed(target_path):
                return None
            if self._copy_with_progress(path, target_path):
                # 上传删除源文件
                path.unlink()
                return self.get_item(target_path)
        except Exception as err:
            logger.error(f"【本地】移动文件失败：{err}")
        return None

    @staticmethod
    def __should_show_progress(src: Path, dest: Path):
        """
        是否显示进度条
        """
        src_isnetwork = SystemUtils.is_network_filesystem(src)
        dest_isnetwork = SystemUtils.is_network_filesystem(dest)
        if src_isnetwork and dest_isnetwork and SystemUtils.is_same_disk(src, dest):
            return True
        return False

    def copy(
            self,
            fileitem: schemas.FileItem,
            path: Path,
            new_name: str
    ) -> bool:
        """
        复制文件（带进度）
        """
        try:
            src = Path(fileitem.path)
            dest = path / new_name
            if not self.__is_allowed(src) or not self.__is_allowed(dest):
                return False
            if self.__should_show_progress(src, dest):
                if self._copy_with_progress(src, dest):
                    return True
            else:
                code, message = SystemUtils.copy(src, dest)
                if code == 0:
                    return True
                else:
                    logger.error(f"【本地】复制文件失败：{message}")
        except Exception as err:
            logger.error(f"【本地】复制文件失败：{err}")
        return False

    def move(
            self,
            fileitem: schemas.FileItem,
            path: Path,
            new_name: str
    ) -> bool:
        """
        移动文件（带进度）
        """
        try:
            src = Path(fileitem.path)
            dest = path / new_name
            if not self.__is_allowed(src) or not self.__is_allowed(dest):
                return False
            if src == dest:
                # 目标和源文件相同，直接返回成功，不做任何操作
                return True
            if self.__should_show_progress(src, dest):
                if self._copy_with_progress(src, dest):
                    # 复制成功删除源文件
                    src.unlink()
                    return True
            else:
                code, message = SystemUtils.move(src, dest)
                if code == 0:
                    return True
                else:
                    logger.error(f"【本地】移动文件失败：{message}")
        except Exception as err:
            logger.error(f"【本地】移动文件失败：{err}")
        return False

    def link(self, fileitem: schemas.FileItem, target_file: Path) -> bool:
        """
        硬链接文件
        """
        file_path = Path(fileitem.path)
        if not self.__is_allowed(file_path) or not self.__is_allowed(target_file):
            return False
        code, message = SystemUtils.link(file_path, target_file)
        if code != 0:
            logger.error(f"【本地】硬链接文件失败：{message}")
            return False
        return True

    def softlink(self, fileitem: schemas.FileItem, target_file: Path) -> bool:
        """
        软链接文件
        """
        file_path = Path(fileitem.path)
        if not self.__is_allowed(file_path) or not self.__is_allowed(target_file):
            return False
        code, message = SystemUtils.softlink(file_path, target_file)
        if code != 0:
            logger.error(f"【本地】软链接文件失败：{message}")
            return False
        return True

    def usage(self) -> Optional[schemas.StorageUsage]:
        """
        存储使用情况
        """
        directory_helper = DirectoryHelper()
        total_storage, free_storage = SystemUtils.space_usage(
            [Path(d.download_path) for d in directory_helper.get_local_download_dirs()
             if d.download_path and self.__is_allowed(d.download_path)] +
            [Path(d.library_path) for d in directory_helper.get_local_library_dirs()
             if d.library_path and self.__is_allowed(d.library_path)]
        )
        return schemas.StorageUsage(
            total=total_storage,
            available=free_storage
        )
