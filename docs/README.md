# 商策助手 CommerceOps

项目已落地为可运行的本地电商运营诊断工作台，版本 0.1.0。所有说明和旧报告集中在本目录，应用代码位于上一级 `commerceops/`。

## 立即使用

在 `RAG_project` 根目录运行：

```sh
sh run.sh
```

打开 <http://127.0.0.1:8877>。当前机器已安装项目独立环境；默认无需 API Key。停止时在启动终端按 Ctrl+C。

新环境完整安装（Python 3.12+，相邻目录保留已检视的 LightRAG）：

```sh
sh scripts/setup.sh --with-lightrag
sh scripts/verify.sh
sh run.sh
```

只体验无需 SDK 的本地界面，可执行 `sh scripts/setup.sh`；**完整验证与 SDK 检查需要 `--with-lightrag`**。LightRAG 源码基线为 `453dce83d6d0354a06e46c8d4029a0895c4e054b`，版本 1.5.8。

## 已实现的功能

- 中文诊断工作台、规则知识、历史记录、评测结果四个页面。
- 基于商品范围、清仓标签、新客资格、原始金额门槛、优惠叠加和带时区活动时间的确定性诊断。
- 金额使用 Decimal；示例 D1=375.00、D2=370.00，不允许非法叠加成345.00。
- 新客资格未知时追问，补充后沿用原购物车和订单时间继续；API同样保留未知商品标签、集合的状态。
- 证据不足或检索失败时暂停结论；每条检查绑定经批准的自建条款。
- SQLite持久化诊断、原请求快照和反馈；历史记录可还原当时的输入。
- 真实 LightRAG SDK 适配：文档入库、索引完整性检查、mix 检索、原文证据映射、独占写入锁、语料和模型配置指纹。
- 33条模拟业务回归、自动化测试和真实SDK冒烟检查。

## 两种运行模式

**默认 `lexical-demo`**：中文双字词/英文词项检索自建规则，规则执行器生成忠实的诊断说明。它没有调用 LLM，也不是图向量检索；页面明确显示“本地关键词检索 · 演示”。适合先学习、演示和验证业务闭环。

**可选 `lightrag`**：真实 SDK 调用聊天模型提取实体关系、调用 Embedding 模型建索引，并通过 `aquery_data` 获取材料。最终业务结论仍由可测试的规则执行器生成，避免让模型改写金额和资格。模型服务配置如下。

```sh
cp .env.example .env
# 在本机编辑 .env，填写以下六项；不要把密钥提交到Git。
```

```dotenv
COMMERCEOPS_RETRIEVAL=lightrag
COMMERCEOPS_MODEL_BASE_URL=https://你的兼容服务地址/v1
COMMERCEOPS_API_KEY=你的本地密钥
COMMERCEOPS_LLM_MODEL=聊天模型名称
COMMERCEOPS_EMBEDDING_MODEL=向量模型名称
COMMERCEOPS_EMBEDDING_DIM=真实向量维度
```

首先停止运行中的服务，然后执行：

```sh
.venv/bin/python -m commerceops index
sh run.sh
```

当前适配器使用同一兼容服务地址提供聊天与 Embedding 接口。如果只有聊天接口，需要补充支持 Embedding 的服务或扩展双地址配置。调用真实模型会产生服务提供商费用；此交付未使用付费凭据。

切换语料或模型后，设置新的 `COMMERCEOPS_DATA_DIR` 重新建立索引；旧目录的指纹不匹配时会拒绝使用。首版一次仅一个进程持有同一图目录。不要同时运行索引、评测与在线服务并指向同一个图目录。

`index --curated-graph` 可导入人工编写的规则图，仍使用配置的 Embedding 服务；它不代表模型完成了实体抽取。`scripts/check_lightrag.py` 则使用**测试专用确定性向量与关键词函数**，在临时目录检查真实 SDK 的存储、图检索和引用映射，全程不调用模型服务。

## 演示顺序

1. 选择“优惠为什么不能叠加？”示例（显式选择新客）：确认清仓排除，比较375元和370元，查看R1–R4全文。
2. 点击“新客信息尚未确认”，提交后确认身份，观察推荐从未定变为D2。
3. 点击“活动到期后会怎样”，看有效期终点不包含的判断。
4. 为一次诊断提交反馈，在“诊断记录”回看原问题和业务条件。
5. 在“评测结果”查看本机实际33条回归结果及范围说明。

## 目录与维护

```text
RAG_project/
  commerceops/       API、业务编排、规则、检索、持久化和网页
    data/           自建条款与固定评测数据
    static/         无构建依赖的中文界面
  tests/            行为与回归测试
  scripts/          安装、验证、真实SDK检查
  docs/
    README.md       本文
    reports/        原两份报告及全部附件，作为落地前设计基线
    development/    规格、计划、实现记录、验证记录
  var/              运行后生成的SQLite、评测和可选图索引，不应提交
  .venv/            独立环境，不应提交
  .env.example      模型配置示例
  run.sh            启动入口
```

## 如何继续开发

阅读顺序：`catalog.py` → `rules.py` → `retrieval.py` → `service.py` → `app.py` → `static/app.js`。

接口文档：<http://127.0.0.1:8877/docs>。主要接口：`POST /api/diagnoses`、`POST /api/diagnoses/{id}/continue`、`GET /api/diagnoses`、`GET /api/knowledge`、`POST /api/diagnoses/{id}/feedback`、`GET /api/evaluation`。

添加场景时同时更新规范规则、知识条款和回归样例。正式改变语料需要发布新快照并重新索引；不要仅改一段说明却沿用旧索引或旧缓存。

## 当前边界

这是单店、本机运行的首版：商品和规则是自建模拟数据，默认购物车只读；自定义购物车可通过API提交。没有接入真实平台订单，没有多租户登录、任意文档上传、通用聊天、自动改价或线上营收指标。退款/运费规则只说明不在诊断范围，不会虚构承诺。

本地回归通过率不能当作大模型问答准确率。实际付费/本地模型端点尚待用户配置后验证，尚未进行真实向量模型下的 naive/mix 对照实验。用于简历时，应把本次已实现的模块和这些待完成工作分开。

资料：[原始项目报告入口](reports/00_阅读指南.html) · [实施规格](development/spec.md) · [实现与验证记录](development/implementation-status.md)

## 复评修复更新

已修复身份冲突、超范围问题误标成功、活动失效后的无效追问。页面默认身份改为未知；33条业务回归及82项测试、51项子测试通过。详见[本轮修复记录](development/reassessment-fixes-2026-10-03.md)。
