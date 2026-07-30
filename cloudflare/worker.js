// Cloudflare Worker：新闻台刷新代理
// 作用：服务端保管 GitHub PAT，对外暴露一个无需鉴权的 /refresh 接口，
//      前端按钮直接调用它来触发 GitHub Actions 的 repository_dispatch。
//      这样朋友点“刷新”也完全不需要 token。
//
// 部署（详见同目录 README.md）：
//   npx wrangler secret put GITHUB_PAT      # 你的 GitHub Fine-grained PAT（Actions: write）
//   npx wrangler secret put REFRESH_KEY     # 可选：轻量防护密钥（与前端 WORKER_KEY 一致）
//   npx wrangler deploy

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type,Authorization',
};

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...CORS, 'content-type': 'application/json; charset=utf-8' },
  });
}

export default {
  async fetch(request, env) {
    // 1) 处理 CORS 预检
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: CORS });
    }

    // 2) 仅响应 /refresh（或根路径）
    const url = new URL(request.url);
    if (url.pathname !== '/refresh' && url.pathname !== '/') {
      return json({ error: 'not found' }, 404);
    }

    // 3) 可选：轻量密钥校验（防止裸 URL 被随意调用，仅此而已）
    if (env.REFRESH_KEY && url.searchParams.get('key') !== env.REFRESH_KEY) {
      return json({ error: 'unauthorized' }, 401);
    }

    // 4) 读取配置（来自 wrangler.toml [vars] 与 secret）
    const owner = env.REPO_OWNER;
    const repo = env.REPO_NAME;
    const pat = env.GITHUB_PAT;
    if (!owner || !repo || !pat) {
      return json({ ok: false, error: 'worker not configured (missing secrets)' }, 500);
    }

    // 5) 触发 GitHub workflow_dispatch（= 跑 refresh.yml 工作流）
    //    注意：Fine-grained PAT 不支持 repository_dispatch，改用 workflow_dispatch
    const WORKFLOW_ID = env.WORKFLOW_ID || '323723786';
    try {
      const gh = await fetch(`https://api.github.com/repos/${owner}/${repo}/actions/workflows/${WORKFLOW_ID}/dispatches`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${pat}`,
          'Accept': 'application/vnd.github+json',
          'Content-Type': 'application/json',
          'X-GitHub-Api-Version': '2022-11-28',
          'User-Agent': 'newsdesk-worker',
        },
        body: JSON.stringify({ ref: 'main' }),
      });

      if (gh.status === 204) {
        return json({ ok: true, msg: '已触发刷新，云端生成约需1分钟，稍后点按钮再刷' });
      }
      const txt = await gh.text();
      return json({ ok: false, status: gh.status, detail: txt.slice(0, 300) }, 502);
    } catch (e) {
      return json({ ok: false, error: String(e) }, 502);
    }
  },
};
