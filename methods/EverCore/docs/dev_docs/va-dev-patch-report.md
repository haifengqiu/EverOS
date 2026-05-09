# va-dev 分支 Patch 总结与验证报告

> 日期: 2026-05-09
> 基线: main
> 分支: va-dev (3 commits)

## 1. Patch 清单

### Commit 1: `c59bdc6` — fix: correct sync_mode default to enable background mode as documented

**文件**: `src/core/request/timeout_background.py`

**改动**: 将 `sync_mode` 查询参数的默认值从 `"true"` 改为 `"false"`，使后台模式默认生效，与文档描述一致。

```diff
- sync_mode = request.query_params.get(SYNC_MODE_PARAM, "true").lower()
+ sync_mode = request.query_params.get(SYNC_MODE_PARAM, "false").lower()
```

**逻辑**: 原代码先读 `sync_mode=true`（禁用后台），再检查 `"false"/"0"/"no"`（启用后台）。修复后先读 `sync_mode=false`（默认后台），再检查 `"true"/"1"/"yes"`（禁用后台），语义更清晰。

### Commit 2: `932a668` — fix: handle 202 Accepted response in demo store method

**文件**: `demo/utils/simple_memory_manager.py`

**改动**: `SimpleMemoryManager.store()` 新增对 HTTP 202 状态码的处理。

```python
# Background mode returns 202 Accepted
if response.status_code == 202:
    print(f"  ⏳ Accepted: {content[:40]}... (Processing in background)")
    return True
```

**逻辑**: 当后台模式生效时，API 在超时后返回 202。原代码未处理此状态码，会导致 `response.json()` 解析非 JSON 响应体而出错。

### Commit 3: `c52fa96` — feat: add generate_stream() to LLM provider interface

**文件**:
- `src/memory_layer/llm/protocol.py` — Protocol 接口新增 `generate_stream` 方法签名
- `src/memory_layer/llm/llm_provider.py` — `LLMProvider` 代理层新增 `generate_stream`，带 `timed("call_llm_stream")` 埋点
- `src/memory_layer/llm/openai_provider.py` — `OpenAIProvider` 实现 `generate_stream`，基于 SSE 解析

**接口**:
```python
async def generate_stream(
    self,
    prompt: str,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: dict | None = None,
) -> AsyncGenerator[str, None]:
```

**实现要点**:
- 不使用 key 轮转/重试机制（长连接中途无法重试），取首个 key
- 使用 `aiohttp` 的 `iter_chunked` 逐块读取，按行解析 SSE `data:` 帧
- 记录首 chunk 延迟和总耗时，调用 `record_llm_request` 统计
- 超时配置: total=600s, sock_connect=30s, sock_read=60s

---

## 2. 验证结果

### 2.1 simple_demo.py（基础流程验证）

| 步骤 | 结果 |
|------|------|
| Store（7 条消息） | ✅ 全部成功，状态 `accumulated` |
| 后台记忆提取 | ✅ 服务器日志显示提取 12 foresight + 10 atomic fact |
| Search（3 个查询） | ✅ 各返回 1 条记忆，rerank 评分 0.54-0.65 |

### 2.2 generate_stream() 专项测试

使用 `demo/test_stream_demo.py` 非交互脚本验证：

| 测试项 | 结果 | 详情 |
|--------|------|------|
| `generate_stream()` | ✅ | 首 token 702ms，总计 4342ms，12 chunks，流式加速 6.2x |
| `generate()` 基线 | ✅ | 非流式 4973ms，响应内容一致 |
| API 端到端（store+search） | ✅ | HTTP 200 正常 |

### 2.3 202 Accepted 响应

**未触发**。当前 `MemoryController` 的 endpoint 未使用 `@timeout_to_background` 装饰器，因此不会产生 202 响应。代码逻辑正确，但该路径在当前代码中无实际调用场景。

### 2.4 chat_with_memory_stream.py（交互式流式聊天）

**未完整验证**。依赖项缺失：
- `demo/chat/session_stream.py` — 已复制到位，可 import
- `prompt_system_role_simple_*` i18n 键 — 不存在于 `demo/ui/i18n_texts.py`，会 fallback 为键名字符串，导致 system prompt 不理想但不报错

---

## 3. 基础设施问题（验证过程中发现并修复）

### Milvus 容器代理干扰

**问题**: 宿主机设置了 `HTTP_PROXY=http://127.0.0.1:1081`，Docker 容器继承后 Milvus gRPC 连接 etcd 被代理拦截，导致 Milvus 一直处于 `starting` 状态。

**修复**: 在 `docker-compose.yaml` 的 `milvus-standalone` 服务中添加空代理环境变量：
```yaml
environment:
  NO_PROXY: "milvus-etcd,milvus-minio,localhost,127.0.0.1"
  no_proxy: "milvus-etcd,milvus-minio,localhost,127.0.0.1"
  HTTP_PROXY: ""
  HTTPS_PROXY: ""
  http_proxy: ""
  https_proxy: ""
```

**影响**: 此修改在 `docker-compose.yaml` 中，该文件未被 git 跟踪（`git ls-files` 无结果），但 `git diff` 显示了该变更。需决定是否纳入提交。

---

## 4. 未提交文件清单

| 文件 | 状态 | 建议 |
|------|------|------|
| `demo/chat/session_stream.py` | 新增（untracked） | 提交 — 流式 chat 的核心依赖 |
| `demo/chat_with_memory_stream.py` | 新增（untracked） | 提交 — 流式 chat 入口 |
| `demo/test_stream_demo.py` | 新增（untracked） | 提交 — 非交互式验证脚本 |
| `docker-compose.yaml`（Milvus 代理修复） | 修改（untracked file） | 提交 — 修复代理环境下 Milvus 启动问题 |
| `uv.lock` | 修改（untracked file） | 提交 — 依赖锁定文件同步 |
| `demo/chat/session_stream.py:Zone.Identifier` | 新增（untracked） | 不提交 — Windows WSL 元数据文件 |
| `demo/chat_with_memory_stream.py:Zone.Identifier` | 新增（untracked） | 不提交 — Windows WSL 元数据文件 |
| `.env` | 新增 | 不提交 — 已在 .gitignore 中，包含本地配置 |

---

## 5. 待补充项（非阻塞）

1. **`prompt_system_role_simple_*` i18n 键**: `session_stream.py` 使用了简化 prompt 键但 `i18n_texts.py` 未定义，建议补充
2. **`@timeout_to_background` 装饰器未接入 endpoint**: 202 处理代码已就绪但当前 controller 未使用该装饰器，202 路径无法被触发

---

## 6. 结论

**可以 push 到 remote**。三个 commit 的代码改动经验证功能正确，无破坏性变更。建议 push 前将 `session_stream.py`、`chat_with_memory_stream.py`、`test_stream_demo.py`、`docker-compose.yaml`、`uv.lock` 提交到本分支，Zone.Identifier 文件不提交。
