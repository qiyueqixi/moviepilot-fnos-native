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

- 后端就绪前显示从本次启动日志提取的初始化进度；检测到异常或后台进程退出时显示脱敏、截断后的错误摘要。
- 为统一网关路径注入正确的 `<base>`。
- 代理 `/api` 和 `/cookiecloud` 到 Python 后端。
- 在 fnOS iframe 中使用紧凑 UI。
- 从配置目录读取自定义启动背景。

## 4. fnOS 生命周期

fnOS 调用 `fnos/cmd/*_init` 和 `*_callback`，这些入口统一加载 `installer`、`common` 和 `service-setup`。

| 阶段 | 主要行为 |
| --- | --- |
| 安装前 | 校验环境，初始化应用变量 |
| 安装后 | 保存应用代理，迁移并清理旧进程代理，解压内置运行时，修正目录所有者 |
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

应用私有运行数据位于 `${TRIM_PKGVAR}`，常见路径为 `/vol1/@appdata/moviepilot`。其中包括虚拟环境、PID 和授权路径快照。MoviePilot 应用代理写入共享配置目录的 `app.env`。

安装向导的 `wizard_proxy` 只更新 `PROXY_HOST`。MoviePilot 的 GitHub 检查、更新、插件、元数据以及带代理开关的模块会显式读取 `settings.PROXY`；下载器等没有主动使用该配置的模块不会经过代理。

启动脚本不得设置全进程 `HTTP_PROXY`、`HTTPS_PROXY` 或 `ALL_PROXY`，并会在启动前清除从父进程继承的同名变量。发现某个具体模块需要代理时，应让该模块显式使用 `settings.PROXY`，不能用全进程代理扩大作用范围。

升级时如果发现旧版 `.proxy`，安装脚本会在服务启动前把其值迁移到 `PROXY_HOST` 并删除旧文件；历史 `.process-proxy` 也会被清理。

配置向导不能安全回显包含凭据的代理 URL，因此空输入表示保留现有值。`wizard_clear_app_proxy` 提供显式清除操作，不能把空输入直接解释为删除。

媒体库、下载目录等额外目录由用户在 fnOS 应用设置中授权。fnOS 通过 `TRIM_DATA_ACCESSIBLE_PATHS` 注入授权列表；启动脚本将其写入 `.accessible_paths`，`fnos/resources/local.py` 在列目录及复制、移动、删除、链接等每个操作前再次检查路径是否位于授权根目录内。

新增文件操作时必须调用同一套允许路径检查，不能只在列表页面隐藏未授权目录。

## 6. 免登录实现

免登录不是删除旧数据库中的账户或密码，而是由环境变量 `MOVIEPILOT_NO_AUTH=1` 启用适配逻辑：

- `scripts/apps/moviepilot/patch-native.py` 修改后端令牌解析、当前用户和登录接口。
- 资源 Cookie 鉴权在免登录模式下返回内置管理员身份，供实时日志 SSE、图片缓存和下载等浏览器资源请求使用。
- `fnos/resources/no-auth.js` 在前端模块启动前调用免登录接口，写入内置管理员状态和后端返回的真实认证等级。
- 后端返回 ID 为 `0` 的 `admin` 管理员，但令牌等级读取 `SitesHelper().auth_level`，不会伪造站点认证结果。

`no-auth.js` 不能把等级固定为 `0` 或 `99`。固定为 `0` 会在每次重新打开页面时覆盖浏览器状态，使已完成认证的机器再次显示“用户认证”；固定为 `99` 则会隐藏未认证机器的认证入口。站点认证参数保存在当前机器的 `user.db`，前端只同步后端计算出的等级。

登录接口返回的普通访问令牌默认只有 8 天有效期，免登录前端不能直接持久保存该令牌，否则长期打开后仍会被前端判定为过期。`no-auth.js` 应使用后端返回的真实等级生成长期本地令牌；后端请求瞬时失败时沿用已有等级，只有后端成功返回新等级时才覆盖。后端在 `MOVIEPILOT_NO_AUTH=1` 下仍按当前 `SitesHelper().auth_level` 执行权限判断，前端令牌等级只用于界面状态。

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
python build-fpk.py --version 2.14.6-37 --platform x86
python build-fpk.py --version 2.14.6-37 --platform arm
```

拆分安装包：

```powershell
python build-fpk.py --version 2.14.6-37 --platform x86 --without-runtime --output-name moviepilot_2.14.6-37_x86_installer.fpk
python build-fpk.py --version 2.14.6-37 --platform arm --without-runtime --output-name moviepilot_2.14.6-37_arm_installer.fpk
```

同一批源码生成的完整包和拆分安装包必须使用相同版本号；是否内置运行时只通过 `_installer` 文件名和包内容区分，不能为拆分包单独递增版本。产物写入 `dist/`。`build-fpk.py` 会：

`manifest` 中的 `maintainer` 表示 MoviePilot 上游维护者，`distributor` 表示 fnOS FPK 发布者。自建发布包应保留 `maintainer=jxxghp`，并把 `distributor` 与 `distributor_url` 设置为实际发布者及其仓库，不能沿用模板项目的发布者信息。

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
tar -tzf dist/moviepilot_2.14.6-37_x86.fpk
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

应用文件中的 `moviepilot.log` 是 stdout/stderr 汇总日志。`cmd/main` 必须同时设置 `MOVIEPILOT_STDIO_LOG_MAX_BYTES=5242880` 和 `MOVIEPILOT_STDIO_LOG_BACKUP_COUNT=7`，使上游 `configure_rotating_stdio` 按每个 5 MB 滚动并保留 7 个备份，总占用约 40 MB。只设置 `MOVIEPILOT_STDIO_LOG_FILE` 时，上游默认备份数为 0，Python 的 `RotatingFileHandler` 不会真正轮转，文件会持续增长。升级旧版时，`trim_legacy_log` 会在服务进程打开日志前检查旧单文件；超过 40 MB 时只保留末尾约 5 MB，避免超大旧文件进入备份链。

MoviePilot 网页实时日志读取 `config/logs` 下的业务日志，使用上游默认的 5 MB、10 个备份策略；不要把应用文件日志的轮转改成定期删除整个日志目录。

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
- 局域网下载器连接超时：检查服务进程是否意外继承了宿主环境的 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`。FPK 自身只写入 `PROXY_HOST`，不会设置这些变量。

## 14. 自定义启动背景

在配置目录放入以下任一文件并重启应用：

```text
loading-background.webp
loading-background.jpg
loading-background.jpeg
loading-background.png
```

安装包内置 `public/loading-background.jpg` 作为默认背景。Node 网关先按以上顺序选择配置目录中的第一个文件，均不存在时才使用包内图片。该资源统一通过 `/fnos-loading-background` 返回。

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

## 17. 已验证的坑点

以下问题均在实际 fnOS 测试机或发布流程中出现过。升级上游、调整代理或重新打包时应优先检查这些位置。

### 17.1 应用代理不是全进程代理

`PROXY_HOST` 会生成 MoviePilot 的 `settings.PROXY`，但只有显式传入该配置的请求才会走代理。不要为了解决 GitHub 或元数据访问而给整个 Python 进程设置 `HTTP_PROXY`、`HTTPS_PROXY` 或 `ALL_PROXY`，否则局域网下载器、媒体服务器和其他应直连的模块也会被送进代理。

另一个容易忽略的问题是请求对象的代理快照。Bangumi 模块曾在初始化时创建并长期保存 `RequestUtils` 和 `AsyncRequestUtils`；安装后再写入代理时，同步模块测试可以成功，但详情页使用的旧异步对象仍会直连并在约 20 秒后超时。本项目在每次 Bangumi 请求前按当前 `settings.PROXY` 重建请求器。适配其他模块时也要检查请求对象是在模块启动时创建，还是在实际请求时读取配置。

不能只用模块测试判断代理正常，还应覆盖真实接口：

```bash
curl -o /dev/null -w '%{http_code} %{time_total}\n' http://127.0.0.1:3001/api/v1/bangumi/326
curl -o /dev/null -w '%{http_code} %{time_total}\n' 'http://127.0.0.1:3001/api/v1/bangumi/credits/326?page=1&count=20'
curl -o /dev/null -w '%{http_code} %{time_total}\n' 'http://127.0.0.1:3001/api/v1/bangumi/recommend/326?page=1&count=20'
```

### 17.2 首次资源更新可能让后端主动退出

MoviePilot 检测到 `sites` 或 `user.sites.v2.bin` 更新后，会下载资源并主动结束当前服务以请求重启。原生 FPK 的 `cmd/main` 是启动器，不是持续监督 Python 子进程的进程管理器，因此不能把“进程曾经启动”当成“更新后已经重新监听”。

首次安装、升级资源或替换 `sites` 后，应等待资源更新结束，再同时检查进程和端口：

```bash
ps -ef | grep MoviePilot | grep -v grep
curl --max-time 5 http://127.0.0.1:3001/api/v1/system/global?token=moviepilot
tail -n 100 /vol1/@appshare/moviepilot/logs/moviepilot.log
```

首次启动遇到资源包更新时，`public/backend-supervisor.sh` 会在检测到当前启动周期的“资源包更新完成”标记后自动拉起一次，不依赖进程退出码。更新正在加载的 `sites` 原生扩展可能使 Python 以 `SIGSEGV/139` 退出，这属于该更新流程的一部分，不应由等待页显示为启动失败。监督脚本只处理当前启动周期内的第一次资源更新退出；没有更新标记的普通异常仍会停止并由等待页显示。测试流程应覆盖自动重启后 `/fnos-ready` 恢复就绪。

等待页只在 `MOVIEPILOT_PID_FILE` 对应的后台监督进程已经退出时提取错误日志。后台仍存活时，TMDB、插件仓库等模块输出的 `ERROR` 属于可恢复的运行状态，只作为日志保留，不显示红色启动失败提示。

### 17.3 系统日志文件会被 fnOS 重新创建

应用日志需要同时出现在“应用文件”和 `/var/log/apps/moviepilot.log`。后者可能被 fnOS 重新创建为 `root:root 0644`，此时以 package 用户运行的 `tail -F` 镜像进程无法追加内容，而且通常不会留下明显错误。

安装和升级回调必须调用 `prepare_system_log` 修正所有者和模式；启动后还要确认日志镜像进程实际存在：

```bash
stat -c '%U:%G %a %n' /var/log/apps/moviepilot.log
ps -ef | grep 'tail -n 0 -F' | grep moviepilot | grep -v grep
```

不要尝试在应用用户执行的 `main start` 中 `chown` 系统日志，该用户没有足够权限。

### 17.4 启动页只能显示本次启动的安全摘要

应用日志是追加写入的。如果启动页直接读取文件尾部，旧 Traceback 会被误认为当前启动失败。`cmd/main` 每次启动前写入 `[fnOS] MoviePilot service starting`，Node 网关只分析最后一个标记之后的内容。

返回浏览器前必须去除 ANSI 控制符，截断行数和总长度，并遮蔽 `token`、`apikey`、`password`、`secret` 等值。完整日志只保存在应用日志目录。后端健康检查成功时应以“启动完成”为准，避免把插件安装等非致命错误继续显示成启动失败。

### 17.5 图片代理还会经过地址安全检查

页面没图不一定是代理不可用。MoviePilot 会解析图片域名并拦截被判定为内网、保留地址或特殊 IPv6 范围的结果。Bangumi 的 `lain.bgm.tv` 曾解析到 `2001::/32`，HTTP 代理本身返回正常，但图片安全检查仍会拒绝 URL。

应先记录域名的实际 DNS 结果，再按最小范围配置 `IMAGE_PROXY_ALLOWED_PRIVATE_RANGES`。不要为了省事放开全部私网或关闭检查，否则免登录网关会扩大服务端请求伪造风险。

### 17.6 FPK 是两层压缩包

只检查外层 FPK 文件名和大小不足以证明补丁进入产物。外层包含 `manifest`、生命周期脚本和内层 `app.tgz`；Bangumi、免登录、Node 网关和运行时都位于内层。

每次构建至少验证：

- 外层 `manifest` 的版本和平台正确。
- `cmd/main` 包含当前启动、日志和代理逻辑。
- 内层 Bangumi 文件包含动态代理补丁。
- 内层 `public/service.js` 包含当前启动页实现。
- 完整包包含 `runtime/venv.tgz`，拆分包不包含。
- x86 与 ARM 的 `sites`、Node 和运行时 ELF 架构匹配。

运行时解压后出现 `Permission denied: pyvenv.cfg`，通常不是 Python 版本问题，而是从数据包恢复的目录所有者不属于 package 用户。解压和升级回调必须再次修正虚拟环境所有者与读取权限。

### 17.7 GitHub Release 大文件上传

四个 FPK 加两个运行时接近 1 GB。通过局域网 HTTP 代理一次性执行 `gh release create ... <全部附件>` 时，代理可能在大文件上传中强制断开连接；`gh` 创建的临时 Release 会被删除，或留下状态为 `starter` 的不完整附件。重复上传同名文件会返回 `already_exists`。

更稳定的流程是：

1. 先创建不带附件的正式 Release，并使用 UTF-8 `--notes-file` 写中文说明，避免 PowerShell 参数编码导致乱码。
2. 逐个上传附件，小包先上传，大包单独重试。
3. 失败后通过 Release assets API 检查 `state`；删除 `starter` 附件后再传，不能只看网页中是否显示。
4. 如果 Windows 到 HTTP 代理的大请求持续被重置，可从存有产物的 NAS 直连 `uploads.github.com` 上传。
5. 使用 `curl` 直传时采用纯 ASCII 临时路径并显式发送 `Content-Length`，中文路径在多层 Shell 编码中可能被误读为 0 字节。
6. 最后核对 GitHub 返回的附件大小和 `digest`，并与本地 `SHA256SUMS.txt` 对比。

GitHub 插件安装出现 `403 - 超出速率限制` 与网络不通不是同一问题。代理只能解决连接，API 限额需要配置有效的 GitHub Token 或等待限额恢复。
