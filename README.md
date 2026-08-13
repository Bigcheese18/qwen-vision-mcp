# qwen-vision-mcp

给 Claude Code（或任何支持 MCP 的客户端）挂上 **Qwen3-VL 视觉能力**的 MCP 服务器。
让纯文本主模型也能 OCR、识别截图 / UI 元素、理解图表。

后端走阿里云百炼（DashScope）的 **OpenAI 兼容接口**，默认模型 `qwen3-vl-235b-a22b-thinking`。

## 功能

| 工具 | 说明 |
|---|---|
| `analyze_image(file_path, prompt, fast)` | 分析单张本地图片（OCR / UI 识别 / 图表理解） |
| `analyze_images_batch(paths, prompt, fast)` | 并行分析多张图片 |

内置 **缓存**：同一张图 + 同一问题第二次直接秒回（不重复调用 API）。

`fast=True` 时关闭 thinking（`enable_thinking: false`）：小图/简单任务实测约快 2.4x；
大图收益很小（瓶颈在视觉 token 处理），可保持默认。

## 安装

需要 Python 3.10+。

```bash
cd qwen-vision-mcp
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# .venv/bin/python -m pip install -r requirements.txt          # macOS / Linux
```

> ⚠️ `requirements.txt` 锁定 `mcp>=1.2.0,<2`。**不要装 mcp 2.x** —— 它移除了 `FastMCP`，API 完全不兼容。

## 配置

```bash
cp .env.example .env
```

编辑 `.env` 填入你的阿里云百炼 API Key 和模型名。`.env` 已被 `.gitignore` 排除，不会提交。

## 注册到 Claude Code

```bash
claude mcp add --scope user --transport stdio qwen-vision -- \
  "C:/path/to/qwen-vision-mcp/.venv/Scripts/python.exe" \
  "C:/path/to/qwen-vision-mcp/server.py"
```

然后 **重启 Claude Code**（MCP 服务器只在启动时加载）。

## 注册到 DeepSeek Harness (dsh)

在 profile 的用户补丁层（如 `C:\Users\<你>\.dsh\profiles\web\cordis.patch.yml`）里**新增**一条 MCP 客户端插件：

```yaml
- insert:
    - id: mcp-qwen-vision
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: qwen-vision
        transport: stdio
        command: 'C:\path\to\qwen-vision-mcp\.venv\Scripts\python.exe'
        args: ['C:\path\to\qwen-vision-mcp\server.py']
```

> ⚠️ **必须用 `insert:` 语法**。dsh 的 patch 机制里，普通 `id:` 条目只用于**覆盖已存在的插件行**；指向不存在的 id 会被**静默跳过**（日志里仅一条 warning），插件不加载也不报错——排查时极易忽略。

保存后 dsh 通过 HMR 热重载补丁，**无需重启**。注册成功后模型会看到
`mcp__qwen-vision__analyze_image` / `mcp__qwen-vision__analyze_images_batch` 两个工具。

## 用法示例

在 Claude Code 会话里直接说：

> 用 analyze_image 看看 `D:\screenshots\ui.png`，识别里面的按钮和坐标

> 用 fast 模式批量分析 `imgs/` 下的截图，提取每张的文字

> 提取这张网页截图里的新闻标题

## 安全提示

- API Key 只存在本地 `.env`，**不要提交到任何仓库**。
- 若 Key 疑似泄露，去百炼控制台吊销重发。
- 涉及精确信息（价格、数字、坐标）时，请在 prompt 里强调"只按图中可见内容回答，不要推测"。

## 项目结构

```
server.py          # MCP 服务器（FastMCP + DashScope OpenAI 兼容接口）
test.py            # 端到端测试（自生成测试图 → 调用分析）
smoke_stdio.py     # MCP stdio 协议冒烟测试
bench.py           # 并行 vs 串行基准测试
requirements.txt
.env.example
docs/setup-notes.md  # 搭建过程、踩坑与性能实测
docs/prompt-templates.md  # 图片识别提示词模板（详/标/简/定向四版 + 调整原则）
```

## License

MIT
