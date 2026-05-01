import asyncio
import json
import re
import hashlib
import time
import urllib.parse
import os
from typing import Optional, List, Dict
from functools import reduce

import aiohttp
import requests
from collections import Counter
from fastmcp import FastMCP

mcp = FastMCP("B站视频总结 MCP")

# 从环境变量获取默认 SESSDATA
DEFAULT_SESSDATA = os.environ.get("BILIBILI_SESSDATA", "")

# WBI 签名相关常量
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52
]

def get_mixin_key(orig: str) -> str:
    """对抽样得到的暗号进行重排"""
    return reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, "")[:32]

def enc_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    """为请求参数进行 WBI 签名"""
    mixin_key = get_mixin_key(img_key + sub_key)
    curr_time = int(time.time())
    params['wts'] = curr_time
    # 按照 key 重排参数
    params = dict(sorted(params.items()))
    # 过滤 value 中的非法字符
    params = {
        k: ''.join(filter(lambda chr: chr not in "!'()*", str(v)))
        for k, v in params.items()
    }
    query = urllib.parse.urlencode(params)
    w_rid = hashlib.md5((query + mixin_key).encode()).hexdigest()
    params['w_rid'] = w_rid
    return params

async def get_wbi_keys() -> tuple[str, str]:
    """获取最新的 img_key 和 sub_key"""
    url = "https://api.bilibili.com/x/web-interface/nav"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com/"
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            res = await response.json()
    
    wbi_img = res.get("data", {}).get("wbi_img", {})
    img_url = wbi_img.get("img_url")
    sub_url = wbi_img.get("sub_url")
    
    img_key = img_url.split("/")[-1].split(".")[0]
    sub_key = sub_url.split("/")[-1].split(".")[0]
    return img_key, sub_key


def extract_bvid(url_or_bvid: str) -> Optional[str]:
    """从URL或BV号中提取BV号"""
    if url_or_bvid.startswith("BV"):
        return url_or_bvid
    
    bv_pattern = r'BV[a-zA-Z0-9]{10}'
    match = re.search(bv_pattern, url_or_bvid)
    if match:
        return match.group()
    
    short_pattern = r'b23\.tv/([a-zA-Z0-9]+)'
    match = re.search(short_pattern, url_or_bvid)
    if match:
        short_url = f"https://b23.tv/{match.group(1)}"
        try:
            response = requests.head(short_url, allow_redirects=False)
            if 'Location' in response.headers:
                real_url = response.headers['Location']
                bv_match = re.search(bv_pattern, real_url)
                if bv_match:
                    return bv_match.group()
        except Exception:
            pass
    
    return None


async def fetch_video_info(bvid: str) -> dict:
    """获取视频基本信息"""
    url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://www.bilibili.com/video/{bvid}"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            data = await response.json()
            
    if data.get("code") != 0:
        raise Exception(f"API错误: {data.get('message', '未知错误')}")
    
    return data.get("data", {})


async def fetch_subtitle_list(bvid: str, cid: int) -> List[dict]:
    """获取视频字幕列表"""
    url = f"https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://www.bilibili.com/video/{bvid}"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            data = await response.json()
    
    if data.get("code") != 0:
        return []
    
    subtitle_data = data.get("data", {}).get("subtitle", {})
    subtitles = subtitle_data.get("subtitles", [])
    
    result = []
    for sub in subtitles:
        result.append({
            "id": sub.get("id"),
            "id_str": sub.get("id_str"),
            "lan": sub.get("lan"),
            "lan_doc": sub.get("lan_doc"),
            "subtitle_url": sub.get("subtitle_url"),
            "ai_type": sub.get("ai_type"),
            "ai_status": sub.get("ai_status")
        })
    
    return result


async def fetch_subtitle_content(subtitle_url: str) -> List[dict]:
    """获取字幕文件内容"""
    if not subtitle_url:
        return []
    
    full_url = "https:" + subtitle_url if subtitle_url.startswith("//") else subtitle_url
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(full_url, headers=headers) as response:
            data = await response.json()
    
    body = data.get("body", [])
    return body


async def fetch_danmaku(cid: int, bvid: str) -> list:
    """获取视频弹幕"""
    url = f"https://comment.bilibili.com/{cid}.xml"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://www.bilibili.com/video/{bvid}"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            text = await response.text()
    
    danmaku_list = []
    pattern = r'<d p="([^"]+)">([^<]+)</d>'
    for match in re.finditer(pattern, text):
        p_attrs = match.group(1).split(',')
        content = match.group(2)
        danmaku_list.append({
            "time": float(p_attrs[0]),
            "mode": int(p_attrs[1]),
            "fontsize": int(p_attrs[2]),
            "color": int(p_attrs[3]),
            "midHash": p_attrs[5],
            "content": content
        })
    
    return danmaku_list


async def fetch_ai_conclusion(bvid: str, cid: int, sessdata: str = "") -> Optional[dict]:
    """获取视频 AI 总结内容"""
    img_key, sub_key = await get_wbi_keys()
    params = {
        "bvid": bvid,
        "cid": cid,
    }
    signed_params = enc_wbi(params, img_key, sub_key)
    
    url = "https://api.bilibili.com/x/web-interface/view/conclusion/get"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://www.bilibili.com/video/{bvid}"
    }
    
    # 如果提供了 sessdata，则添加到 cookie 中
    cookies = {}
    if sessdata:
        cookies["SESSDATA"] = sessdata
    elif DEFAULT_SESSDATA:
        cookies["SESSDATA"] = DEFAULT_SESSDATA
    
    async with aiohttp.ClientSession(cookies=cookies) as session:
        async with session.get(url, params=signed_params, headers=headers) as response:
            data = await response.json()
            
    if data.get("code") == 0 and data.get("data"):
        return data.get("data")
    
    # 如果是登录错误，在返回中体现
    if data.get("code") == -101:
        return {"error": "Authentication required (SESSDATA cookie needed)", "code": -101}
        
    return None


def summarize_danmaku(danmaku_list: list) -> dict:
    """对弹幕进行简单的统计分析"""
    if not danmaku_list:
        return {"total": 0, "top_keywords": [], "highlights": []}
    
    contents = [d["content"] for d in danmaku_list]
    total = len(contents)
    
    word_count = Counter()
    for content in contents:
        if len(content) > 1:
            word_count[content] += 1
    
    top_keywords = word_count.most_common(20)
    
    highlights = [d for d in danmaku_list if len(d["content"]) >= 10][:10]
    
    return {
        "total": total,
        "top_keywords": [{"text": k, "count": v} for k, v in top_keywords],
        "highlights": [{"time": h["time"], "content": h["content"]} for h in highlights]
    }


def format_subtitle_text(subtitle_body: List[dict]) -> str:
    """将字幕内容格式化为纯文本"""
    lines = []
    for sub in subtitle_body:
        start_time = sub.get("from", 0)
        content = sub.get("content", "")
        minutes = int(start_time // 60)
        seconds = int(start_time % 60)
        lines.append(f"[{minutes:02d}:{seconds:02d}] {content}")
    return "\n".join(lines)


@mcp.tool
async def get_video_ai_summary(url_or_bvid: str, sessdata: str = "") -> str:
    """获取B站官方AI生成的视频内容总结。
    
    参数:
        url_or_bvid: B站视频的URL链接或BV号
        sessdata: B站登录后的 SESSDATA Cookie 值。如果官方AI总结提示需要登录，请提供此值。
    
    返回:
        AI生成的总结和提纲
    """
    bvid = extract_bvid(url_or_bvid)
    if not bvid:
        return "错误: 无法从输入中提取有效的B站视频BV号。"
    
    try:
        video_info = await fetch_video_info(bvid)
        cid = video_info["pages"][0]["cid"]
        
        ai_data = await fetch_ai_conclusion(bvid, cid, sessdata)
        
        if ai_data and ai_data.get("code") == -101:
            return "该视频的官方AI总结需要登录后才能查看。请提供 SESSDATA Cookie，或使用 get_video_summary 获取转录文本由 AI 助手总结。"
        
        if not ai_data or ai_data.get("code") != 0:
            return "该视频暂无官方AI总结。可能是因为视频太短、没有语音、内容敏感或AI尚未处理完成。"
        
        model_result = ai_data.get("model_result", {})
        summary = model_result.get("summary", "无摘要")
        outlines = model_result.get("outline", [])
        
        result = f"# AI 视频总结: {video_info.get('title')}\n\n"
        result += f"## 核心摘要\n{summary}\n\n"
        
        if outlines:
            result += "## 内容大纲\n"
            for outline in outlines:
                title = outline.get("title", "")
                timestamp = outline.get("timestamp", 0)
                time_str = f"{int(timestamp//60)}:{int(timestamp%60):02d}"
                result += f"### [{time_str}] {title}\n"
                
                for part in outline.get("part_outline", []):
                    p_timestamp = part.get("timestamp", 0)
                    p_time_str = f"{int(p_timestamp//60)}:{int(p_timestamp%60):02d}"
                    result += f"- [{p_time_str}] {part.get('content')}\n"
                result += "\n"
        
        return result
        
    except Exception as e:
        return f"获取AI总结失败: {str(e)}"


@mcp.tool
async def get_video_summary(url_or_bvid: str, sessdata: str = "") -> str:
    """获取B站视频的全面总结信息，包括视频基本信息、统计数据、官方AI总结（如有）或完整字幕转录文本。
    
    参数:
        url_or_bvid: B站视频的URL链接或BV号
        sessdata: 可选的 B站 SESSDATA Cookie，用于获取官方AI总结
    
    返回:
        视频的详细总结信息。如果官方AI总结不可用，将包含完整字幕文本。
    """
    bvid = extract_bvid(url_or_bvid)
    if not bvid:
        return "错误: 无法从输入中提取有效的B站视频BV号，请检查链接或BV号是否正确。"
    
    try:
        video_info = await fetch_video_info(bvid)
        
        cid = video_info["pages"][0]["cid"]
        danmaku_list = await fetch_danmaku(cid, bvid)
        danmaku_summary = summarize_danmaku(danmaku_list)
        
        subtitle_list = await fetch_subtitle_list(bvid, cid)
        
        # 尝试获取官方 AI 总结
        ai_data = await fetch_ai_conclusion(bvid, cid, sessdata)
        ai_summary_text = ""
        has_official_ai = False
        
        if ai_data and ai_data.get("code") == 0:
            model_result = ai_data.get("model_result", {})
            summary = model_result.get("summary", "")
            if summary:
                ai_summary_text = f"\n## 官方 AI 内容总结\n{summary}\n"
                has_official_ai = True
        elif ai_data and ai_data.get("code") == -101:
            ai_summary_text = "\n> [!TIP] 官方 AI 总结需要登录 SESSDATA 才能获取。\n"

        # 如果没有官方 AI 总结，尝试提取完整字幕文本作为替代
        transcript_text = ""
        if not has_official_ai:
            if subtitle_list:
                # 获取第一条字幕的内容
                sub_body = await fetch_subtitle_content(subtitle_list[0].get("subtitle_url"))
                if sub_body:
                    full_text = " ".join([s.get("content", "") for s in sub_body])
                    transcript_text = f"\n## 视频转录文本 (由 AI 助手进行内容判断)\n{full_text}\n"
            else:
                transcript_text = "\n## 内容提示\n该视频无可用字幕，建议结合简介和弹幕分析判断内容。\n"
        
        stat = video_info.get("stat", {})
        owner = video_info.get("owner", {})
        
        duration = video_info.get("duration", 0)
        minutes = duration // 60
        seconds = duration % 60
        
        result = f"""# {video_info.get('title', '未知标题')}

## 基本信息
- **BV号**: {bvid}
- **视频时长**: {minutes}分{seconds}秒
- **分区**: {video_info.get('tname', '未知')}
- **发布时间**: {video_info.get('pubdate', 0)}
- **简介**: {video_info.get('desc', '无')[:500]}{'...' if len(video_info.get('desc', '')) > 500 else ''}

## UP主
- **名称**: {owner.get('name', '未知')}
- **UID**: {owner.get('uid', '未知')}

## 统计数据
- **播放量**: {stat.get('view', 0):,} | **点赞**: {stat.get('like', 0):,} | **投币**: {stat.get('coin', 0):,} | **收藏**: {stat.get('favorite', 0):,}
{ai_summary_text}{transcript_text}
## 弹幕分析 (共 {danmaku_summary['total']:,} 条)
- **高频词**: {', '.join([f'"{k["text"]}"({k["count"]}次)' for k in danmaku_summary['top_keywords'][:10]]) if danmaku_summary['top_keywords'] else '无'}
"""
        
        if danmaku_summary['highlights']:
            result += "\n## 精彩弹幕片段\n"
            for h in danmaku_summary['highlights'][:5]:
                time_str = f"{int(h['time']//60)}:{int(h['time']%60):02d}"
                result += f"- [{time_str}] {h['content']}\n"
        
        return result
        
    except Exception as e:
        return f"获取视频信息失败: {str(e)}"


@mcp.tool
async def get_video_info(url_or_bvid: str, sessdata: str = "") -> str:
    """获取B站视频的基本信息。
    
    参数:
        url_or_bvid: B站视频的URL链接或BV号
    
    返回:
        视频的基本信息JSON
    """
    bvid = extract_bvid(url_or_bvid)
    if not bvid:
        return '{"error": "无法提取BV号"}'
    
    try:
        video_info = await fetch_video_info(bvid)
        
        stat = video_info.get("stat", {})
        owner = video_info.get("owner", {})
        
        result = {
            "bvid": bvid,
            "title": video_info.get("title"),
            "description": video_info.get("desc"),
            "duration": video_info.get("duration"),
            "publish_time": video_info.get("pubdate"),
            "category": video_info.get("tname"),
            "owner": {
                "name": owner.get("name"),
                "uid": owner.get("uid")
            },
            "stats": {
                "views": stat.get("view"),
                "danmaku": stat.get("danmaku"),
                "comments": stat.get("reply"),
                "likes": stat.get("like"),
                "coins": stat.get("coin"),
                "favorites": stat.get("favorite"),
                "shares": stat.get("share")
            }
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool
async def get_video_subtitles(url_or_bvid: str) -> str:
    """获取B站视频的字幕列表。
    
    参数:
        url_or_bvid: B站视频的URL链接或BV号
    
    返回:
        可用字幕列表JSON
    """
    bvid = extract_bvid(url_or_bvid)
    if not bvid:
        return json.dumps({"error": "无法提取BV号"}, ensure_ascii=False)
    
    try:
        video_info = await fetch_video_info(bvid)
        cid = video_info["pages"][0]["cid"]
        
        subtitle_list = await fetch_subtitle_list(bvid, cid)
        
        result = {
            "bvid": bvid,
            "title": video_info.get("title"),
            "subtitle_count": len(subtitle_list),
            "subtitles": subtitle_list
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool
async def get_video_subtitle_text(url_or_bvid: str, lan: str = "zh-CN") -> str:
    """获取B站视频的字幕文本内容。
    
    参数:
        url_or_bvid: B站视频的URL链接或BV号
        lan: 字幕语言代码，默认 "zh-CN"（中文），可选 "en"（英文）等
    
    返回:
        带时间戳的字幕文本
    """
    bvid = extract_bvid(url_or_bvid)
    if not bvid:
        return "错误: 无法提取BV号"
    
    try:
        video_info = await fetch_video_info(bvid)
        cid = video_info["pages"][0]["cid"]
        
        subtitle_list = await fetch_subtitle_list(bvid, cid)
        
        if not subtitle_list:
            return f"视频 [{video_info.get('title')}] 没有可用字幕"
        
        target_sub = None
        for sub in subtitle_list:
            if sub.get("lan") == lan:
                target_sub = sub
                break
        
        if not target_sub and subtitle_list:
            target_sub = subtitle_list[0]
        
        if not target_sub:
            return "未找到指定语言字幕"
        
        subtitle_body = await fetch_subtitle_content(target_sub.get("subtitle_url"))
        
        if not subtitle_body:
            return "字幕内容为空"
        
        text = format_subtitle_text(subtitle_body)
        
        header = f"# {video_info.get('title')}\n"
        header += f"字幕: {target_sub.get('lan_doc', lan)}\n"
        header += f"共 {len(subtitle_body)} 条\n"
        header += "-" * 40 + "\n"
        
        return header + text
        
    except Exception as e:
        return f"获取字幕失败: {str(e)}"


@mcp.tool
async def get_video_transcript(url_or_bvid: str, lan: str = "zh-CN") -> str:
    """获取视频的完整字幕文本（不带时间戳），适合用于AI总结。
    
    参数:
        url_or_bvid: B站视频的URL链接或BV号
        lan: 字幕语言代码，默认 "zh-CN"
    
    返回:
        完整的字幕文本内容
    """
    bvid = extract_bvid(url_or_bvid)
    if not bvid:
        return "错误: 无法提取BV号"
    
    try:
        video_info = await fetch_video_info(bvid)
        cid = video_info["pages"][0]["cid"]
        
        subtitle_list = await fetch_subtitle_list(bvid, cid)
        
        if not subtitle_list:
            return f"视频 [{video_info.get('title')}] 没有可用字幕"
        
        target_sub = None
        for sub in subtitle_list:
            if sub.get("lan") == lan:
                target_sub = sub
                break
        
        if not target_sub and subtitle_list:
            target_sub = subtitle_list[0]
        
        subtitle_body = await fetch_subtitle_content(target_sub.get("subtitle_url"))
        
        if not subtitle_body:
            return "字幕内容为空"
        
        # 提取纯文本
        text_lines = [sub.get("content", "") for sub in subtitle_body]
        return "\n".join(text_lines)
        
    except Exception as e:
        return f"获取字幕失败: {str(e)}"


@mcp.tool
async def get_video_danmaku(url_or_bvid: str, max_count: int = 100) -> str:
    """获取B站视频的弹幕列表。
    
    参数:
        url_or_bvid: B站视频的URL链接或BV号
        max_count: 最大返回弹幕数量，默认100条
    
    返回:
        弹幕列表
    """
    bvid = extract_bvid(url_or_bvid)
    if not bvid:
        return '{"error": "无法提取BV号"}'
    
    try:
        video_info = await fetch_video_info(bvid)
        cid = video_info["pages"][0]["cid"]
        
        danmaku_list = await fetch_danmaku(cid, bvid)
        
        danmaku_list = danmaku_list[:max_count]
        
        result = {
            "bvid": bvid,
            "total": len(danmaku_list),
            "danmaku": [
                {
                    "time": d["time"],
                    "content": d["content"],
                    "color": d["color"]
                }
                for d in danmaku_list
            ]
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool
async def get_user_videos(mid: int, ps: int = 10, pn: int = 1) -> str:
    """获取B站用户的视频列表。
    
    参数:
        mid: 用户的 UID
        ps: 每页数量，默认 10
        pn: 页码，默认 1
    
    返回:
        视频列表 JSON
    """
    img_key, sub_key = await get_wbi_keys()
    params = {
        "mid": mid,
        "ps": ps,
        "pn": pn,
        "tid": 0,
        "keyword": "",
        "order": "pubdate"
    }
    signed_params = enc_wbi(params, img_key, sub_key)
    
    url = "https://api.bilibili.com/x/space/wbi/arc/search"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": f"https://space.bilibili.com/{mid}/video"
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=signed_params, headers=headers) as response:
            data = await response.json()
            
    if data.get("code") != 0:
        return json.dumps({"error": data.get("message", "未知错误"), "code": data.get("code")}, ensure_ascii=False)
    
    list_data = data.get("data", {}).get("list", {}).get("vlist", [])
    
    result = []
    for v in list_data:
        result.append({
            "bvid": v.get("bvid"),
            "title": v.get("title"),
            "description": v.get("description"),
            "duration": v.get("length"),
            "publish_time": v.get("created"),
            "play": v.get("play"),
            "comment": v.get("comment"),
            "author": v.get("author")
        })
    
    return json.dumps(result, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    mcp.run()
