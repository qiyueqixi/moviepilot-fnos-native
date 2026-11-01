# MoviePilot ARM64 离线安装说明

本发行版适用于 ARM64 飞牛 fnOS，使用系统内置 Python 3.11 运行，不使用 Docker。

## 文件说明

- `moviepilot_2.15.6-40_arm.fpk`：完整离线安装包，已经内置运行环境，推荐使用。
- `moviepilot_2.15.6-40_arm_installer.fpk`：拆分版安装包，不含 Python 运行环境。
- `moviepilot-runtime-arm-python311.tgz`：拆分版所需的 ARM64 运行时数据包。

## 完整包安装

1. 在 fnOS 应用中心选择手动安装，上传 `moviepilot_2.15.6-40_arm.fpk`。
2. 按安装向导完成安装，然后启动 MoviePilot。
3. 从飞牛桌面打开 MoviePilot。应用已启用免登录模式，无需输入 MoviePilot 登录密码。

免登录只跳过 MoviePilot 账户密码。未完成站点认证时，从右上角用户菜单进入“站点认证”，选择站点并填写认证参数；参数只保存在当前机器的 `moviepilot/config/user.db`。

完整包安装和首次启动不会下载 Python 依赖。安装向导中的代理只供 MoviePilot 后续联网使用。

## 拆分包安装

1. 在 fnOS 应用中心手动安装 `moviepilot_2.15.6-40_arm_installer.fpk`。
2. 安装完成后先不要启动 MoviePilot。
3. 打开 fnOS 的“应用文件”，进入 `moviepilot/runtime` 目录。
4. 上传 `moviepilot-runtime-arm-python311.tgz`，不要修改文件名。
5. 回到应用中心启动 MoviePilot。首次启动会自动解压运行环境。

升级拆分包时，运行时也必须从同一 Release 下载并重新上传。应用会核对 SHA-256，拒绝不匹配的旧依赖；完整包已经内置匹配的运行时。

## 应用文件

- `moviepilot/config`：配置、数据库和令牌等重要数据。
- `moviepilot/logs`：应用日志，排错时查看 `moviepilot.log`。
- `moviepilot/exports`：应用导出的文件。
- `moviepilot/runtime`：拆分版运行时数据包。

卸载时选择“保留数据”会保留以上目录；选择“删除全部数据”会删除 MoviePilot 对应的全部应用目录。

## 自定义启动背景

后台启动期间会显示当前初始化进度，安装包已内置默认背景，首次打开不会显示纯黑页面；检测到启动错误或后台进程提前退出时，页面会直接显示错误摘要，完整内容保存在 `moviepilot/logs/moviepilot.log`。

将以下任意一个文件上传到 `moviepilot/config`，重新打开应用即可生效：

- `loading-background.webp`
- `loading-background.jpg`
- `loading-background.jpeg`
- `loading-background.png`

建议使用 1920 x 1080 或更高分辨率的横向图片。

## 访问和权限

应用通过 fnOS 统一网关 `/app/moviepilot/` 访问。内部 API 只监听 `127.0.0.1:3001`，不会向局域网开放独立端口。

MoviePilot 文件管理器只显示安装或应用设置中明确授权的目录。未授权时不会显示 NAS 系统目录。

代理由 MoviePilot 自身设置和上级网络规则管理，FPK 不额外设置代理地址，也不改写模块的代理选择逻辑。需要调整时，在 MoviePilot 内修改原生代理设置。

升级会保留已有 MoviePilot 配置。如果以前在 FPK 向导中填过代理，该值已写入 MP 的配置，需要时可在 MP 内自行调整或清除。
