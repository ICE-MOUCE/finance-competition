# 数据模型 Review 变更日志

> v1.2 Review修正记录

---

## 变更概览

| 修改项 | 修改前 | 修改后 | 原因 |
|--------|--------|--------|------|
| risk_tags注释 | 无说明 | 增加注释说明由Risk Agent生成 | 明确职责边界 |
| Document.evidence_store_path | 无 | 新增字段 | 记录Evidence输出目录 |
| BaseEvidence基类 | 无 | 新增抽象基类 | 统一字段和方法 |
| section_path默认值 | 无默认值 | default_factory=list | 简化构造 |
| bbox类型 | Tuple | Optional[Tuple] | 支持缺失场景 |

---

## 详细变更

### 1. risk_tags 字段注释

**修改位置**: TextEvidence、TableEvidence、ImageEvidence

**修改内容**:
```python
# === 风险标签 ===
# NOTE: Evidence Builder不生成risk_tags
# risk_tags由后续Risk Agent阶段生成
risk_tags: List[str] = field(default_factory=list)
```

**原因**: 明确职责边界，Evidence Builder只负责数据提取，Risk Agent负责风险判断。

---

### 2. Document.evidence_store_path

**修改位置**: Document数据类

**修改内容**:
```python
@dataclass
class Document:
    ...
    evidence_store_path: str = ""  # Evidence输出目录
    ...
```

**原因**: 记录Evidence输出目录，便于后续检索和管理。

**影响**: builder.py中自动填充该字段。

---

### 3. BaseEvidence 抽象基类

**修改位置**: 新增BaseEvidence类

**修改内容**:
```python
class BaseEvidence(ABC):
    """Evidence抽象基类"""

    @property
    @abstractmethod
    def block_type(self) -> str:
        pass

    @abstractmethod
    def to_citation(self) -> str:
        pass

    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        pass
```

**原因**: 统一TextEvidence、TableEvidence、ImageEvidence的接口。

**影响**: 所有Evidence类型继承BaseEvidence，可通过isinstance检查。

---

### 4. section_path 默认值

**修改位置**: TextEvidence、TableEvidence、ImageEvidence

**修改内容**:
```python
# 修改前
section_path: List[str]

# 修改后
section_path: List[str] = field(default_factory=list)
```

**原因**: 简化构造，部分Evidence可能没有section信息。

---

### 5. bbox Optional支持

**修改位置**: TextEvidence、TableEvidence、ImageEvidence

**修改内容**:
```python
# 修改前
bbox: Tuple[float, float, float, float]

# 修改后
bbox: Optional[Tuple[float, float, float, float]] = None
```

**原因**: 部分场景bbox可能缺失（如OCR识别失败）。

**影响**: to_dict()中处理None情况：
```python
"bbox": list(self.bbox) if self.bbox else None,
```

---

## 验证结果

| 样本 | 文本 | 表格 | 图片 | 总计 | BaseEvidence | store_path |
|------|------|------|------|------|--------------|------------|
| S1_快手 | 63 | 1 | 14 | 78 | ✅ | ✅ |
| S2_KEEP | 40 | 1 | 8 | 49 | ✅ | ✅ |
| S3_京东工业 | 42 | 2 | 2 | 46 | ✅ | ✅ |

**验证结论**: 全部通过 ✅

---

## 未修改项

以下内容按要求保持不变：

- ✅ Evidence ID规则（txt/tbl/img前缀）
- ✅ 已有目录结构
- ✅ Evidence Builder逻辑
- ✅ Parser逻辑
- ✅ 不增加Chunk/Embedding/Retriever代码
