# MosDNS Log Reader
#### 此项目完全由 Claude 3.5 Sonnet 完成（包括README.md）
一个用于实时监控和分析 MosDNSv4 日志的 Web 应用。

## 功能特性

- 实时监控日志文件变化
- DNS 查询统计分析
- 缓存命中率统计
- 客户端 IP 地理位置显示
- 查询类型分布统计
- 支持域名黑名单过滤
- WebSocket 实时数据更新
- 响应式 Web 界面

## 安装说明

### 1. 环境要求
- Python 3.7+
- pip 包管理器
- MosDNS 日志等级为 debug

### 2. 安装步骤

1. 克隆仓库：
```bash
git clone https://github.com/JohnsonRan/mosdns-logreader
cd mosdns-logreader
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 配置黑名单（可选）：
编辑 `blacklist.json` 文件，添加需要过滤的域名或关键词。

### 3. 运行应用
```bash
python src/server.py
```

应用将在 http://127.0.0.1:8000 启动

## 配置说明

### 日志文件

默认监控项目目录下的 `mosdns.log` 文件。确保 MosDNS 日志等级为 debug。

### 黑名单配置

`blacklist.json` 支持两种过滤方式：
- `domains`: 完整域名匹配
- `patterns`: 关键词匹配

示例：
```json
{
    "domains": [
        "telemetry.example.com",
        "analytics.example.org"
    ],
    "patterns": [
        "telemetry",
        "analytics"
    ]
}
```

### 截图
![](src/static/screenshot.jpeg)