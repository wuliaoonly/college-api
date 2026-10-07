学院 AI Coding 安装助手

1. 完整解压安装包，请勿在ZIP内直接启动。
2. 双击 Start.cmd，即可看到安装窗口。
3. 勾选Claude Code、DeepSeek Harness，或同时勾选二者，点击“开始安装”。
   Claude Code包含CC Switch；仅选Harness时不会安装或改动Claude Code和CC Switch。
   允许官方软件安装程序需要的权限提示。
4. 完成后点击「打开 Claude Code」，即可进入可使用的编程终端。
   也可重新打开终端，在你的项目目录输入 claude。
   选择Harness时，点击「打开DeepSeek Harness」或桌面的「学院DeepSeek Harness」快捷方式。
   Harness会打开本机网页界面；需要选择一个项目文件夹后开始任务。

没有Key的账户也可下载并安装软件，此时安装包不含配置票据。
软件安装成功与模型配置成功分别显示。管理员分配Key后，重新下载即可补充配置。
票据过期或网络故障不会阻止软件安装，但仍需重新下载完成配置。

配置票据30分钟有效，只能领取一次。不要分享安装包或ticket.json。
助手会用Windows当前用户保护机制缓存已领取配置，便于中途失败后重试。
最终官方Key保存到你选择的本机客户端配置中，模型请求直达供应商。
Harness使用LOCALAPPDATA/CampusAI/Harness独立环境，Key由Windows当前用户DPAPI加密保存。
Harness使用DeepSeek官方@deepseek-ai/dsh 0.2.0-rc.2，不覆盖已有Harness安装。
安装软件从官方来源下载，不经过学院服务器。需要64位Windows 10/11、WinGet及Node.js 22.12或以上。
没有WinGet时，请在Microsoft Store安装“应用安装程序”后重试。

已有Claude Code配置会自动备份到 ~/.claude/ 内；设置了CLAUDE_CONFIG_DIR时使用对应目录。
配置损坏时不会强制覆盖；关闭客户端后，可把备份文件复制回settings.json恢复。
已有CC Switch会显示官方导入确认，不覆盖其他供应商；请确认本机导入。
助手不会修改Windows永久执行策略。

连接检查只请求模型列表和软件版本，不发送收费的模型推理。
官方网站封号不等于官方Key已失效，停用由管理员在供应商官网处理。
