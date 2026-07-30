# 新闻台刷新代理（Cloudflare Worker）

让「刷新」按钮在**不暴露 GitHub token** 的前提下触发 GitHub Actions 工作流。
PAT 只存在于 Cloudflare Worker 服务端（secret），前端只打这个公开的 /refresh 接口。

## 部署步骤（只需做一次）

1. 安装并登录 wrangler（需你自己的 Cloudflare 账号，免费）：
   ```bash
   npx wrangler login
   ```

2. 设置密钥（**不要**把 PAT 粘贴到聊天/代码里）：
   ```bash
   npx wrangler secret put GITHUB_PAT
   # 提示输入时，粘贴你新建的 GitHub Fine-grained PAT（只需 Actions: write，仅本仓库）
   ```
   可选防护：
   ```bash
   npx wrangler secret put REFRESH_KEY
   # 设置一个任意字符串；启用后需同步填到前端 HTML 的 WORKER_KEY
   ```

3. 部署：
   ```bash
   npx wrangler deploy
   ```
   部署成功会输出地址，形如：
   `https://newsdesk-refresh-proxy.<你的workers子域>.workers.dev`

4. 把上一步得到的地址（加上 `/refresh`）填回前端：
   打开 `financial-news-desk.html`，修改常量
   ```js
   const WORKER_URL='https://newsdesk-refresh-proxy.<你的workers子域>.workers.dev/refresh';
   ```
   若设置了 REFRESH_KEY，把 `WORKER_KEY` 也改成相同字符串；否则留空。

5. 提交并推送 HTML 即可生效。

## 安全说明
- 真正的凭证（PAT）**只在 Cloudflare 服务端**，任何人点按钮都拿不到。
- `/refresh` 是公开接口，理论上任何人可调用；但最多只是触发你的工作流（GitHub 有频率限制），不会泄露任何数据或权限。
- 建议 PAT 用**新建的 Fine-grained** 令牌，权限收敛为仅本仓库的 `Actions: write`，并定期轮换。
