# Bilibili Video Summary MCP Server

这是一个基于 [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) 的 B 站视频总结服务器。

> [!IMPORTANT]
> **Vibe Coding 产物**：这个项目完全是通过与 AI 对话（Vibe Coding）快速生成的，不是传统意义上手写的工程代码。它旨在快速解决“让 AI 助手直接读取 B 站视频内容”的需求。

## 功能特性

- **一键总结**：自动获取视频基本信息、统计数据（播放、点赞等）、弹幕分析。
- **官方 AI 总结**：支持调用 B 站官方生成的 AI 总结和提纲（需 SESSDATA）。
- **智能回退**：若官方 AI 总结不可用，将自动提取视频字幕/转录文本供 AI 助手阅读。
- **弹幕热词**：分析视频弹幕分布，提取高频词汇和精彩片段。
- **WBI 签名**：内置 B 站最新的 WBI 签名算法，确保接口调用稳定。

## 安装与配置

### 1. 环境准备
确保已安装 Python 3.10+，并安装依赖：
```bash
pip install aiohttp requests fastmcp
```

### 2. 配置 SESSDATA (可选)
部分功能（如官方 AI 总结）需要登录状态。你可以从浏览器 Cookie 中获取 `SESSDATA` 并设置为环境变量：
- **Windows (PowerShell)**: `$env:BILIBILI_SESSDATA = "你的SESSDATA"`
- **Linux/macOS**: `export BILIBILI_SESSDATA="你的SESSDATA"`

## 使用方式

### 在 Trae / Claude Desktop 中接入
在你的 MCP 配置文件（如 `mcp_config.json` 或 Trae 的设置）中添加以下内容：

```json
{
  "mcpServers": {
    "bilibili-summary": {
      "command": "python",
      "args": ["/绝对路径/to/bilibili_mcp.py"],
      "env": {
        "BILIBILI_SESSDATA": "你的SESSDATA(可选)"
      }
    }
  }
}
```

### 可用工具 (Tools)

- `get_video_summary`: 最常用的工具。输入 URL 或 BV 号，返回视频详情 + AI 总结/转录文本 + 弹幕分析。
- `get_video_ai_summary`: 专门获取 B 站官方生成的 AI 提纲。
- `get_video_transcript`: 获取纯文本字幕，适合让 AI 助手进行二次深度分析。
- `get_video_danmaku`: 获取视频原始弹幕列表。
- `get_video_info`: 获取视频播放量、UP 主等元数据。

## 免责声明
本工具仅供学习交流使用，请勿用于大规模爬虫或商业用途。请尊重 Bilibili 平台及内容创作者的相关权利。
