# ECS部署与恢复

## Workbench

用户提供的原命令已执行：`irm https://workbench-cli.oss-cn-hangzhou.aliyuncs.com/install.ps1 | iex`。官方脚本写入Program Files被系统拒绝；项目已使用同一官方发布包及官方SHA256校验安装到 `.tools/workbench/workbench.exe`。

```powershell
.\.tools\workbench\workbench.exe config
.\.tools\workbench\workbench.exe connect -r cn-hangzhou -i <ECS实例ID>
```

凭据保存在当前用户 `.workbench/config.json`，不要发到聊天。AccessKey必须使用阿里云生成的ID和Secret，RAM登录名和密码不能代替。连接后先核查Ubuntu版本、磁盘、已有服务、80/443和Docker，不覆盖已有业务。

## 当前实际部署：系统服务

2026-10-07 已部署到杭州 ECS `i-bp14orusdl513dxgz04z`，正式公网地址 https://101.37.242.39。为用户指定的RAM用户创建AccessKey并配置到本机Workbench，沿用该用户已有权限。没有使用主账号AccessKey。服务器Docker Hub访问超时，因此使用Ubuntu官方软件源中的Caddy和独立Python虚拟环境；前端在本机构建后通过Workbench上传。

- 当前代码：`/opt/campus-ai/current`，指向保留版本的releases目录。
- 生产环境：`/opt/campus-ai/.env`，root专有权限；由systemd注入应用，不随下载包分发。
- 网页：`/var/www/campus-ai`；应用仅监听`127.0.0.1:8000`，安全组新增TCP80，不开放应用端口。
- 数据：`/var/lib/campus-ai`；备份：`/var/backups/campus-ai`，每日服务器当地时间03:30触发，允许延迟10分钟。
- 服务：`campus-ai.service`、`caddy.service`、`campus-ai-backup.timer`，均启用开机启动。
- 管理员账号：本机`.tools/private/部署管理员账号.txt`，服务器保留root可读副本。不要提交或公开该文件。

原IP验证阶段已升级到正式HTTPS。已导入3个真实DeepSeek Key并通过官方鉴权；库存按正常成员自动分配。收款码尚待管理员上传。HTTP除ACME挑战外统一跳转HTTPS；Key导入和安装器配置领取已开启。

## 公网IP证书与自动续期

Let’s Encrypt可信IP证书使用shortlived类型，证书约6天有效；不能沿用普通90天证书的维护周期。Certbot 5.8.0独立安装在`/opt/campus-ai/certbot-venv`。HTTP挑战目录`/var/lib/campus-ai-acme`由Caddy保持可访问，TCP80/443安全组已放行，应用8000仍只监听回环。

Caddy使用`deploy/Caddyfile.ip-https`，设置default_sni兼容不发送SNI的IP客户端。证书账号及原始私钥保持root专有，deploy_ip_certificate.sh仅复制网站所需证书及私钥到`/etc/caddy/tls`，私钥root:caddy 0640。部署钩子重载Caddy，不要求停止网站。

campus-ai-certificate.timer在服务器当地时间00/06/12/18:15检查续期，允许延迟15分钟，已模拟续期通过。续期配置保存在`/etc/letsencrypt/renewal/campus-ai-ip.conf`。备份和迁移需保留受限的/etc/letsencrypt、证书部署钩子及定时器，禁止公开这些私钥。

```bash
systemctl status campus-ai-certificate.timer
/opt/campus-ai/certbot-venv/bin/certbot renew --dry-run --no-random-sleep-on-renew
```

Workbench离线TXT导入可运行`ops/import_keys.py --env /opt/campus-ai/.env --data /var/lib/campus-ai --file <受限TXT>`，通过进程内鉴权调用相同事务接口，不绕过公共HTTP保护，也不打印Key；完成后删除临时明文文件。网站现可直接使用TXT或粘贴导入。

账户与号池版本已更新至`20261007T035723Z-accounts-pool`。管理员可直接访问`/admin/users`和`/admin/keys`。普通成员不会获得管理入口或管理员权限；管理员密码仍使用本机账号文件。新版本复用原始虚拟环境，清理旧发布目录时必须保留其实际依赖目录。邀请码的已用次数以生产管理列表为准，使用过的单人邀请码不能再次注册。

首次原生部署脚本`ops/deploy-native.sh`要求先准备独立生产.env、版本目录和已构建的frontend/dist，并安装python3-venv与caddy。脚本拒绝覆盖运行中的应用，使用专属低权限用户、单进程服务、固定依赖哈希及每日备份。

```bash
bash /opt/campus-ai/current/ops/deploy-native.sh /opt/campus-ai/current
systemctl status campus-ai caddy campus-ai-backup.timer
/opt/campus-ai/current/.venv/bin/python /opt/campus-ai/current/ops/smoke_deployment.py --env /opt/campus-ai/.env
systemctl start campus-ai-backup.service
```

后续发布先备份、创建新版本目录和虚拟环境，不运行首次部署脚本覆盖活跃服务。保留数据目录和.env；切换current并重启campus-ai，更新静态资源时先复制新assets再原子替换index.html。验收失败切回旧版本；数据库版本不兼容时恢复匹配快照，不删除旧数据。

已有原生部署可使用`bash ops/update-native.sh /opt/campus-ai/发布包.zip`；Workbench远程命令默认使用sh，执行该工具时明确使用bash。脚本保留原虚拟环境、证书和数据库，发布前后备份，失败回退。静态目录必须允许Caddy遍历（目录755、文件644）；验收检查HTML引用的JS/CSS内容与类型，防止文件不可访问时被单页应用回退页面掩盖。

原生恢复先停止campus-ai，保存现有数据目录，再使用ops/restore.py恢复到空目标，并设置campus-ai所有权及快照对应的ENCRYPTION_KEY。恢复目标应与生产DATA_DIR和服务ReadWritePaths一致。确认完整性、管理员登录和账务后再恢复服务。

拥有域名后，解析到服务器并放行TCP443；把生产.env的PUBLIC_ORIGIN改为https地址，同时更新SITE_ADDRESS及`/opt/campus-ai/web.env`中的SITE_ADDRESS。重启campus-ai和caddy，检查可信证书及浏览器连接后才导入真实Key。

## Docker部署备选

将代码或发布包上传到 `/opt/campus-ai`，包括portal、frontend、installer、ops、deploy。不要上传本机.env、数据库、.tools、.venv、node_modules和测试产物。

在服务器生成独立.env，参照根目录.env.example。设置 `PUBLIC_ORIGIN=https://你的域名`、`SITE_ADDRESS=你的域名`、独立随机ADMIN_PASSWORD及Fernet ENCRYPTION_KEY。为.env设置仅所有者可读权限。初次建管理员需要至少12位密码；已有管理员不会因环境变量修改而被覆盖。

```bash
docker compose --env-file .env -f deploy/compose.yaml config --quiet
docker compose --env-file .env -f deploy/compose.yaml up -d --build
docker compose --env-file .env -f deploy/compose.yaml ps
```

域名解析、安全组和防火墙允许80/443；不公开8000。Caddy只反代控制接口，模型路径返回404。运行时仅静态Web和单进程、非root Portal，数据与备份持久化，日志轮转。

IP界面验证可暂设PUBLIC_ORIGIN和SITE_ADDRESS为 `http://公网IP`；此模式禁止官方Key导入与配置领取。真实密钥发放前完成可信HTTPS。本地回环地址可进行开发测试。

首次管理员登录：上传收款码 → 导入Key → 创建邀请码 → 注册测试用户 → 下载安装器 → 完成真实代码任务 → 官网核对用量 → 演练官网删除及网站核验。

## 备份

备份使用SQLite online backup生成一致快照，随后复制不可变收款码、匹配加密密钥并生成校验清单。

```bash
docker compose --env-file .env -f deploy/compose.yaml exec -T portal python ops/backup.py --data /app/data --out /app/backups
```

通过docker cp把指定快照复制出容器，再保存到独立受限位置。备份包含可解密数据库的密钥，应与.env一样保护；同机副本不能抵御整机丢失。

本地备份：`.venv\Scripts\python.exe ops\backup.py --data data --out backups`。

## 恢复与回滚

恢复工具验证路径、SHA256和数据库，只写入空目录，不自动删除或覆盖已有数据。

```powershell
.venv\Scripts\python.exe ops\restore.py backups\<快照名> --target restored-data
```

把DATA_DIR指向恢复目录，使用快照对应的ENCRYPTION_KEY，或清空该变量以读取恢复目录encryption.key。密钥不匹配时程序拒绝启动。

ECS恢复先暂停领取并保留旧卷。用 `PORTAL_DATA_VOLUME=campus-ai_restored_<日期>` 选择新空卷，启动一次性Portal容器运行 `python ops/restore.py /app/backups/<快照名> --target /app/data`。确认数据后，用同一新卷名启动服务，保留原卷以便回退。不要执行 `docker compose down -v`。

发布前备份并记录旧镜像ID，按日期保留旧发布包。上线先检查健康、登录、账务、票据与停用；失败时恢复旧代码/镜像及匹配快照。数据库高于应用支持版本时会拒绝错误降级。

Docker方案目前仅通过Compose和Caddy静态校验。当前ECS使用上文系统服务方案，已通过启动、公网、管理员鉴权和实际备份恢复验证。
