# FPE 工程与代码组织

## 1. 目录设计

```text
fpe/
  docs/
    README.md
    FPE_总体设计.md
    FPE_接口与数据模型.md
    FPE_工程与代码组织.md
    FPE_开发计划与依赖清单.md
  src/
    fpe/
      __init__.py
      settings.py               # 配置（保留在顶层）
      models/
        __init__.py             # 所有核心结构体与枚举
      collectors/
        __init__.py             # 系统信息采集函数
      command/
        __init__.py             # 公共命令执行重新导出
        executor.py             # 远端命令执行
      analyzer/
        __init__.py             # 分析编排重新导出
        engine.py               # 分析编排主流程 (状态机)
      renderer/
        __init__.py             # 输出渲染重新导出
        output.py               # 文本/JSON 格式化输出
      mcp/
        server.py               # MCP Server 入口（stdio/SSE）
        tools.py                # MCP 工具注册与 handler
      api/
        app.py                  # FastAPI 入口
      cli/
        main.py                 # Typer CLI 入口
  tests/
    unit/
    integration/
    fixtures/
  scripts/
  .venv/
  pyproject.toml
  .env.example
```

说明：

1. 本项目默认使用宿主机 `python3.12`
2. 虚拟环境目录统一使用 `.venv/`
3. 所有开发、测试、运行命令默认基于 `.venv`
4. 远端采集默认通过 SSH 免密执行

## 2. 简化后的文件职责

### 2.1 `models/__init__.py`

放所有核心结构体：

1. context
2. route
3. link
4. ovs
5. state
6. output

### 2.2 `command/executor.py`

远端命令执行与上下文管理：

1. SSH 连接与本地 subprocess 运行
2. 命令运行（自动注入 `ip netns exec` 等上下文前缀）
3. 执行上下文从环境变量读取（`FPE_HOST`, `FPE_NAMESPACE`, `FPE_VRF` 等）
4. 超时 / 重试
5. 原始输出返回

### 2.3 `collectors/__init__.py`

放所有采集函数：

1. `get_interface_context`
2. `get_ip_rules`
3. `get_route`
4. `resolve_next_hop`
5. `get_ovs_info`
6. `check_neighbor`

### 2.4 `analyzer/engine.py`

唯一主流程入口：

1. 接收输入
2. 顺序调用 collectors
3. 组织 path
4. 返回结果

### 2.5 `renderer/output.py`

1. JSON 输出
2. 文本输出
3. AI 摘要输入准备

## 3. 代码组织规则

1. `models/__init__.py` 只放结构体和枚举
2. `collectors/__init__.py` 只负责取数和解析
3. `analyzer/engine.py` 只负责业务编排
4. `mcp/tools.py` 只做 MCP tool 暴露
5. `renderer/output.py` 只做格式化输出

## 4. 依赖反转规则

初版不引入过多接口抽象，只保留一条基本边界：

1. `analyzer/engine.py` 不直接拼 SSH 细节，而是调用 `command/executor.py`

## 5. 推荐类设计

### 5.1 Settings

```python
class Settings(BaseSettings):
    # ── Execution context ──────────────────────────────
    host: str | None = None             # FPE_HOST / FPE_TARGET_HOST
    namespace: str | None = None        # FPE_NAMESPACE
    vrf: str | None = None              # FPE_VRF
    ip_version: int = 4                 # FPE_IP_VERSION
    ingress_if: str | None = None       # FPE_INGRESS_IF

    # ── SSH ────────────────────────────────────────────
    target_host: str | None = None
    target_hosts: str | None = None
    ssh_user: str = "root"
    ssh_port: int = 22
    ssh_key_path: str | None = None
    ssh_connect_timeout: int = 10

    # ── LLM / model ────────────────────────────────────
    model_base_url: str
    model_api_key: str
    model_name: str
    model_timeout: int = 30

    # ── Behaviour ──────────────────────────────────────
    enable_ovs: bool = True
    default_max_hops: int = 16
    log_level: str = "INFO"
```

### 5.2 RemoteExecutor

```python
class RemoteExecutor:
    """Reads host and exec_ctx entirely from environment variables."""

    def run(self, cmd: str) -> str:
        """Run *cmd* locally or remotely per FPE_HOST."""
        ...
```

### 5.3 Analyzer

```python
class Analyzer:
    def analyze(
        self,
        packet: PacketContext,
        options: dict | None = None,
    ) -> AnalysisResult:
        ...
```

## 6. 错误设计

建议定义统一异常层级：

1. `FpeError`
2. `ConfigError`
3. `ToolExecutionError`
4. `ParseError`
5. `UnsupportedTopologyError`
6. `ModelApiError`

统一错误映射到：

1. HTTP 错误响应
2. MCP `ToolResult.error`
3. CLI 错误输出

## 7. 测试设计

### 7.1 单元测试

覆盖：

1. 模型校验
2. collector 解析函数
3. analyzer 主流程
4. 路径构建逻辑

### 7.2 集成测试

覆盖：

1. CLI 端到端
2. API 端到端
3. MCP tool 端到端
4. MCP `stdio` 端到端
5. MCP `SSE` 端到端

### 7.3 Fixture 设计

建议准备：

1. `ip rule` 示例输出
2. `ip route` 示例输出
3. `ip -d link show` 示例输出
4. `ovs-vsctl` 示例输出

## 8. 代码风格建议

1. 使用类型标注
2. 使用 Pydantic 模型作为边界协议
3. 优先少文件、少层次
4. 不在 collector 中写跨工具推理
5. 不在 MCP tool 中写业务逻辑

## 9. 开发环境约束

1. 使用宿主机 `python3.12 -m venv .venv` 创建虚拟环境
2. 使用 `.venv/bin/python`、`.venv/bin/pip` 运行项目命令
3. 不使用系统全局 `pip` 安装项目依赖
4. SSH 免密由环境预先准备，程序只消费现有 SSH 能力

## 10. MCP 实现约束

1. MCP 必须同时支持 `stdio` 和 `SSE` 两种形式
2. `SSE` 模式必须支持 `POST` 建立连接
3. 传输适配层不能侵入 handler 和 service 业务逻辑

## 11. 环境变量配置

所有配置通过 `pydantic-settings` 集中管理（`fpe/settings.py`），支持 `.env` 文件或环境变量注入。

```text
# ── 执行上下文 ──────────────────
FPE_HOST              # 目标主机 IP（空=本地执行）
FPE_NAMESPACE         # ip netns ns 名称
FPE_VRF               # VRF 名称
FPE_IP_VERSION        # IP 协议版本（默认 4）
FPE_INGRESS_IF        # 入接口名称

# ── SSH ──────────────────────────
FPE_TARGET_HOST
FPE_TARGET_HOSTS
FPE_SSH_USER          # SSH 用户名（默认 root）
FPE_SSH_PORT          # SSH 端口（默认 22）
FPE_SSH_KEY_PATH      # SSH 密钥路径

# ── LLM / model ──────────────────
FPE_MODEL_BASE_URL
FPE_MODEL_API_KEY
FPE_MODEL_NAME
FPE_MODEL_TIMEOUT

# ── Behaviour ────────────────────
FPE_ENABLE_OVS        # 启用 OVS 采集（默认 true）
FPE_DEFAULT_MAX_HOPS  # 最大跳数（默认 16）
FPE_LOG_LEVEL         # 日志级别（默认 INFO）
```

约束：

1. 程序不负责创建、分发或更新 SSH 密钥
2. 程序不负责交互式输入密码
3. 无免密能力时视为环境未准备完成
4. `FPE_HOST` 与 `FPE_TARGET_HOST` 互为别名，任意设置一个即可
