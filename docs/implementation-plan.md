# 已实现方案：DeepSeek直连网站与可视化安装器

此文件替换早期网关草案。用户最终确认模型直接从客户端发送到供应商，服务器仅承担登录、收款、Key发放、官网撤销待办和安装包下载。

实现与启动步骤见 [README](../README.md)，部署与恢复见 [deployment.md](deployment.md)，接口与适配层见 [api.md](api.md)，验证范围见 [verification.md](verification.md)。

首版同一官方账号多个专属Key、5%服务费、人工账务、人工官网撤销。不承诺独立官方余额、自动消费截断或仅网站封号就停用官方Key。取消New API及模型反代。
