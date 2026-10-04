# 商策助手首版实施规格

用户已阅读电商设计报告并明确要求开始落地，沿用该设计。本次交付可运行软件，不再请求重复设计授权。

目标：本地中文电商运营诊断工作台，真实计算优惠资格与金额，展示可追溯证据、历史记录和反馈，并提供真实 LightRAG 集成与离线演示。首版单店模拟数据，明确不是生产多租户平台。

## 架构及边界
Python 3.12+ / FastAPI / SQLite / 原生 HTML CSS JS。无需前端编译，模块化单体。金额采用 Decimal。默认本地 lexical 检索演示，不冒充 LightRAG 或大模型生成。可选真实本地 LightRAG SDK，通过 aquery_data 获取材料；支持真实模型配置，但没有密钥也能使用全部规则诊断产品闭环。

文档归档到 docs/reports/，开发说明位于 docs/development/。产品代码留在根目录的 commerceops/。保留上游 LightRAG 不修改。

### 冻结模块契约
业务规则模块 commerceops/rules.py 暴露 evaluate_cart(cart: list[dict], is_new_customer: bool|None, at: str, policy: dict) -> dict。
cart 每项 {sku,name,price:str,quantity:int,collection:str,tags:list[str]|None}；默认 P1 250.00 户外非清仓，P2 150.00 户外清仓，quantity=1。允许自定义验证边界。时间为带时区 ISO8601，起点包含终点不包含。
policy {snapshot_id:'demo-v3', discount_rate:'0.90', minimum:'350.00', coupon_amount:'30.00', excluded_tag:'clearance', collection:'outdoor', stackable:False, starts_at:'2026-10-01T00:00:00+08:00', ends_at:'2026-11-01T00:00:00+08:00'}。
结果 {checks:[{rule_id,result:'pass'|'fail'|'unknown',reason_code,detail,evidence_ids:list[str]}],plans:[{id:'D1'|'D2'|'D1+D2',label,eligible:bool|None,total:str|None}],missing_fields:list[str],subtotal:str,recommended_plan:str|None}。固定 rule IDs: R1(活动范围与清仓排除)、R2(新客与原价门槛)、R3(叠加)、R4(有效时间)。result用于判断条件，不是系统成功失败。每个商品 R1 检查 detail明确SKU。缺失任何影响资格字段保持unknown不推荐未经确认方案。非法负价、非有限数字、非整数数量、无时区、空购物车拒绝。

知识检索模块 commerceops/retrieval.py 暴露 dataclass Evidence(id,title,content,source,version,score=0.0); load_evidence(snapshot_id='demo-v3')->list[Evidence]; LexicalRetriever(evidence).async search(query,mode='mix',limit=6)->list[Evidence]; backend='lexical-demo'。LightRAGRetriever通过相同search接口，并提供async initialize/close/ingest。文档id为R1-R4、R5退货、R6运费，source为自建规则路径，version='demo-v3'。全文带模拟声明，不假装平台现行政策。

### 产品 API 契约
GET /api/health -> {status,backend,version}; GET /api/catalog -> {shop:{id,name},cart:[...],policy:{...},presets:[{id,label,question,is_new_customer,at}]}。
POST /api/diagnoses body {question:str,is_new_customer:bool|null,at:ISO string,cart?:list}。默认cart使用catalog，服务端固定商家身份demo-shop不接受任意tenant。仅诊断优惠范围问题，其他问题unsupported。
返回 {id,status:'resolved'|'needs_info'|'insufficient_evidence'|'unsupported',answer,backend,knowledge_snapshot,business_snapshot,created_at,checks,plans,missing_fields,evidence:[{id,title,content,source,version,score}],trace:[{step,detail,duration_ms}],subtotal,recommended_plan,warnings}。
POST /api/diagnoses/{id}/continue body {is_new_customer:bool} 继承原请求字段生成新诊断并保留parent_id。
GET /api/diagnoses -> {items:[{id,status,question,created_at,answer}]}; GET /api/diagnoses/{id} ->完整记录。
POST /api/diagnoses/{id}/feedback {rating:'helpful'|'incorrect',comment:str} ->{saved:true}。
GET /api/knowledge -> {items:[Evidence...]}; GET /api/evaluation ->本次实际结果或明确未运行。
安全：只绑定127.0.0.1，限制Host与跨域写请求；无写商家操作，输入与HTML文本转义，SQL参数化。SQLite事务保存诊断与反馈。服务异常不显示密钥。真实LightRAG失败不得静默回退后仍标记LightRAG。

### 验收
普通案例D1=375.00 D2=370.00禁止叠加，推荐D2；缺新客资格追问再继续；清仓例外、350边界、活动失效、证据缺失拒断、无关问题、非法输入、反馈持久化。真实 SDK 至少验证自定义KG导入与aquery_data返回/证据映射（可用明确标记的确定性测试向量，不算模型质量评测）。API和UI真实联调；文档展示实际通过数与限制。密钥模式若缺凭据明确未验证，提供配置与操作步骤。
