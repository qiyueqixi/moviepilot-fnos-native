# MoviePilot x86 离线安装说明

本发行版适用于 x86 飞牛 fnOS，使用系统内置 Python 3.11 运行，不使用 Docker。

## 文件说明

- `moviepilot_2.14.6-19_x86.fpk`：完整离线安装包。运行环境已经内置，推荐大多数用户使用。
- `moviepilot_2.14.6-20_x86_installer.fpk`：拆分版安装包，不含 Python 运行环境。
- `moviepilot-runtime-x86-python311.tgz`：拆分版所需的数据包。

## 完整离线包安装

1. 在 fnOS 应用中心选择手动安装，上传 `moviepilot_2.14.6-19_x86.fpk`。
2. 按安装向导完成安装，然后启动 MoviePilot。
3. 从桌面打开 MoviePilot。应用已启用免登录模式，无需设置或输入登录密码。

完整包安装和首次启动均不会下载 Python 依赖；网络代理只供 MoviePilot 后续访问站点或下载资源时使用。

## 拆分包安装

拆分包适合希望减少 FPK 安装包体积的用户。必须先上传运行时数据包，再启动应用。

1. 在 fnOS 应用中心手动安装 `moviepilot_2.14.6-20_x86_installer.fpk`。
2. 安装完成后先不要启动 MoviePilot。
3. 打开 fnOS 的“应用文件”，进入 `moviepilot`，再进入 `runtime` 目录。
4. 将 `moviepilot-runtime-x86-python311.tgz` 上传到这个目录，文件名不要修改。
5. 回到应用中心启动 MoviePilot。首次启动会自动解压运行环境，完成后正常运行。

运行时会解压到应用私有目录，因此上传的数据包会保留在“应用文件”的 `moviepilot/runtime` 中，便于检查和重复使用。

## 应用文件目录

以下目录会显示在 fnOS “应用文件”中：

- `moviepilot/config`：配置、数据库、账号令牌等重要数据。
- `moviepilot/logs`：应用日志，排错时查看 `moviepilot.log`。
- `moviepilot/exports`：应用导出的文件。
- `moviepilot/runtime`：拆分版的运行时数据包。

请定期备份 `moviepilot/config`。卸载应用时选择“保留数据”会保留以上目录；选择“删除全部数据”会同时删除它们。

## 代理

安装向导提供两个相互独立的代理选项：

- `MoviePilot 应用代理`：推荐使用，写入 MoviePilot 的 `PROXY_HOST`，仅供明确支持代理的联网模块使用。
- `进程网络代理`：高级选项，为整个 MoviePilot 进程设置 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`，可能影响下载器等其他连接。

进程网络代理启用后，回环地址及 `10.0.0.0/8`、`172.16.0.0/12`、`192.168.0.0/16` 内网地址仍会自动绕过代理。旧版本保存的全进程代理在升级时会自动迁移为 MoviePilot 应用代理。

在应用配置页中，代理输入框留空表示保持现有配置；需要删除代理时，选择对应的“清除”选项。

## 自定义启动背景

MoviePilot 后台启动期间会显示启动检查页，并在服务就绪后自动进入应用。需要自定义背景时，将以下任意一个文件上传到 fnOS “应用文件”中的 `moviepilot/config` 目录：

- `loading-background.webp`
- `loading-background.jpg`
- `loading-background.jpeg`
- `loading-background.png`

重新打开 MoviePilot 即可生效，无需重新安装。建议使用 1920 x 1080 或更高分辨率的横向图片；启动页会自动增加遮罩，保证浅色和深色模式下文字清晰。

## 访问方式

应用通过 fnOS 统一网关路径 `/app/moviepilot/` 访问，不对局域网开放独立网页端口。飞牛桌面入口会自动使用当前 fnOS 域名，并由系统校验 NAS 登录会话。

MoviePilot 内部 API 仅监听本机回环地址 `127.0.0.1:3001`，不能从其他设备直接访问。
