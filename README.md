# 学院 AI Coding

网站管理账号、手工收款、官方 Key 发放和撤销待办；Windows 可视化安装器安装客户端并配置 **DeepSeek 官方直连**。没有模型代理、New API 网关或自动余额截断。

已实现邀请注册、权限与会话、加密库存、事务分配、人工撤销核验、微信/支付宝收款码、5%服务费、幂等审核、人工消费核对与纠错、公告、审计、一次性安装票据、带窗口的PowerShell安装器、供应商适配层、备份恢复、Docker配置和系统服务部署。

2026-10-07 已通过 Workbench 部署到 ECS：**https://101.37.242.39**。已启用可信公网 IP 证书、HTTP跳转、自动续期、正式Key导入和安装票据领取。服务器管理员账号保存在本机 `.tools/private/部署管理员账号.txt`，与本地开发 `.env` 的账号相互独立。

## 本地运行

需要Python 3.12和Node.js 22以上。在根目录：

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r portal\requirements-dev.txt
.venv\Scripts\python.exe ops\init_env.py
.venv\Scripts\python.exe -m uvicorn portal.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

另开终端：

```powershell
cd frontend
npm ci
npm run dev
```

打开 **http://127.0.0.1:5173**。管理员用户名为 `admin`，随机密码保存在本地 `.env` 的 `ADMIN_PASSWORD` 中；初始化不输出密码，也不覆盖已有文件。

管理员先上传收款码、导入Key，再创建邀请码。注册后自动分配库存；无库存时等待分配。下载安装ZIP后完整解压，双击 `Start.cmd`。

注册和登录支持普通用户名或邮箱。管理员侧栏提供「账户管理」和「官方 Key 号池」：新建/编辑成员、重置密码、暂停领取、批量TXT导入、去重预览、库存启停及指定用户分配。真实Key导入需要可信HTTPS；当前公网IP模式不会通过明文发送密钥。

成员通过「邀请好友」生成自己的单人邀请码，7天有效，最多同时保留5个未使用的有效邀请码；支持复制注册链接、查看使用情况及停用自己的邀请码。管理员可以查看生成者并管理全部邀请码。

安装页面和Windows向导都可勾选Claude Code、DeepSeek Harness，或同时安装两者。未分配Key的正常账户也能下载并安装软件，获得Key后重新下载完成配置。未选择的客户端不安装、不修改；仅选择Harness时不安装CC Switch。Harness使用官方npm包`@deepseek-ai/dsh@0.2.0-rc.2`和独立本机环境，可从窗口或桌面快捷方式打开本机网页界面。其凭据由DPAPI加密保存，仅在启动的Harness进程中解密，不写入启动参数或浏览器页面。

## 行为边界

- 已购额度和已核对余额属于平台账务，不是官方独立资金池，消费数据不实时更新。
- 网站暂停领取不会使已发官方Key失效。截止产生官网撤销待办；管理员删除后核验，仅401确认不可鉴权，其余异常保持待核实。
- Key领取后保存在用户电脑，可以用于其他客户端；本地脚本不实施可靠消费限额。
- 安装包不嵌长期Key。有可领取Key时携带30分钟、单次、绑定用户和Key的票据；无Key时只安装软件。票据过期不阻止软件安装，并明确显示模型配置待完成。配置领取后用Windows DPAPI缓存，便于失败重试；安装完成删除缓存。
- 配置原子备份与合并，保留其他设置。无效JSON不强制覆盖；备份后移除冲突的旧 `ANTHROPIC_API_KEY`，使用当前 `ANTHROPIC_AUTH_TOKEN`。
- 新装CC Switch首次启动导入Claude配置；已有客户端需要一次官方导入确认，不直接修改其数据库。
- 软件从官方源下载；依赖WinGet，缺少时提示安装Microsoft Store的“应用安装程序”。启动入口只对当前进程设置执行策略，不修改永久策略。

## 验证与部署

```powershell
.venv\Scripts\python.exe -m pytest portal\tests -q
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ops\test-installer.ps1
cd frontend
npm run build
```

详见[部署与恢复](docs/deployment.md)、[接口与扩展](docs/api.md)、[验证范围](docs/verification.md)。ECS、可信HTTPS、证书续期、真实Key鉴权和真实Claude Code直连任务已验证；干净Windows安装仍需要试装。

不要提交或公开 `.env`、`data/`、安装票据和备份。
