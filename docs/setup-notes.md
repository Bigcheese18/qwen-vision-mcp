# 搭建笔记：Claude Code + Qwen3-VL 视觉 MCP

记录这套视觉 MCP 服务器的搭建过程、踩过的坑和性能实测数据。

## 背景

Claude Code 本身是支持多模态的（Claude 模型原生能看图），但如果主模型是**纯文本模型**
（例如本机挂在 DeepSeek 后端），就看不到图片。解法不是换主模型，而是通过 **MCP 工具**
把视觉能力封装成 `analyze_image(file_path, prompt)` 暴露给文本模型——模型把图片路径交给工具，
工具后台调 Qwen3-VL 把图片解析成文本返回。这是最贴合 Claude Code 架构、且不影响代码编辑能力的方案。

## 架构

```
Claude Code (纯文本主模型)
   │  MCP stdio
   ▼
server.py (FastMCP)
   │  HTTP (OpenAI 兼容 /chat/completions)
   ▼
DashScope: qwen3-vl-235b-a22b-thinking
```

图片以 `data:image/...;base64,...` 的 `image_url` 形式发送。

## 踩过的坑

1. **`mcp` 包版本**：2.0 移除了 `FastMCP`（改成 `MCPServer`/`MCPTool`/`stdio_server`，API 大改）。
   必须锁 `mcp>=1.2.0,<2`，用社区标准的 FastMCP API。

2. **Windows 控制台编码**：Python 在 Windows 默认用 GBK 输出，而 MCP stdio 需要 UTF-8，
   中文结果会乱码甚至破坏 JSON 帧。解决：server.py 启动时对 stdout/stderr 做
   `reconfigure(encoding="utf-8")`。

3. **`.env` 加载依赖 cwd**：`load_dotenv()` 默认找当前工作目录。Claude Code 从任意目录启动，
   必须用 `load_dotenv(Path(__file__).resolve().parent / ".env")` 显式定位。

4. **MCP 只在启动时加载**：改了 server.py 后必须重启 Claude Code 才生效。

5. **DashScope 并发受限**：同一 API Key 有 QPS/并发限制，多路并行请求会被服务端排队，
   并行收益远低于预期（实测仅约 1.2x）。

## 性能实测（2026-08）

| 场景 | 默认 (thinking) | `fast=True` | 缓存命中 |
|---|---|---|---|
| 小图 350B（颜色判断） | ~6-7s | ~2-3s（快约 2.4x） | 0.00s |
| 大图 154KB（新闻截图） | 16~50s | 同样区间 | 0.00s |

- **大图延迟抖动极大（16~50s）**，由服务端负载主导，`fast` 开关影响很小
  ——大图瓶颈在视觉 token 处理和输出长度，不在思考过程。
- **缓存是最大赢家**：同图+同问题秒回，无损。

### 按场景选档（"既快又准"）

| 场景 | 用法 |
|---|---|
| 小图 / 简单任务（OCR、颜色、单元素） | `fast=True` |
| 大图 / 复杂推理（歧义图表、多步理解） | 默认（thinking 开着，不额外耗时） |
| 重复分析同一张图 | 靠缓存秒回，无需手动 |
| 一次分析多张图 | `analyze_images_batch` |

## 防"脑补"验证法

视觉模型偶尔会补全不确定的细节。可复用验证法：**用 Puppeteer 抓真实 DOM 文本，与模型描述
逐条比对**。本机对 IT之家首页实测：头条/日榜条目全部命中，防推测提示词生效后会主动标注
`[截断]`（宁可承认看不清，也不编）。

好的默认提示词模板（已内置）：
> 只描述图片中实际可见的内容，不要推测或补充图中没有的信息；文字若被截断或看不清，
> 请明确标注[截断]或[看不清]。

## 可能的进一步优化

- **裁剪 ROI**：别整页截图，只截目标区域，视觉 token 大幅减少。
- **发图前压缩**：大图用 Pillow 缩尺寸 / 转 JPEG。
- **换更快的模型**：若只做 OCR 不求思考，可换 `qwen-vl-plus` 等快模型。

## DeepSeek Harness (dsh) 集成笔记（2026-08 实测）

### 1. 注册 MCP 必须用 `insert:` 语法

dsh 的 profile 补丁层（`~/.dsh/profiles/<profile>/cordis.patch.yml`）是 **cordis loader patch** 格式：

- 普通 `id:` 条目 = **覆盖已存在的插件行**；若 id 不存在会被**静默跳过**（loader 只打一条 warning，插件不加载也不报错）。
- 新增插件 = 必须用 `insert:` 键包一层。

```yaml
- insert:
    - id: mcp-qwen-vision
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: qwen-vision
        transport: stdio
        command: 'C:\Users\<你>\qwen-vision-mcp\.venv\Scripts\python.exe'
        args: ['C:\Users\<你>\qwen-vision-mcp\server.py']
```

> 对比参照：`dsh-base` bundle 的 patch 文件整体就是**一个大 `insert:` 块**，后续层（其他 bundle、用户层）再用 `id:` 定位覆盖。

### 2. 补丁文件 HMR 热重载，无需重启

`cordis.patch.yml` 被 `watchUserPatches` 持续监视，保存即触发事务式重组（失败回滚到上一个可用树）。改配置/新增插件**不用重启 dsh**。MCP 配置变更会触发断开重连。

### 3. 排查工具是否真的注册了

- 会话的工具列表是**会话启动时固定的**：新注册的工具（如 MCP 工具、自定义子代理工具）在**当前会话看不到**，新开会话才出现。
- 想即时验证：让一个全新子代理报告自己的工具列表（子代理从 harness 当前注册表构建工具集），或看 dsh 日志里的 loader warning。

### 4. 另一种方案：vision 子代理工具（对比）

不依赖 MCP，用 dsh 自带的子代理工具把视觉模型包成专用委派工具：

```yaml
- insert:
    - id: tool-subagent-vision
      name: '@deepseek-ai/dsh-tool-subagent'
      config:
        provider: spawn
        toolName: vision
        backgroundMode: continuable
        agentOptions:
          provider: dashscope          # llm-pi-ai 配置的 provider 路由
          model: qwen3-vl-235b-a22b-thinking
```

前提：`settings.yaml` 里 `llm-pi-ai.providers.dashscope` 配好 API Key（`QWV_API_KEY`，可存在 `~/.dsh/.credentials.yaml`）。

两种方式对比：

| | MCP (`analyze_image`) | `vision` 子代理 |
|---|---|---|
| 调用 | `mcp__qwen-vision__analyze_image` | `vision` 工具 → Qwen-VL 子代理 |
| 并发批量 | `analyze_images_batch` 内置 | 需自行并发 |
| 缓存 | 服务端内存缓存（同图同问秒回） | 无 |
| 子代理上下文 | 无（纯工具调用） | 可 continuable 追问，后台运行 |
| 依赖 | 本仓库 venv + .env | 仅 llm-pi-ai 配置 |

### 5. 经验教训

- 插件"配了但没生效"时，先怀疑 patch 语法（`insert:`），再看日志 warning——静默失败最容易浪费排查时间。
- 主模型看不到图时，先查自己的工具列表里有没有视觉工具（MCP 工具名形如 `mcp__<serverName>__<toolName>`），别急着绕路。
