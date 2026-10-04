# CommerceOps 实施计划

> For agentic workers: execute tasks with test-driven development; independent rule, retrieval, and UI tasks use dispatching-parallel-agents after contracts are frozen.

**Goal:** 在 RAG_project 交付可运行的电商运营助手。
**Architecture:** FastAPI模块化单体，SQLite记录，确定性规则与可替换知识检索，原生中文页面。
**Tech Stack:** Python3.12+, FastAPI, SQLite, LightRAG SDK, HTML/CSS/JS.
**Spec:** spec.md，完整接口契约以该文件为准。

## Global Constraints
金额Decimal；本地127.0.0.1；模拟数据明确标注；不编造模型质量成绩；不修改上游源码；原有报告完整迁入docs/reports。

## Review Focus
未知资格不得当失败或允许；非有限/负金额与非法数量必须拒绝；时间带时区且终点不包含；缺关键证据不输出确定结论；持久化及用户文本不得导致注入或跨域写操作。

## Tasks
1. [ ] 归档文档，创建独立环境及启动入口；检验归档文件hash一致。
2. [ ] rules.py：先写tests/test_rules.py验证375/370、不可叠加、unknown、金额/时间边界，再实现evaluate_cart并执行全部规则测试。
3. [ ] retrieval.py与自建规则资料：先写tests/test_retrieval.py验证检索、证据版本映射、SDK生命周期与失败行为，再实现本地/LightRAG双适配，运行真实SDK集成测试。
4. [ ] app.py/service.py/storage.py：先写API测试验证诊断、追问、证据缺失、非法输入、历史与反馈，再实现编排和SQLite，所有返回遵守冻结契约。
5. [ ] static页面：实现诊断/知识/历史/评测四视图、方案比较、证据展开、状态与反馈，真实API验证流程与窄屏布局。
6. [ ] 固定评测集与CLI、README和配置：运行评测保留逐例结果；标明lexical和LightRAG测试的不同含义。
7. [ ] 汇总独立代码审查，修复实质缺陷，目标目录运行完整测试、SDK检查、服务及浏览器验收，交付运行地址。

执行方式：用户已明确要求直接开始落地；接口冻结后分派互不重叠的规则、检索、前端文件，主代理负责服务集成与最终验收。新建目录不需要现有仓库worktree。
