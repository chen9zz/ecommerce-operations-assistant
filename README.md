# Ecommerce Operations Assistant · 商策 CommerceOps

基于规则证据检索与确定性优惠计算的电商运营助手，提供中文诊断工作台、规则知识、诊断记录和评测结果。当前使用自建模拟店铺与规则，默认演示模式不需要模型密钥。

## 快速运行

需要 Python 3.12+。在本仓库根目录执行：

```sh
sh scripts/setup.sh
sh run.sh
```

打开 http://127.0.0.1:8877 。默认模式为本地关键词检索与规则计算；运行数据写入 `var/`，不会提交到 Git。

## 完整 SDK 验证与可选 LightRAG 模式

安装脚本的 `--with-lightrag` 选项使用相邻的 `../LightRAG` 目录。首次获取时，在本仓库根目录运行：

```sh
git clone https://github.com/HKUDS/LightRAG.git ../LightRAG
git -C ../LightRAG checkout 453dce83d6d0354a06e46c8d4029a0895c4e054b
sh scripts/setup.sh --with-lightrag
sh scripts/verify.sh
```

若相邻目录已经存在，请复用并核对版本，不要覆盖已有修改。LightRAG 是外部依赖，未将其源码复制进本仓库。

真实模型模式需要按 `.env.example` 配置聊天与 Embedding 服务，再建立索引。`.env` 与真实密钥仅保留在本地。

## 项目内容

- `commerceops/`：API、业务规则、检索适配、持久化、网页和模拟数据。
- `tests/`：自动化与回归测试。
- `scripts/`：环境安装、验证与 SDK 检查。
- `docs/`：使用文档、设计资料、实现记录及完整报告附件。

详见 [完整使用文档](docs/README.md)。当前功能是限定活动范围的诊断助手，不代表通用电商问答、真实商家收益或在线模型质量评测。
