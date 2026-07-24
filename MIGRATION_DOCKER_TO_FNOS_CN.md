# MoviePilot Docker 数据手动迁移到 fnOS 原生 FPK

本文适用于从 MoviePilot v2 Docker 版迁移到本仓库提供的 fnOS 原生 FPK。迁移后保留原有站点、订阅、下载器、插件配置和用户数据，但打开原生应用时不再要求输入 MoviePilot 账户密码。

## 迁移前说明

- 源端和目标端应使用相同或兼容的 MoviePilot v2 数据库版本。
- 必须先停止 Docker 容器和原生 FPK，避免复制正在写入的 SQLite 数据库。
- 下文以应用安装在 `/vol1` 为例。应用安装在其他存储空间时，需要替换路径中的卷号。
- 本仓库的 FPK 只监听 `127.0.0.1:3001`，并通过 fnOS 统一网关 `/app/moviepilot/` 访问。

示例 Docker 配置目录：

```text
/vol1/1000/docker/moviepilot-v2/moviepilot-v2/config
```

原生 FPK 配置目录：

```text
/vol1/@appshare/moviepilot/config
```

可以用以下命令查找实际目标目录：

```bash
sudo find /vol* -path '*/@appshare/moviepilot/config' -type d 2>/dev/null
```

## 账户验证如何变为免验证

Docker 数据库的 `user` 表中通常保留管理员账户、密码哈希和双重验证配置。迁移时不要删除用户表，也不要把 `hashed_password` 手动改为空，否则可能破坏数据库约束或影响以后恢复 Docker 版。

本仓库的原生 FPK 在启动时强制设置：

```text
MOVIEPILOT_NO_AUTH=1
SUPERUSER=admin
SUPERUSER_PASSWORD=
```

后端收到请求后会构造一个 ID 为 `0`、等级为 `99` 的内置管理员身份；前端也会自动写入对应的登录状态。因此旧数据库中的真实账户仍然保留，但不会触发 MoviePilot 登录页面，也不需要知道旧密码。

复制旧 `app.env` 后，建议删除其中的账户控制项，让 FPK 启动脚本成为唯一来源：

```bash
sudo sed -i -E '/^(SUPERUSER|SUPERUSER_PASSWORD|MOVIEPILOT_NO_AUTH)=/d' \
  /vol1/@appshare/moviepilot/config/app.env
```

如果 `app.env` 中本来没有这些项目，命令不会改变其他配置。日志里出现“`SUPERUSER_PASSWORD` 的空值已替换为 `None`”属于 MoviePilot 的配置规范化提示，不代表免登录失效。

## 手动迁移步骤

先根据自己的环境修改 `SRC` 和 `DST`：

```bash
SRC=/vol1/1000/docker/moviepilot-v2/moviepilot-v2/config
DST=/vol1/@appshare/moviepilot/config
BACKUP=/vol1/1000/分享
```

1. 停止旧 Docker 容器。使用 Compose 部署时，在 Compose 文件所在目录执行：

```bash
sudo docker compose stop
```

也可以只停止 MoviePilot 容器：

```bash
sudo docker stop <MoviePilot容器名称>
```

2. 停止原生 FPK：

```bash
sudo appcenter-cli stop moviepilot
```

3. 备份原生 FPK 的当前配置：

```bash
STAMP=$(date +%Y%m%d-%H%M%S)
sudo tar -czf "$BACKUP/moviepilot-native-config-before-migration-$STAMP.tgz" \
  -C "$DST" .
```

4. 合并 Docker 配置到原生配置目录：

```bash
sudo cp -a "$SRC"/. "$DST"/
```

这里使用合并复制，不会删除目标目录中仅由 fnOS 创建的文件。源 Docker 配置也不会被修改。

5. 删除 SQLite 运行期临时文件：

```bash
sudo rm -f "$DST/user.db-wal" "$DST/user.db-shm"
```

`user.db` 是正式数据库，不能删除。只有在两个服务均已停止后才能清理 `-wal` 和 `-shm` 文件。

6. 清除旧账户环境变量并修复权限：

```bash
if [ -f "$DST/app.env" ]; then
  sudo sed -i -E '/^(SUPERUSER|SUPERUSER_PASSWORD|MOVIEPILOT_NO_AUTH)=/d' "$DST/app.env"
fi

sudo chown -R moviepilot:moviepilot "$DST"
sudo chmod -R u+rwX,go-rwx "$DST"
```

7. 启动原生 FPK：

```bash
sudo appcenter-cli start moviepilot
sudo appcenter-cli status moviepilot
```

状态应显示：

```text
running
```

## 验证免登录

从 fnOS 桌面重新打开 MoviePilot。正常情况下会经过启动检查页并直接进入仪表盘，不出现 MoviePilot 登录页面。

也可以通过应用的 Unix Socket 验证后端免登录桥接。以下请求故意使用无效 Token，仍应返回 HTTP 200 和内置管理员信息：

```bash
sudo curl --unix-socket /vol1/@appcenter/moviepilot/moviepilot.sock \
  -H 'Authorization: Bearer deliberately-invalid' \
  -w '\nHTTP %{http_code}\n' \
  http://localhost/api/v1/user/current
```

预期响应包含：

```json
{"name":"admin","is_active":true,"is_superuser":true,"id":0}
```

如果浏览器仍显示旧登录页，关闭 fnOS 中的 MoviePilot 窗口后重新从桌面打开。必要时清理当前 fnOS 域名下 MoviePilot 的浏览器站点数据，`no-auth.js` 会重新生成免登录状态。

## 日志和恢复

应用日志位于：

```text
/vol1/@appshare/moviepilot/logs/moviepilot.log
/var/log/apps/moviepilot.log
```

启动时第三方插件可能尝试访问 GitHub。出现速率限制或插件下载失败不代表数据库迁移或免登录失败，可以配置 GitHub Token 后再重新安装插件。

需要恢复迁移前状态时，先停止原生 FPK，把迁移后的目录改名保留，再解压第 3 步生成的备份：

```bash
sudo appcenter-cli stop moviepilot
STAMP=$(date +%Y%m%d-%H%M%S)
sudo mv "$DST" "${DST}.after-migration-$STAMP"
sudo mkdir -p "$DST"
sudo tar -xzf "$BACKUP/moviepilot-native-config-before-migration-时间戳.tgz" -C "$DST"
sudo chown -R moviepilot:moviepilot "$DST"
sudo chmod -R u+rwX,go-rwx "$DST"
sudo appcenter-cli start moviepilot
```

## 安全注意事项

免登录表示 MoviePilot 自身不再校验账户密码。只能通过 fnOS 桌面和统一网关使用，不要把 `127.0.0.1:3001`、Unix Socket 或额外反向代理直接暴露到公网。外部访问应先由 fnOS 登录、可信 VPN 或其他独立身份认证保护。
