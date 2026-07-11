# 设计变更日志

> Evidence Layer 设计版本记录

---

## v1.1（当前版本）

**日期**：2026-07-10
**状态**：冻结

### 变更内容

#### 1. 修正Evidence ID前缀（消除冲突）

**问题**：v1.0中text和table都使用`t`作为前缀，导致ID冲突。

**修改**：

| 类型 | v1.0 | v1.1 |
|------|------|------|
| text | `t` | `txt` |
| table | `t` | `tbl` |
| image | `i` | `img` |

**示例**：
- v1.0: `ev_2021_01024_p45_t001`（text和table无法区分）
- v1.1: `ev_2021_01024_p45_txt001`（text）/ `ev_2021_01024_p3_tbl001`（table）

**影响**：所有Evidence ID格式更新，Agent引用格式同步更新。

---

#### 2. 升级section为层级结构

**问题**：v1.0中`section: str`无法表达多级章节关系。

**修改**：
- v1.0: `section: str`（如 `"风险因素 > 业务风险"`）
- v1.1: `section_path: List[str]`（如 `["风险因素", "业务风险", "竞争风险"]`）

**原因**：
1. 层级结构更便于按层级过滤（如只查"风险因素"下的所有Evidence）
2. Agent可以精确引用到具体层级
3. Risk Report可以按层级组织展示

**示例**：
```python
# v1.0
evidence.section = "风险因素 > 业务风险"
# 问题：无法直接按"风险因素"过滤

# v1.1
evidence.section_path = ["风险因素", "业务风险"]
# 可以按任意层级过滤
```

---

#### 3. risk_tags职责调整

**问题**：v1.0中Evidence Builder生成risk_tags，但这需要语义理解能力。

**修改**：
- v1.0：Evidence Builder通过关键词匹配生成risk_tags
- v1.1：Evidence Builder不生成risk_tags，由Risk Agent后续填充

**原因**：
1. risk_tags需要语义理解和风险判断，不是简单的关键词匹配
2. Risk Agent有专门的风险分析能力
3. 分离关注点：Evidence Builder负责数据提取，Risk Agent负责风险判断
4. 避免Evidence Builder阶段引入误判

**影响**：
- `risk_tags`字段保留在Evidence基类中
- Evidence Builder构建时`risk_tags=[]`
- Risk Agent分析后填充`risk_tags`

---

#### 4. 明确Evidence Store MVP范围

**问题**：v1.0中Evidence Store设计过于复杂，包含SQLite、Vector DB等。

**修改**：

| 组件 | v1.0 | v1.1 MVP |
|------|------|----------|
| document.json | ✅ | ✅ |
| evidences.json | ✅ | ✅ |
| images/ | ✅ | ✅ |
| tables/ | ✅ | ❌ 后续 |
| index/ | ✅ | ❌ 后续 |
| metadata.db | ✅ | ❌ 后续 |
| Vector DB | ✅ | ❌ 后续 |

**原因**：
1. MVP阶段只需要验证Evidence数据模型是否正确
2. JSON文件存储足以满足MVP需求
3. SQLite、Vector DB属于后续Stage（索引和检索）

---

#### 5. 更新架构流程图

**问题**：v1.0中流程图暗示Markdown是核心数据输入。

**修改**：
- v1.0：`MinerU → Markdown → content_list.json → Evidence Builder`
- v1.1：`MinerU → content_list.json → Evidence Builder`（Markdown仅用于表格HTML提取和调试）

**原因**：
1. content_list.json是MinerU的结构化输出，包含所有必要信息
2. Markdown是人类可读格式，不是程序化输入
3. 唯一使用Markdown的地方是提取表格HTML（因为content_list.json中table的text为空）

**影响**：
- Evidence Builder的核心输入是content_list.json
- Markdown仅用于：提取表格HTML、调试、人工检查
- Document对象中`markdown_path`标记为"仅用于调试"

---

## v1.0（初始版本）

**日期**：2026-07-09
**状态**：已废弃（被v1.1替代）

### 设计内容

- 定义Document、Evidence、TextEvidence、TableEvidence、ImageEvidence数据模型
- 定义Evidence ID格式
- 定义Evidence Builder数据流
- 定义Evidence Store接口
- 定义Agent引用格式

### 被v1.1修正的问题

1. Evidence ID前缀冲突（text/table都用`t`）
2. section使用单一string，无法表达层级
3. risk_tags由Evidence Builder生成（职责不清）
4. Evidence Store范围过大（包含SQLite、Vector DB）
5. 架构流程图暗示Markdown是核心输入

---

## 版本对比总结

| 维度 | v1.0 | v1.1 |
|------|------|------|
| Evidence ID前缀 | text=`t`, table=`t`, image=`i` | text=`txt`, table=`tbl`, image=`img` |
| section | `str` | `List[str]` |
| risk_tags | Evidence Builder生成 | Risk Agent生成 |
| Evidence Store | 完整（SQLite+VectorDB） | MVP（JSON文件） |
| 核心输入 | Markdown + content_list | content_list.json |
| Markdown角色 | 核心输入 | 仅用于调试 |
