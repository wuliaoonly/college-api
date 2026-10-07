# 验证范围与复现

## 本机验证

- 后端：并发注册、邀请次数、Key唯一分配、用户隔离、CSRF/Origin、票据并发与过期、数据库密钥加密、5%及重复审核、停用核验、截止仅阻止领取、消费防重与纠错、Key不回收、备份恢复。
- Windows PowerShell 5.1：保留权限数组和其他env、移除旧鉴权冲突、备份、重复写入、无效JSON不覆盖及脚本语法。
- WinForms窗口预览：不安装、不领取、不修改客户端配置。
- 独立Chrome浏览器：邀请注册、付款声明、管理员确认、账务、ZIP下载、暂停领取、手机布局、全部管理标签；不使用日常浏览器资料。
- TypeScript/Vite构建、Compose及Caddy配置校验。

浏览器复现：先运行 `.venv\Scripts\python.exe ops\serve_e2e.py`。另开终端进入frontend，设置 `$env:CAMPUS_API_TARGET='http://127.0.0.1:8001'`，运行 `npm run dev -- --port 5174`；最后运行 `node frontend/scripts/e2e.mjs`。测试库与截图在忽略目录artifacts中，不进入正式数据库。

## 真实环境仍需验收

已加密导入用户提供的3个真实DeepSeek Key，官方/models均返回200。已在隔离的Claude Code配置目录中直连DeepSeek，真实生成Python add(a,b)函数。没有修改用户原有Claude配置，没有在平台账务中伪造本次消耗金额；实际费用以官方账单为准。

安装器配置与窗口已验证，但未在干净Windows虚拟机执行四个真实安装程序，仍需验证权限提示、官方源和CC Switch导入。

2026-10-07 已通过 Workbench 成功连接 Ubuntu 24.04 ECS，部署系统服务并验证公网 http://101.37.242.39。Docker Hub 访问超时，生产使用 Caddy + FastAPI 系统服务，没有运行本项目的容器；容器构建仍未验收。

公网首页、登录页、健康接口返回200，模型路径返回404；真实浏览器确认登录页面正常加载。服务器回环地址验证了实际管理员登录、所有管理列表、未登录隔离、CSRF和Origin拒绝、退出，以及非HTTPS禁止导入Key。没有导入占位Key或测试业务数据。修改部署环境加载方式后，18个后端测试再次通过。

账户管理与号池更新：23项后端测试通过，新增邮箱注册与无效输入不消耗邀请码、管理员账户保护、编辑/重置失效会话及票据、未发库存启停、并发指定分配和历史撤销后新库存补配。独立浏览器在隔离数据库中验证邮箱注册、新建/编辑/重置成员、TXT去重预览及导入、库存启停、指定分配和手机布局；正式数据库不写入测试用户或占位Key。

campus-ai、caddy和每日备份定时器均启用开机启动。初次生产快照完成哈希和SQLite完整性验证，并成功恢复到隔离临时目录。现已启用可信HTTPS公网IP证书，正常验证证书链、SAN和主机地址；没有跳过证书检查。Certbot模拟续期成功，6小时检查定时器已启用。

邀请码扩展后26项后端检查通过，浏览器验证成员生成/停用邀请码和分享链接预填；原注册、账务、号池与安装ZIP流程继续通过。Windows PowerShell配置合并与语法检查、WinForms窗口预览通过，新增完成后「打开Claude Code」按钮。干净Windows四个软件的首次安装仍需试装。

正式安装包验证：使用短期验收会话，从可信HTTPS下载已有成员自己的ZIP，逐文件确认没有嵌入任何长期官方Key。Windows PowerShell运行下载包中的实际领取函数，校验证书后单次领取、官方鉴权200、隔离配置写入、DPAPI缓存重试成功；同票据第二次领取返回410。未修改用户现有Claude/CC Switch配置，临时会话与测试凭据已清理。正式浏览器验证成员邀请页面、已分配用户的下载按钮以及手机布局。

官方依据：[DeepSeek接入](https://api-docs.deepseek.com/guides/coding_agents/)、[模型列表](https://api-docs.deepseek.com/api/list-models/)、[错误码](https://api-docs.deepseek.com/quick_start/error_codes/)、[Claude Code安装](https://code.claude.com/docs/en/setup)、[CC Switch](https://github.com/farion1231/cc-switch)、[Workbench](https://help.aliyun.com/zh/ecs/user-guide/connect-to-an-instance-through-workbench-cli/)。

安装选项与下载修复：34项后端检查通过，覆盖无Key管理员/成员下载、三种客户端组合、非法选择不出票及专属票据。隔离浏览器实际下载已分配用户双选ZIP和无Key管理员Harness ZIP，校验selection.json及无Key时不存在ticket.json；空选禁用、暂停账户拒绝、手机页面和原账务/号池流程通过。PowerShell验证三种组合只处理所选客户端，过期票据继续安装软件且不写无效模型配置，DPAPI Harness保存/恢复和配置备份，重试PATH去重。已在本机隔离目录从官方npm安装Harness 0.2.0-rc.2，由实际启动脚本打开认证后的本机网页、识别默认DeepSeek模型；不修改原有Harness/Claude/CC Switch配置。窗口截图已检查。干净Windows首次安装WinGet组件及CC Switch仍需试装。

公网复查：真实HTTPS浏览器管理员登录，无Key情况下分别点击下载Claude Code、Harness、双选ZIP，均成功；逐项验证选项、无票据和PowerShell BOM编码，运行实际下载的双选包窗口预览。页面空选禁用、手机无溢出。真实Harness界面的DeepSeek提供商可用，凭据输入框显示由启动环境提供且只读，不返回原始凭据。修复发布时静态目录权限，JS/CSS正确内容类型与可访问性已加入部署验收，避免只检查HTML和API。
