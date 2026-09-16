# Microsoft 365 与 MariOS

MariOS 与 Microsoft 365 打通后，租约、航次、发票等业务记录可与邮件、Teams、SharePoint / OneDrive 协同使用，形成统一的航运企业协作生态。

## 管理员如何连接

1. 登录后打开 **控制平面 → Office 生态**。
2. 点击 **连接 Microsoft 365**，完成组织授权（Entra ID）。
3. 执行 **健康检查**，再按需同步邮件、文件库或 Teams。
4. 在插件列表中侧载 Outlook / Teams / Excel 清单，并标记为已安装。

开发或演示环境可在未配置应用密钥时使用安全的演示连接，便于验证流程。

## 主要能力

| 能力 | 说明 |
|------|------|
| 邮件 | 查看业务相关收件上下文；在启用 Graph 时可发送邮件 |
| 文件 | 列出 OneDrive / SharePoint 库，为航次或租约创建文件夹并回写链接 |
| Teams | 向频道发送审批、ETA 等通知 |
| Webhook | 向 Power Automate 或伙伴系统推送业务事件 |
| API 密钥 | 插件与集成方使用 `X-API-Key` 调用开放 API |

## 生产环境配置提示

- 在 Entra ID 注册应用，重定向至：`{API 公网地址}/api/v1/office/oauth/callback`
- 授予邮件、文件、站点、频道消息等所需委托权限，并启用 `offline_access`
- 配置环境变量：`MICROSOFT_CLIENT_ID`、`MICROSOFT_CLIENT_SECRET`、`MICROSOFT_TENANT`
- 插件清单中的域名请改为贵司生产域名

更完整的操作说明见产品内 **帮助 → 知识中心 → Microsoft 365 生态**。
