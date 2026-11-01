# MoviePilot 飞牛 fnOS 原生 FPK

本项目将 MoviePilot 改造成飞牛 fnOS 原生应用，不使用 Docker。目前提供 x86_64 和 ARM64 两种架构。

## 功能

- 使用 fnOS 统一网关 `/app/moviepilot/`，不向局域网开放独立网页端口。
- 从飞牛桌面以内嵌页面打开，并启用免登录模式。
- 免登录不跳过 MoviePilot 站点认证；未认证时可从右上角选择认证站点并填写参数。
- 使用 fnOS 内置 Python 3.11，完整包内置依赖，安装时不联网下载。
- 向导可预填 MoviePilot 原生代理设置，模块沿用上游默认代理逻辑；提供配置、日志、导出和运行时目录。
- 文件管理器只显示 fnOS 明确授权给应用的目录。
- 启动检查页显示实时初始化进度和错误摘要，并支持自定义背景。
- 卸载时选择“删除全部数据”会清理 MoviePilot 对应的应用目录。

## 安装

- x86 用户参阅 [OFFLINE_INSTALL_CN.md](OFFLINE_INSTALL_CN.md)。
- ARM64 用户参阅 [OFFLINE_INSTALL_ARM_CN.md](OFFLINE_INSTALL_ARM_CN.md)。
- 从 Docker 版迁移数据参阅 [MIGRATION_DOCKER_TO_FNOS_CN.md](MIGRATION_DOCKER_TO_FNOS_CN.md)。
- 维护、适配和发布参阅 [DEVELOPMENT_CN.md](DEVELOPMENT_CN.md)。

推荐直接安装完整 FPK。拆分版需要把对应架构的 Python 3.11 运行时数据包上传到“应用文件”中的 `moviepilot/runtime` 目录后再启动。

## 构建

上游更新由 GitHub Actions 每 6 小时检测，兼容版本自动生成 x86/ARM 的 FPK Release 草稿，再由用户手动升级。完整流程和当前兼容范围见 [UPDATES_CN.md](UPDATES_CN.md)。

准备 MoviePilot 的 `app.tgz`、对应架构的 `sites` 官方资源、Node 二进制和 Python 3.11 运行时后执行：

```powershell
python build-fpk.py --version 2.15.6-41 --platform x86
python build-fpk.py --version 2.15.6-41 --platform arm
```

ARM Python 运行时可由已经验证的 x86 运行时和同版本 ARM64 wheels 生成：

```powershell
python scripts/build-arm-runtime.py
```

脚本会拒绝缺失的 ARM wheel，并检查最终运行时中的所有 ELF 都是 AArch64。
