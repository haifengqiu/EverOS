# va-dev 分支交接文档

[Home](../../README.md) > [Docs](../README.md) > [Development](.) > va-dev Handover

---

## 分支概况

| 项 | 值 |
|----|-----|
| 分支 | `va-dev` |
| 基线 | `main` |
| Commits | 4 |
| 改动文件 | 11（含 uv.lock） |
| 核心代码改动 | 5 文件，+151 / -7 行 |

---

## 核心改动

### 1. sync_mode 默认值修正

**文件**: `src/core/request/timeout_background.py`

`is_background_mode_enabled()` 中 `sync_mode` 查询参数默认值从 `"true"` 改为 `"false"`，使后台模式默认生效，与文档描述一致。

改动前：默认同步（`sync_mode=true`），后台模式不生效。
改动后：默认后台（`sync_mode=false`），传 `sync_mode=true` 切回同步。

### 2. Demo 202 响应处理

**文件**: `demo/utils/simple_memory_manager.py`

`store()` 新增 HTTP 202 状态码处理。后台模式下 API 超时返回 202，原代码未处理会导致 JSON 解析失败。

### 3. LLM 流式生成接口

**文件**:
- `src/memory_layer/llm/protocol.py` — `LLMProvider` Protocol 新增 `generate_stream` 签名
- `src/memory_layer/llm/llm_provider.py` — `LLMProvider` 代理层新增 `generate_stream`，带 `timed("call_llm_stream")` 埋点
- `src/memory_layer/llm/openai_provider.py` — `OpenAIProvider` 实现 SSE 流式解析

```python
async def generate_stream(
    self,
    prompt: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: dict | None = None,
) -> AsyncGenerator[str, None]:
```

实现要点：
- 不使用 key 轮转 / 重试（长连接中途无法重试），取首个 key
- 使用 `aiohttp` 的 `iter_chunked` 逐块读取，按行解析 SSE `data:` 帧
- 记录首 chunk 延迟和总耗时
- 超时：total=600s, sock_connect=30s, sock_read=60s

---

## 新增文件

| 文件 | 用途 | 运行方式 |
|------|------|----------|
| `demo/chat/session_stream.py` | 流式聊天会话管理（ChatSessionStream） | 被 chat_with_memory_stream.py 导入 |
| `demo/chat_with_memory_stream.py` | 交互式流式聊天入口 | `uv run python src/bootstrap.py demo/chat_with_memory_stream.py` |
| `demo/test_stream_demo.py` | 非交互式 generate_stream 验证脚本 | `uv run python demo/test_stream_demo.py` |

---

## 基础设施修复

### Milvus 代理干扰

**症状**: `milvus-standalone` 容器一直处于 `starting` 状态，日志显示 gRPC 连接 etcd 被路由到 `127.0.0.1:1081`。

**原因**: 宿主机设置了 `HTTP_PROXY`，Docker 容器继承后 Milvus gRPC 连接受代理拦截。

**修复**: `docker-compose.yaml` 中 `milvus-standalone` 服务新增：

```yaml
environment:
  NO_PROXY: "milvus-etcd,milvus-minio,localhost,127.0.0.1"
  no_proxy: "milvus-etcd,milvus-minio,localhost,127.0.0.1"
  HTTP_PROXY: ""
  HTTPS_PROXY: ""
  http_proxy: ""
  https_proxy: ""
```

---

## 验证结果

| 测试 | 结果 | 关键指标 |
|------|------|----------|
| simple_demo.py | PASS | Store 7 条 → 后台提取 12 foresight + 10 atomic fact → Search 返回命中 |
| generate_stream() | PASS | 首 token 702ms，总 4342ms，12 chunks，流式加速 6.2x |
| generate() 基线 | PASS | 非流式 4973ms，响应内容一致 |
| API store+search | PASS | HTTP 200，正常返回 |

---

## 已知问题 & 后续建议

| 项 | 说明 | 优先级 |
|----|------|--------|
| `prompt_system_role_simple_*` i18n 键缺失 | `session_stream.py` 引用了这两个键，但 `demo/ui/i18n_texts.py` 未定义，会 fallback 为键名本身。不影响运行，但 system prompt 不理想 | 中 |
| `@timeout_to_background` 未接入 controller | `MemoryController` 的 endpoint 未使用此装饰器，202 路径不会触发 | 低（架构决策） |
| 流式聊天仅交互模式 | `chat_with_memory_stream.py` 需要 stdin 输入，无法 CI 自动化 | 低 |

---

## 快速启动

```bash
cd methods/EverCore

# 1. 启动中间件
docker compose up -d

# 2. 等待 Milvus 就绪（首次约 90s）
docker inspect --format='{{.State.Health.Status}}' memsys-milvus-standalone
# 期望输出: healthy

# 3. 配置 .env（首次）
cp env.template .env
# 编辑 .env，填入 LLM / Embedding / Rerank 的 API 配置

# 4. 启动 API 服务
uv run python src/run.py

# 5. 运行基础 demo（另一终端）
uv run python src/bootstrap.py demo/simple_demo.py

# 6. 验证流式生成（非交互）
uv run python demo/test_stream_demo.py

# 7. 交互式流式聊天（可选）
uv run python src/bootstrap.py demo/chat_with_memory_stream.py
```
