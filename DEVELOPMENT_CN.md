# MoviePilot fnOS 原生 FPK 开发文档

本文面向维护和二次开发人员，说明本项目的运行架构、fnOS 打包规则、构建流程、权限边界、调试方法和发布检查。普通用户安装应用请阅读 `OFFLINE_INSTALL_CN.md` 或 `OFFLINE_INSTALL_ARM_CN.md`。

## 1. 项目目标

本项目把 MoviePilot 改造成 fnOS 原生 FPK，不使用 Docker。当前支持：

- x86_64 和 ARM64。
- fnOS 统一网关 `/app/moviepilot/`，不开放独立网页端口。
- fnOS 桌面 iframe 内嵌打开。
- 应用内免登录。
- 完整离线包，以及安装包与 Python 运行时分离的拆分包。
- fnOS“应用文件”和用户授权目录。
- 安装、升级、配置、启停和卸载生命周期。

免登录会让能够访问该 fnOS 应用网关的用户取得 MoviePilot 管理员权限。不要把网关直接暴露到不可信网络。

## 2. 目录结构

```text
moviepilot/
|-- build-fpk.py                    # 组装最终 FPK
|-- app.tgz                         # 上游源码、前端和 Node 依赖的中间包，不入库
|-- fnos/
|   |-- manifest                    # FPK 元数据
|   |-- config/
|   |   |-- privilege              # package 用户运行声明
|   |   `-- resource               # 应用文件目录声明
|   |-- cmd/                        # fnOS 生命周期和服务脚本
|   |-- wizard/                     # 安装、配置和卸载向导
|   |-- ui/                         # fnOS 桌面入口
|   |-- resources/                  # 适配代码和架构相关资源
|   `-- runtime/                    # Python 3.11 运行时数据包，不入库
|-- scripts/
|   |-- apps/moviepilot/            # 下载并修改上游 MoviePilot
|   `-- build-arm-runtime.py        # 从 x86 运行时生成 ARM64 运行时
`-- dist/                           # 构建产物，不入库
```

以下大文件由 `.gitignore` 排除，需要在构建机单独准备：

- `app.tgz`
- `fnos/runtime/venv-runtime.tgz`
- `fnos/runtime/venv-runtime-arm.tgz`
- `fnos/resources/sites.cpython-311-*.so`
- `fnos/resources/node-linux-arm64`

## 3. 运行架构

应用启动后有两个进程：

```text
fnOS 浏览器
    -> /app/moviepilot/
    -> fnOS 统一网关
    -> moviepilot.sock
    -> Node/Express 前端网关
       |-> 静态前端、启动检查页
       `-> 127.0.0.1:3001
           -> MoviePilot Python 后端
```

`fnos/cmd/main` 负责启动和停止两个进程：

- Python：`${TRIM_PKGVAR}/venv/bin/python -u -m app.main`
- Node：`${TRIM_APPDEST}/public/node/bin/node public/service.js`

Python 后端只监听 `127.0.0.1:3001`。Node 网关监听 `${TRIM_APPDEST}/moviepilot.sock`，由 fnOS 统一网关转发，因此 `manifest` 使用 `checkport = false`，不需要声明外部端口。

`fnos/ui/config` 中的关键设置为：

```json
{
  "type": "iframe",
  "gatewayPrefix": "/app/moviepilot",
  "gatewaySocket": "moviepilot.sock",
  "url": "/app/moviepilot/?fnos=1"
}
```

Node 网关还负责：

- 后端就绪前显示启动检查页。
- 为统一网关路径注入正确的 `<base>`。
- 代理 `/api` 和 `/cookiecloud` 到 Python 后端。
- 在 fnOS iframe 中使用紧凑 UI。
- 从配置目录读取自定义启动背景。

## 4. fnOS 生命周期

fnOS 调用 `fnos/cmd/*_init` 和 `*_callback`，这些入口统一加载 `installer`、`common` 和 `service-setup`。

| 阶段 | 主要行为 |
| --- | --- |
| 安装前 | 校验环境，初始化应用变量 |
| 安装后 | 分别保存应用代理和进程代理，迁移旧代理，解压内置运行时，修正目录所有者 |
| 启动 | 解析应用文件目录，安装拆分运行时，启动 Python 和 Node |
| 停止 | 先正常终止进程，超时后强制终止，删除 PID 和 Socket |
| 配置后 | 更新代理设置 |
| 升级前 | 停止服务并保留数据 |
| 升级后 | 修正所有权，恢复运行时并重新初始化 |
| 卸载后 | 根据向导选择保留数据或删除所有应用数据 |

删除数据使用路径白名单，只允许清理 MoviePilot 自己的 `@appdata`、`@apphome`、`@appconf`、`@appmeta`、`@apptemp`、`@appshare` 和已声明的应用文件子目录。不要删除这些路径校验。

## 5. 数据和权限模型

`fnos/config/privilege` 声明应用以独立的 `moviepilot:moviepilot` package 用户运行，不应使用 root 运行服务。

`fnos/config/resource` 声明四个“应用文件”目录：

```text
moviepilot/config
moviepilot/logs
moviepilot/exports
moviepilot/runtime
```

实际路径由 fnOS 注入的 `TRIM_DATA_SHARE_PATHS` 决定，不能在代码中固定写成 `/vol1/@appshare`。常见安装中对应：

```text
/vol1/@appshare/moviepilot/config
/vol1/@appshare/moviepilot/logs
/vol1/@appshare/moviepilot/exports
/vol1/@appshare/moviepilot/runtime
```

应用私有运行数据位于 `${TRIM_PKGVAR}`，常见路径为 `/vol1/@appdata/moviepilot`。其中包括虚拟环境、PID、进程代理配置和授权路径快照。MoviePilot 应用代理写入共享配置目录的 `app.env`，进程代理单独保存在私有目录的 `.process-proxy`。

两个代理的职责不同：

- `wizard_proxy` 更新 `PROXY_HOST`，只影响 MoviePilot 主动使用 `settings.PROXY` 的模块。
- `wizard_process_proxy` 设置整个服务进程的 `HTTP_PROXY`、`HTTPS_PROXY` 和 `ALL_PROXY`。

升级时如果发现旧版 `.proxy`，安装脚本会把其值迁移到 `PROXY_HOST` 并删除旧文件。除非用户重新填写高级选项，否则升级后不再启用全进程代理。

配置向导不能安全回显包含凭据的代理 URL，因此空输入表示保留现有值。`wizard_clear_app_proxy` 和 `wizard_clear_process_proxy` 提供显式清除操作，不能把空输入直接解释为删除。

媒体库、下载目录等额外目录由用户在 fnOS 应用设置中授权。fnOS 通过 `TRIM_DATA_ACCESSIBLE_PATHS` 注入授权列表；启动脚本将其写入 `.accessible_paths`，`fnos/resources/local.py` 在列目录及复制、移动、删除、链接等每个操作前再次检查路径是否位于授权根目录内。

新增文件操作时必须调用同一套允许路径检查，不能只在列表页面隐藏未授权目录。

## 6. 免登录实现

免登录不是删除旧数据库中的账户或密码，而是由环境变量 `MOVIEPILOT_NO_AUTH=1` 启用适配逻辑：

- `scripts/apps/moviepilot/patch-native.py` 修改后端令牌解析、当前用户和登录接口。
- `fnos/resources/no-auth.js` 向前端写入内置管理员状态。
- 后端返回 ID 为 `0`、等级为 `99` 的 `admin` 管理员。

因此从 Docker 迁移旧配置后，不需要修改数据库中的管理员密码。只要使用本 FPK 的启动脚本，旧账户验证不会阻止访问。

升级上游 MoviePilot 时，必须检查 `patch-native.py` 中的替换目标是否仍存在。当前脚本基于文本替换，上游文件结构变化可能导致补丁没有完整应用。

## 7. 构建环境

生成 `app.tgz` 推荐使用 Linux 或 WSL2，所需工具：

- Bash、curl、tar、xz
- Python 3
- Node.js 和 npm
- jq

最终 FPK 的组装脚本是纯 Python，可在 Windows、Linux 或 WSL2 运行。Python 建议使用 3.11 或更高版本。

所有 Python 原生扩展必须匹配：

- Python ABI：CPython 3.11
- x86：`x86_64-linux-gnu`
- ARM：`aarch64-linux-gnu`

不能把 x86 wheel 或 `.so` 放入 ARM 包，也不能混用 CPython 3.12 扩展。

## 8. 获取并适配上游源码

在 Linux 或 WSL2 中执行：

```bash
VERSION=2.14.6 bash scripts/apps/moviepilot/build.sh
```

不设置 `VERSION` 时，脚本通过 `get-latest-version.sh` 获取最新版本。该流程会：

1. 下载对应标签的 MoviePilot 后端源码。
2. 执行 `patch-native.py` 加入免登录逻辑。
3. 下载同版本 MoviePilot-Frontend 的 `dist.zip`。
4. 注入 `no-auth.js`。
5. 安装 Node 网关依赖和 x86 Node.js。
6. 生成仓库根目录下的 `app.tgz`。

此步骤需要访问 GitHub、npm 和 nodejs.org。使用代理时先设置：

```bash
export HTTP_PROXY=http://代理地址:端口
export HTTPS_PROXY="$HTTP_PROXY"
```

## 9. 准备架构资源

x86 构建至少需要：

```text
fnos/resources/sites.cpython-311-x86_64-linux-gnu.so
fnos/resources/user.sites.v2.bin
fnos/runtime/venv-runtime.tgz
```

ARM64 构建还需要：

```text
fnos/resources/sites.cpython-311-aarch64-linux-gnu.so
fnos/resources/node-linux-arm64
fnos/runtime/venv-runtime-arm.tgz
```

ARM 运行时可从已验证的 x86 Python 3.11 运行时和 ARM64 wheels 生成：

```powershell
python scripts/build-arm-runtime.py `
  --source fnos/runtime/venv-runtime.tgz `
  --wheels wheels-arm64 `
  --output fnos/runtime/venv-runtime-arm.tgz
```

脚本会拒绝缺失的 ARM wheel，并检查最终运行时中的 ELF 是否全部为 AArch64。

`sites` 是 MoviePilot 官方闭源资源，版本、Python ABI 和 CPU 架构必须与目标包一致，否则启动时会出现 `ModuleNotFoundError` 或 ELF 架构错误。

## 10. 构建 FPK

完整离线包：

```powershell
python build-fpk.py --version 2.14.6-19 --platform x86
python build-fpk.py --version 2.14.6-19 --platform arm
```

拆分安装包：

```powershell
python build-fpk.py --version 2.14.6-20 --platform x86 --without-runtime --output-name moviepilot_2.14.6-20_x86_installer.fpk
python build-fpk.py --version 2.14.6-20 --platform arm --without-runtime --output-name moviepilot_2.14.6-20_arm_installer.fpk
```

产物写入 `dist/`。`build-fpk.py` 会：

- 读取 `app.tgz`。
- 替换对应架构的 `sites`、文件权限适配、免登录和 Node 网关文件。
- 加入 fnOS UI。
- 按需加入运行时。
- 规范 tar 成员的用户、组和执行权限。
- 更新 `manifest` 中的版本、平台和 `app.tgz` MD5。

版本号必须高于已安装版本，否则 fnOS 可能拒绝升级。建议上游版本保持不变时只递增最后的 fnOS 修订号。

## 11. 构建检查

提交前至少执行：

```powershell
python -m py_compile build-fpk.py scripts/build-arm-runtime.py scripts/apps/moviepilot/patch-native.py
python -m json.tool fnos/config/privilege > $null
python -m json.tool fnos/config/resource > $null
python -m json.tool fnos/ui/config > $null
python build-fpk.py --help
python scripts/build-arm-runtime.py --help
```

检查 FPK 内容：

```powershell
tar -tzf dist/moviepilot_2.14.6-19_x86.fpk
```

至少应包含 `manifest`、`app.tgz`、`cmd/`、`config/`、`wizard/`、`ui/`、图标和许可文件。完整包的内层 `app.tgz` 还应包含 `runtime/venv.tgz`。

ARM 包建议在 Linux 中进一步检查：

```bash
file fnos/resources/sites.cpython-311-aarch64-linux-gnu.so
file fnos/resources/node-linux-arm64
```

最终仍需在对应架构的 fnOS 测试机进行安装、升级、卸载和重装测试。只检查压缩包不能覆盖 fnOS 生命周期变量和目录权限。

## 12. 测试清单

每个架构至少验证：

- 新安装可以启动，桌面入口以内嵌页面打开。
- `/app/moviepilot/` 可访问，没有额外局域网监听端口。
- 启动较慢时显示检查页，后端就绪后自动进入应用。
- 无需输入 MoviePilot 账户密码即可进入。
- 配置、日志、导出和运行时目录出现在“应用文件”。
- 未授权系统目录不会出现在 MoviePilot 文件管理器，也不能通过手工路径访问。
- fnOS 新增授权目录后，重启应用即可访问。
- 代理安装和配置修改生效。
- 保留数据升级后配置仍在。
- 卸载选择“保留数据”后可恢复。
- 卸载选择“删除全部应用数据”后不残留 MoviePilot 应用目录。
- 从 Docker 数据迁移后仍为免登录。

## 13. 日志和调试

安装器及生命周期日志：

```bash
cat /var/log/apps/moviepilot.log
```

应用运行日志通常位于：

```bash
tail -f /vol1/@appshare/moviepilot/logs/moviepilot.log
```

实际数据卷不一定是 `/vol1`，应以 fnOS“应用文件”显示的路径或 `TRIM_DATA_SHARE_PATHS` 为准。

常用只读检查：

```bash
ps -ef | grep -E 'app.main|public/service.js' | grep -v grep
ls -l /vol1/@appcenter/moviepilot/moviepilot.sock
ss -lntp | grep 3001
curl -I http://127.0.0.1:3001/api/v1/system/global?token=moviepilot
```

常见问题：

- `No module named app.helper.sites`：缺少匹配 Python 3.11 和 CPU 架构的 `sites` 文件。
- `Permission denied: pyvenv.cfg`：运行时目录所有权或读取权限错误，检查是否由 package 用户拥有。
- 启动页一直等待：先看应用日志，再检查 Python 是否监听 `127.0.0.1:3001`。
- 页面资源 404：检查统一网关前缀、`<base>` 注入和 `/fnos-assets` 路径转换。
- 应用文件为空：检查 `fnos/config/resource` 是否打入 FPK，以及 fnOS 是否注入 `TRIM_DATA_SHARE_PATHS`。
- 能看到未授权目录：检查 `.accessible_paths` 和 `local.py` 是否被正确打入 `app.tgz`。
- 局域网下载器连接超时：检查是否误用了进程网络代理；优先改用 MoviePilot 应用代理。确需进程代理时，确认服务同时继承 `NO_PROXY/no_proxy`。

## 14. 自定义启动背景

在配置目录放入以下任一文件并重启应用：

```text
loading-background.webp
loading-background.jpg
loading-background.jpeg
loading-background.png
```

Node 网关按以上顺序选择第一个存在的文件。该资源通过 `/fnos-loading-background` 返回，不需要改包。

## 15. 升级上游 MoviePilot

建议按以下顺序：

1. 更新目标 MoviePilot 版本并重新生成 `app.tgz`。
2. 检查 `patch-native.py` 的三个后端补丁是否实际生效。
3. 确认前后端版本一致。
4. 确认新版本依赖已进入 x86 和 ARM 运行时。
5. 获取同版本、同 ABI、同架构的官方 `sites`。
6. 分别构建完整包和拆分包。
7. 先在 fnOS 虚拟机执行保留数据升级。
8. 再测试全新安装、Docker 数据迁移和完整卸载。
9. 更新 README、安装文档和 `CHANGELOG.md`。
10. 计算产物校验值并上传私有 GitHub Release。

不要直接修改 `app.tgz` 中的上游文件后长期保存。可重复的修改应进入 `patch-native.py`、`fnos/resources/` 或构建脚本。

## 16. 发布建议

发布前记录 SHA-256：

```powershell
Get-FileHash dist\*.fpk -Algorithm SHA256
Get-FileHash fnos\runtime\*.tgz -Algorithm SHA256
```

Release 至少应包含：

- x86 完整 FPK。
- x86 拆分安装 FPK 和运行时数据包。
- ARM64 完整 FPK。
- ARM64 拆分安装 FPK 和运行时数据包。
- 对应版本的更新说明和校验值。

仓库当前用于私有分发。上传前应再次确认仓库可见性为 Private，避免把第三方闭源资源或完整运行时公开发布。
