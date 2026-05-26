# FPE 开发计划与依赖清单

## 0. 开发环境硬约束

1. Python 版本固定为宿主机的 `python3.12`
2. 必须使用 `venv`，统一虚拟环境目录为 `.venv`
3. 项目初始化方式固定为 `python3.12 -m venv .venv`
4. 安装依赖、运行测试、启动服务都必须使用 `.venv` 中的解释器和工具
5. 远端采集默认通过 SSH 免密执行

## 1. 所有开发库清单

### 1.1 必选库

1. `pydantic`
   用于结构体、配置和接口校验。
2. `pydantic-settings`
   用于环境变量配置。
3. `fastapi`
   用于 HTTP API。
4. `typer`
   用于 CLI。
5. `httpx`
   用于厂商模型 API。
6. `tenacity`
   用于重试控制。
7. `python-dotenv`
   用于本地环境变量加载。
8. `pytest`
   用于测试。
9. `pytest-asyncio`
   用于异步测试。
10. `uvicorn`
   用于本地 API 服务运行。

### 1.2 初版强烈建议

1. `orjson`
   提升 JSON 性能。
2. `rich`
   改善 CLI 输出。

### 1.3 后续增强库

1. `pyroute2`
2. `networkx`

### 1.4 标准库

1. `subprocess`
2. `asyncio`
3. `pathlib`
4. `ipaddress`
5. `json`
6. `re`
7. `logging`
8. `enum`
9. `dataclasses`
10. `typing`

## 2. 首版为什么不用更多库

1. 信息获取层优先追求与现网命令一致
2. 过早把命令执行替换成更高层库，容易掩盖真实输出差异
3. 先稳定数据结构，再替换底层实现，风险更小

## 3. 分阶段开发计划

### 3.1 Phase A - 骨架

开发内容：

1. 目录初始化
2. Pydantic 模型
3. CLI / API / MCP 基础入口
4. 远端执行器
5. 最小 analyzer

交付物：

1. 可运行空壳
2. 可调用的最小 analyze 流程

### 3.2 Phase B - 信息获取

开发内容：

1. interface collector
2. rules collector
3. route collector
4. link collector
5. neighbor collector
6. OVS collector

交付物：

1. 可输出结构化采集结果
2. 支持 namespace / VRF 上下文

### 3.3 Phase C - 链路骨架

开发内容：

1. 状态机
2. hop 推进
3. path node 组织
4. incomplete / failed 终态

交付物：

1. 可输出路径骨架
2. 可输出 decision chain

### 3.4 Phase D - 路径解释

开发内容：

1. 简要解释
2. 风险项
3. 可信度

交付物：

1. AI 应用最小解释能力

## 3.5 简化开发原则

1. 不先拆很多 service / factory / repository
2. 能用一个文件解决的，不先拆成多个目录
3. 先把远端采集跑通，再考虑模式升级

## 4. 运行方式

### 4.1 安装

建议使用 `pyproject.toml` 管理依赖。

初始化方式：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e .
```

环境变量示例：

```bash
export FPE_TARGET_HOST=10.0.0.10
export FPE_SSH_USER=root
export FPE_SSH_PORT=22
export FPE_SSH_KEY_PATH=~/.ssh/id_rsa
```

说明：

1. SSH 免密需由环境预先准备
2. 程序不参与密钥分发和密码输入

### 4.2 本地运行

CLI：

```bash
.venv/bin/python -m fpe.cli.main analyze --src-ip 10.0.0.2 --dst-ip 8.8.8.8
```

> 目标主机通过环境变量 `FPE_HOST` / `FPE_TARGET_HOST` 配置，不通过 CLI 参数。

API：

```bash
.venv/bin/uvicorn fpe.api.app:app --reload
```

MCP：

```bash
.venv/bin/python -m fpe.mcp.server
```

## 5. 交付标准

1. `docs` 文档完整
2. MCP 协议明确
3. 结构体完整
4. 目录可直接落地
5. 设计模式明确
6. 依赖清单完整
