# 环境配置记录

> IPO-Risk-Agent 比赛专用开发环境

---

## 1. 环境概述

| 属性 | 值 |
|------|-----|
| 环境名称 | ipo311 |
| Python版本 | 3.11.15 |
| 环境路径 | /sessions/exciting-inspiring-gates/miniconda3/envs/ipo311 |
| 创建时间 | 2026-07-09 |
| 用途 | 港股IPO招股书解析与风险预警系统 |

---

## 2. 系统信息

### 2.1 操作系统

| 属性 | 值 |
|------|-----|
| 发行版 | Ubuntu 22.04.5 LTS |
| 内核 | 6.8.0-124-generic |
| 架构 | x86_64 |

### 2.2 Conda

| 属性 | 值 |
|------|-----|
| 版本 | conda 26.5.3 |
| 安装路径 | $HOME/miniconda3 |
| 环境路径 | $HOME/miniconda3/envs/ipo311 |

---

## 3. Python环境

### 3.1 核心组件

| 组件 | 版本 | 说明 |
|------|------|------|
| Python | 3.11.15 | 主解释器 |
| pip | 26.1.2 | 包管理器 |
| setuptools | 83.0.0 | 构建工具 |
| wheel | 0.47.0 | 包格式 |

### 3.2 环境激活

```bash
# 激活环境
conda activate ipo311

# 验证Python版本
python --version
# 输出: Python 3.11.15

# 验证pip
pip --version
# 输出: pip 26.1.2
```

---

## 4. GPU/CUDA信息

### 4.1 当前状态

| 属性 | 值 |
|------|-----|
| NVIDIA GPU | 未检测到 |
| CUDA版本 | N/A |
| cuDNN版本 | N/A |

### 4.2 说明

当前环境为CPU环境。如需GPU加速（如MinerU），需要：
- 部署到GPU服务器
- 或使用云端GPU实例（如AutoDL、Google Colab）

---

## 5. 依赖管理

### 5.1 包管理策略

- **Conda**: 用于Python版本管理和基础包
- **pip**: 用于PyPI包安装
- **镜像源**: 清华大学镜像（https://pypi.tuna.tsinghua.edu.cn/simple）

### 5.2 安装命令模板

```bash
# 激活环境
conda activate ipo311

# 使用清华镜像安装
pip install <package> -i https://pypi.tuna.tsinghua.edu.cn/simple

# 批量安装
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

---

## 6. 已安装包清单

### 6.1 基础包

| 包名 | 版本 | 用途 |
|------|------|------|
| pip | 26.1.2 | 包管理 |
| setuptools | 83.0.0 | 构建工具 |
| wheel | 0.47.0 | 包格式 |
| packaging | 26.0 | 包版本处理 |

### 6.2 待安装包（比赛相关）

| 包名 | 用途 | 优先级 |
|------|------|--------|
| pdfplumber | PDF文本提取 | P0 |
| camelot-py | PDF表格提取 | P0 |
| opencc-python-reimplemented | 繁简转换 | P0 |
| PyPDF2 | PDF处理 | P1 |
| PyMuPDF | PDF处理（备选） | P1 |
| pandas | 数据处理 | P0 |
| numpy | 数值计算 | P0 |
| sentence-transformers | Embedding | P1 |
| chromadb | 向量数据库 | P1 |
| fastapi | API服务 | P2 |

---

## 7. 环境验证

### 7.1 验证脚本

```bash
#!/bin/bash
# env_check.sh

source $HOME/miniconda3/bin/activate
conda activate ipo311

echo "=== 环境验证 ==="
echo "Python: $(python --version)"
echo "pip: $(pip --version | cut -d' ' -f2)"
echo "setuptools: $(pip show setuptools | grep Version | cut -d' ' -f2)"
echo "wheel: $(pip show wheel | grep Version | cut -d' ' -f2)"
echo "环境路径: $(conda info --envs | grep ipo311)"
echo "=== 验证完成 ==="
```

### 7.2 预期输出

```
=== 环境验证 ===
Python: Python 3.11.15
pip: 26.1.2
setuptools: 83.0.0
wheel: 0.47.0
环境路径: ipo311               *   /sessions/exciting-inspiring-gates/miniconda3/envs/ipo311
=== 验证完成 ===
```

---

## 8. 常见问题

### 8.1 conda命令找不到

```bash
source $HOME/miniconda3/bin/activate
```

### 8.2 环境激活失败

```bash
conda init bash
source ~/.bashrc
conda activate ipo311
```

### 8.3 pip安装超时

```bash
pip install <package> -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn
```

---

## 9. 下一步

1. 安装比赛相关依赖（pdfplumber、camelot等）
2. 配置项目目录结构
3. 开始Parser模块开发

---

## 10. 附录

### 10.1 环境导出

```bash
# 导出环境
conda env export > environment.yml

# 从yml恢复环境
conda env create -f environment.yml
```

### 10.2 相关文档

- Conda文档: https://docs.conda.io/
- Python 3.11文档: https://docs.python.org/3.11/
- pip文档: https://pip.pypa.io/
