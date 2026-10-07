# 接口与供应商扩展

接口前缀 `/portal-api`。会话Cookie为HttpOnly；GET /me返回CSRF值，后续写操作带X-CSRF-Token。浏览器Origin必须匹配PUBLIC_ORIGIN。密码、Key与票据不放URL。

## 学生

- POST /auth/register：用户名（支持邮箱，3至128位）、密码、显示名、邀请码；邀请次数、建号、库存分配在同一写事务中完成。首尾空格去除，邀请码忽略大小写；字段校验失败不会消耗邀请码。
- POST /auth/login、POST /auth/logout、GET /me：身份、状态、个人账务、Key遮罩。
- GET /public：站点、收款码和公告，key_delivery_enabled表明当前地址是否允许密钥导入与领取。
- GET/POST /invites、POST /invites/{id}/disable：成员只查看和停用自己的邀请码。生成单次、7天有效的邀请码；事务限制同时最多5个有效未用码。暂停成员不能生成，暂停邀请人的未用码也不能注册。只在生成时返回完整邀请码。
- GET/POST /orders：金额用整数分，支持1000/2000/5000/10000；需确认5%和不退款说明，先分配Key。
- POST /orders/{id}/paid：声明付款，不直接记账。
- POST /orders/{id}/cancel：只取消尚未付款的本人订单，不退款。
- GET /usage：核对区间、时间和作废状态。
- POST /installer/package：可选JSON正文`{"clients":["claude-code","deepseek-harness"]}`，至少选择一个；不传正文兼容旧版默认Claude Code。ZIP的selection.json记录选项，窗口可再次调整。正常但未分配Key的账户（含管理员）可下载软件包，不生成ticket.json、不占用库存。已有Key时包含30分钟、单次、绑定用户和Key的票据，新下载使前一未使用票据失效。暂停账户仍拒绝下载，所有领取仍要求可信HTTPS。
- POST /installer/exchange：票据在JSON正文，无需Cookie；事务消费后返回Claude和Harness直连配置。Harness仅对已核实的DeepSeek供应商启用。暂停、到期、替换状态均阻止领取。

## 管理

- GET /admin/overview、GET /admin/users、POST /admin/users/{id}/action：汇总及block/activate/assign。
- POST /admin/users：管理员直接创建成员账户，无需邀请码；自动分配可用官方库存。
- PATCH /admin/users/{id}：编辑成员的用户名/邮箱和称呼。登录名改变时清除旧会话，账务与Key归属保留。
- POST /admin/users/{id}/password：重置成员密码，清除该用户全部登录会话、失效未使用票据。管理员账号不能通过成员管理入口修改。
- GET /admin/keys、POST /admin/keys/import：遮罩列表、批量导入、HMAC指纹去重、Fernet加密。
- POST /admin/keys/{id}/inventory：disable/enable，仅允许从未分配的库存。停用库存不等于官网撤销。
- POST /admin/keys/{id}/assign：指定一个正常、没有当前Key的成员；事务锁及唯一索引阻止并发重复分配。
- POST /admin/keys/{id}/deadline：设置网站提醒，不修改供应商期限。
- POST /admin/keys/{id}/verify-revocation：官网删除后的效果核验；不是远程删除命令。
- GET /admin/orders、POST /admin/orders/{id}/review：approve/reject。写事务和唯一流水防止重复确认。
- GET/POST /admin/usage、POST /admin/usage/{id}/void：人工增量、同Key同模型区间防重、唯一reference、保留原始记录的纠错。
- GET/POST /admin/invites、POST /admin/invites/{id}/disable：邀请码只在创建时完整显示，数据库存摘要。
- GET/POST /admin/providers：Anthropic直连基础地址、模型及核验地址。
- POST /admin/settings、POST /admin/payment-qr/{wechat|alipay}：站点和收款码；仅PNG/JPEG。
- 公告发布/撤下、GET /admin/audits：审计不保存密码、票据、Key或对话。

Key流转：available → assigned → pending_revocation → revoked。已发Key不会回到available。未发库存可available ↔ disabled。官网核验完成后才能恢复用户并分配新Key。

管理员侧栏直接进入`/admin/users`账户管理和`/admin/keys`官方Key号池。号池支持粘贴及UTF-8 TXT文件、重复行预览、状态搜索与指定分配。非HTTPS地址明确显示界面验证模式并禁用真实Key输入和导入，服务端同样拒绝，避免只在浏览器上限制。

邀请码归属使用兼容旧数据的invite_creators关系表，旧管理记录从审计补齐。账务、Key与旧邀请码不改写。邀请码分享链接`/login?invite=...`自动打开注册并填入邀请码，链接不包含官方Key。

## 扩展

portal/providers.py隔离客户端配置、鉴权探测与管理能力。DeepSeek没有已核实的远程撤销、独立预算、到期或单Key用量接口，相关能力均关闭。

新供应商先加入PROVIDER_ALLOWED_HOSTS，再配置地址。能力默认未验证，不能自动核验停用或假装具有独立额度。需要远程管理时实现ProviderManagement契约，核实接口并补充恢复与幂等测试后再开启能力；模型继续直达供应商。

没有/v1模型代理。服务器只执行少量管理员模型列表核验，不发起用户模型推理。
