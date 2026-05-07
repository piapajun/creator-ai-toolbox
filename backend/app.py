#!/usr/bin/env python3
"""
Creator AI Toolbox - Flask 后端
帮头条创作者用AI找到爆款选题，一键生成内容
"""
import json
import os
import re
import time
import urllib.parse
from datetime import datetime

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# ========== 配置 ==========
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "rewrite_api_key.json")
TOUTIAO_COOKIE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "toutiao_cookies.json")

# 热榜签名
HOT_BOARD_SIG = "_02B4Z6wo00f01gSIqVQAAIDBiSAQ3QJ33SoErK3AAOjgV5CjGUsxoVn36NFc5GKepd6hJ6KotRot94R0neUhhOJjiLNDuSAdXizEvIyBv2W3gd8u0b25ONTJm-0P61jDfJoUEKSlOYDRFBUx2d"
HOT_BOARD_SIG_BAK = "_02B4Z6wo00d01gSIqVQAAIDBiSAQ3QJ33SoErK3AAOjgtrNqPQoD6qFq1lVU8ybgrvd9N1Aypqwh591J0aV-OKKKdaeH7dm.fGHv-q1cPeOfx4Izm-AXJTMNVhEZWqhawtj9zzgIn9Gl.L.O2c"

# ========== 工具函数 ==========

def load_deepseek_key():
    """加载 DeepSeek API Key"""
    try:
        with open(CONFIG_PATH, "r") as f:
            key = json.load(f).get("deepseek", {}).get("api_key", "")
            return key.strip() if key else ""
    except:
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        return key.strip() if key else ""


def load_toutiao_cookies():
    """加载头条 Cookie（支持环境变量 + list/dict 文件格式）"""
    # 优先从环境变量读取
    env_cookie = os.environ.get("TOUTIAO_COOKIES", "")
    if env_cookie:
        return env_cookie.strip()
    try:
        with open(TOUTIAO_COOKIE_PATH, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            cookie_str = "; ".join(f"{c.get('name', '')}={c.get('value', '')}" for c in data if c.get('name'))
            return cookie_str
        elif isinstance(data, dict):
            return "; ".join(f"{k}={v}" for k, v in data.items())
        return ""
    except:
        return ""


def deepseek_chat(prompt, system="你是一个资深内容创作者助手。", max_tokens=2000):
    """调用 DeepSeek API"""
    api_key = load_deepseek_key()
    if not api_key:
        return "⚠️ 未配置 DeepSeek API Key"

    resp = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.8,
            "max_tokens": max_tokens,
        },
        timeout=60,
    )
    data = resp.json()
    if "error" in data:
        return f"API错误: {data['error']['message']}"
    return data["choices"][0]["message"]["content"]


# InterestCategory 中文映射（头条API返回的英文分类标签）
INTEREST_CAT_CN = {
    "sports": "⚽ 体育",
    "finance": "💰 财经",
    "international": "🌍 国际",
    "military": "🛡️ 军事",
    "taiwan": "🇹🇼 台海",
    "health": "🏥 健康",
    "technology": "💻 科技",
    "entertainment": "🎬 娱乐",
    "education": "📚 教育",
    "society": "👥 社会",
}


def get_hot_board():
    """获取头条热榜全部50条"""
    sigs = [HOT_BOARD_SIG, HOT_BOARD_SIG_BAK]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.toutiao.com/",
    }

    for sig in sigs:
        try:
            url = f"https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc&_signature={sig}"
            resp = requests.get(url, headers=headers, timeout=10)
            raw_data = resp.json()
            data = raw_data.get("data", [])
            hot_list = []
            for item in data[:30]:
                title = item.get("Title", "")
                source_url = item.get("Url", "")
                if source_url and not source_url.startswith("http"):
                    source_url = "https://www.toutiao.com" + source_url

                # 提取兴趣分类
                interest_cats = item.get("InterestCategory", [])
                if isinstance(interest_cats, str):
                    interest_cats = [interest_cats]
                elif not isinstance(interest_cats, list):
                    interest_cats = []

                # 封面图
                img_dict = item.get("Image", {})
                image_url = ""
                if isinstance(img_dict, dict):
                    image_url = img_dict.get("url", "")

                hot_list.append({
                    "title": title,
                    "url": source_url,
                    "hot_value": item.get("HotValue", ""),
                    "label": item.get("Label", ""),
                    "cluster_id": item.get("ClusterIdStr", ""),
                    "interest_categories": interest_cats,
                    "image_url": image_url,
                    "query_word": item.get("QueryWord", ""),
                })
            return hot_list
        except Exception as e:
            print(f"Hotboard fetch error (sig={sig[:10]}...): {e}")
            continue
    return []


def search_low_fan_articles(keyword, limit=15):
    """搜索低粉爆文 — 适配 2026年5月 头条搜索API新结构

    新结构：data[] 是混合列表，文章字段直接在 item 顶层，不再嵌套在
    display.cards[].merge_article[] 中。需按 cell_type 区分类型：
      - 无 cell_type / cell_type 含 article → 图文文章（有 title, abstract, article_url）
      - cell_type=50 → 微头条（有 content，用 thread_base_data_user_action 做互动分）
      - cell_type=26/21/20/58 → GPT回答/搜索建议/用户推荐 → 跳过
    """
    cookie_str = load_toutiao_cookies()

    # pd=synthesis 获得文章+微头条混合结果
    url = f"https://www.toutiao.com/api/search/content/?keyword={urllib.parse.quote(keyword)}&pd=synthesis&source=input&offset=0&count=20"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.toutiao.com/",
        "Cookie": cookie_str,
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        data_items = data.get("data") or []

        results = []
        for item in data_items:
            cell_type = item.get("cell_type", 0)

            # --- 图文文章（有 group_id / article_url）---
            if cell_type not in (20, 21, 26, 50, 58) and item.get("article_url"):
                title = item.get("title", "")
                if not title:
                    continue
                url_val = item.get("article_url", "") or item.get("share_url", "")
                source = item.get("source", "") or item.get("media_name", "")
                abstract = item.get("abstract", "")[:300]
                image = item.get("image_url", "") or item.get("middle_image_url", "") or item.get("large_image_url", "")

                # 互动数据（普通文章没有直接的 read_count）
                interaction = item.get("thread_base_data_user_action", {})
                score = (
                    interaction.get("go_detail_count", 0) * 2
                    + interaction.get("digg_count", 0)
                    + interaction.get("comment_count", 0) * 3
                    + interaction.get("forward_count", 0) * 5
                )

                results.append({
                    "title": re.sub(r'<[^>]+>', '', title),
                    "url": url_val,
                    "read_count": interaction.get("go_detail_count", 0),
                    "digg_count": interaction.get("digg_count", 0),
                    "comment_count": interaction.get("comment_count", 0),
                    "source": source,
                    "abstract": abstract,
                    "image_url": image,
                    "score": score,
                    "type": "article",
                })

            # --- 微头条（cell_type=50）---
            elif cell_type == 50:
                content = item.get("content", "") or item.get("rich_content", "")
                if not content:
                    continue
                # 微头条没有 title，用 content 前40字
                clean_content = re.sub(r'<[^>]+>', '', content)
                title = clean_content[:40] + ("..." if len(clean_content) > 40 else "")
                url_val = item.get("share_url", "") or item.get("ttsearch_msite_url", "")
                image = item.get("image_url", "") or item.get("thumb_image_url", "")

                interaction = item.get("thread_base_data_user_action", {})
                score = (
                    interaction.get("go_detail_count", 0) * 2
                    + interaction.get("digg_count", 0)
                    + interaction.get("comment_count", 0) * 3
                    + interaction.get("forward_count", 0) * 5
                )

                results.append({
                    "title": title,
                    "url": url_val,
                    "read_count": interaction.get("go_detail_count", 0),
                    "digg_count": interaction.get("digg_count", 0),
                    "comment_count": interaction.get("comment_count", 0),
                    "source": item.get("source", "") or item.get("media_name", ""),
                    "abstract": clean_content[:300],
                    "image_url": image,
                    "score": score,
                    "type": "microblog",
                })

        # 去重
        seen = set()
        unique = []
        for r in results:
            if r["title"] not in seen:
                seen.add(r["title"])
                unique.append(r)

        unique.sort(key=lambda x: x["score"], reverse=True)
        return unique[:limit]
    except Exception as e:
        print(f"Search error: {e}")
        return []


def analyze_hot_trends(hot_list):
    """AI分析热榜趋势"""
    if not hot_list:
        return {"summary": "热榜数据获取失败", "categories": [], "opportunities": []}

    titles = "\n".join([f"{i+1}. {h['title']} (热度:{h.get('hot_value','')})"
                         for i, h in enumerate(hot_list[:20])])

    prompt = f"""分析以下今日头条热榜，给出创作者可以切入的机会：

热榜列表：
{titles}

请返回JSON格式（不要markdown代码块）：
{{
  "summary": "一句话总结今日热榜趋势",
  "categories": [
    {{"name": "分类名", "count": 数量, "hot_topics": ["话题1", "话题2"]}}
  ],
  "opportunities": [
    {{"topic": "可切入话题", "angle": "切入角度", "difficulty": "低/中/高", "potential": "潜力评估"}}
  ]
}}"""

    result = deepseek_chat(prompt, system="你是头条数据分析专家，返回纯JSON。")
    try:
        # 尝试清理markdown代码块
        result = re.sub(r'```json\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return json.loads(result.strip())
    except:
        return {"summary": result[:200], "categories": [], "opportunities": []}


# ========== 静态文件（前端） ==========
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")


@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    """Serve static files from frontend dir"""
    filepath = os.path.join(FRONTEND_DIR, filename)
    if os.path.exists(filepath):
        return send_from_directory(FRONTEND_DIR, filename)
    return jsonify({"error": "Not found"}), 404


# ========== API 路由 ==========

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})


@app.route("/api/hotboard")
def api_hotboard():
    """获取热榜全部50条 + 分类分布"""
    hot_list = get_hot_board()

    # 统计分类分布
    cat_count = {}
    for item in hot_list:
        for ic in item.get("interest_categories", []):
            cat_count[ic] = cat_count.get(ic, 0) + 1
    # 无分类的归入社会
    no_cat_count = sum(1 for item in hot_list if not item.get("interest_categories"))
    if no_cat_count > 0:
        cat_count["society"] = cat_count.get("society", 0) + no_cat_count

    # 排序：按数量降序，综合放第一个
    sorted_cats = sorted(cat_count.items(), key=lambda x: -x[1])
    categories_list = [{"id": "all", "name": "🔥 综合", "count": len(hot_list)}]
    for eng_id, cnt in sorted_cats:
        cn_name = INTEREST_CAT_CN.get(eng_id, eng_id)
        categories_list.append({"id": eng_id, "name": cn_name, "count": cnt})

    return jsonify({
        "data": hot_list,
        "count": len(hot_list),
        "categories": categories_list,
    })


@app.route("/api/hotboard/categories")
def api_hotboard_categories():
    """列出所有可用的热榜分类"""
    return jsonify({"categories": INTEREST_CAT_CN})


@app.route("/api/hotboard/detail")
def api_hotboard_detail():
    """获取热榜条目详情 - AI生成摘要+切入角度建议"""
    title = request.args.get("title", "").strip()
    url = request.args.get("url", "").strip()
    hot_value = request.args.get("hot_value", "").strip()
    label = request.args.get("label", "").strip()

    if not title:
        return jsonify({"error": "请提供文章标题"}), 400

    # AI 生成详情
    label_text = f" [{label}]" if label else ""
    prompt = f"""你是资深头条内容分析师。请针对以下热榜条目生成深度分析：

标题：{title}{label_text}
热度值：{hot_value}

请返回JSON（不要markdown代码块）：
{{
  "topic_summary": "100字以内的话题概述，解释为什么这条新闻火了",
  "background": "相关背景知识（100字以内）",
  "angles": ["可切入的角度1", "角度2", "角度3"],
  "target_readers": "目标读者画像",
  "suggested_title": "如果是我来写这篇文章，标题会是...",
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5"]
}}"""

    result = deepseek_chat(prompt, system="你是头条深度内容分析师，返回纯JSON。", max_tokens=800)
    try:
        result = re.sub(r'```json\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        analysis = json.loads(result.strip())
    except:
        analysis = {"topic_summary": result[:200], "background": "", "angles": [], "suggested_title": "", "keywords": []}

    return jsonify({
        "title": title,
        "url": url,
        "hot_value": hot_value,
        "label": label,
        "analysis": analysis,
    })


@app.route("/api/hotboard/analyze")
def api_hotboard_analyze():
    """AI分析热榜趋势"""
    hot_list = get_hot_board()
    analysis = analyze_hot_trends(hot_list)
    return jsonify({"analysis": analysis, "hot_count": len(hot_list)})


@app.route("/api/search")
def api_search():
    """搜索低粉爆文"""
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return jsonify({"error": "请输入搜索关键词"}), 400

    articles = search_low_fan_articles(keyword)
    if not articles:
        return jsonify({"data": [], "message": "未找到相关文章，请尝试其他关键词"})

    # AI分析这些爆文的共同特征
    titles_text = "\n".join([f"- {a['title']}" for a in articles[:5]])
    analysis_prompt = f"""分析以下低粉爆文的共同特征，总结为什么这些文章能成为爆款：

{titles_text}

请返回JSON：
{{
  "common_patterns": ["模式1", "模式2", "模式3"],
  "title_style": "标题风格总结",
  "content_angle": "内容角度建议",
  "recommended_titles": ["建议标题1", "建议标题2", "建议标题3"]
}}"""

    ai_analysis = deepseek_chat(analysis_prompt, "你是爆文分析专家，返回纯JSON。")
    try:
        ai_analysis = re.sub(r'```json\s*', '', ai_analysis)
        ai_analysis = re.sub(r'```\s*', '', ai_analysis)
        ai_analysis = json.loads(ai_analysis.strip())
    except:
        ai_analysis = {"common_patterns": [], "title_style": "", "recommended_titles": []}

    return jsonify({
        "keyword": keyword,
        "articles": articles,
        "analysis": ai_analysis,
    })


@app.route("/api/rewrite", methods=["POST"])
def api_rewrite():
    """AI改写文章 — 支持粘贴原文 或 仅输入主题/关键词生成"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "请提供文章内容"}), 400

    original_text = data.get("text", "").strip()
    reference_title = data.get("reference_title", "").strip()
    style = data.get("style", "智能改写")
    mode = data.get("mode", "rewrite")  # rewrite | generate（仅主题生成全文）

    if not original_text and not reference_title:
        return jsonify({"error": "请提供原文内容或参考标题"}), 400

    # 对生成模式，不带原文参考文章
    if mode == "generate":
        context_text = original_text or reference_title
        prompt = f"""你是一个资深头条内容创作者。请根据以下主题，生成一篇完整的头条爆款文章：

主题/关键词：{context_text}

要求：
1. 标题要吸引眼球，引发好奇，使用数字、反差、悬念等技巧
2. 开头30字内有冲击力，让读者想继续看
3. 结构清晰，分段合理（用小标题分隔）
4. 字数800-1500字
5. 加入真实案例或数据增加可信度
6. 结尾要有互动引导（引导评论）
7. 适合普通读者阅读，不要过于专业

请直接输出文章（第一行是标题，第二行开始是正文），不要加任何解释或符号。"""
    elif style == "智能改写":
        # AI自动判断最佳改写策略
        context_text = original_text or reference_title
        prompt = f"""你是一个资深头条内容创作者。请分析以下内容，自动选择最佳的改写策略，生成一篇能成为爆款的头条文章：

{context_text}

策略参考：如果原文是干货型→增加情感共鸣和故事；如果是观点型→增加数据支撑和案例；如果是新闻型→增加深度分析和延展阅读；如果是故事型→提炼核心观点并增加读者共鸣。

要求：
1. 标题要有爆款潜质（数字、反差、悬念、利益点）
2. 开头30字必须有冲击力
3. 结构清晰，分段合理，每段有明确主题
4. 字数800-1500字
5. 纯文本输出，不要任何markdown符号
6. 结尾有互动引导

请直接输出改写后的文章（第一行是标题，第二行开始是正文），不要加任何解释或符号。"""
    else:
        context_text = original_text
        if reference_title and not original_text:
            context_text = f"参考主题：{reference_title}"
        prompt = f"""你是一个资深头条内容创作者。请根据以下内容进行{style}。

{context_text}

要求：
1. 标题要吸引眼球，引发好奇，不要带任何符号（不要加#或*等）
2. 开头要有冲击力，吸引读者继续阅读
3. 结构清晰，分段合理
4. 字数800-1500字
5. 不要使用任何markdown格式符号，纯文本输出
6. 加入互动引导（引导评论）

请直接输出改写后的文章（第一行是标题，第二行是正文），不要加任何解释或符号。"""

    result = deepseek_chat(prompt, max_tokens=3000)

    # 清理格式
    lines = result.strip().split("\n")
    title = lines[0].strip().lstrip("#*- ").strip() if lines else ""
    content = "\n".join(lines[1:]) if len(lines) > 1 else ""

    return jsonify({
        "title": title,
        "content": content,
        "raw": result,
        "word_count": len(content),
        "style": style,
        "mode": mode,
    })


@app.route("/api/rewrite/titles", methods=["POST"])
def api_rewrite_titles():
    """AI生成多个爆款标题 — 输入主题，返回5个标题选项"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "请提供内容"}), 400

    text = data.get("text", "").strip()
    count = data.get("count", 5)

    if not text:
        return jsonify({"error": "请输入主题或关键词"}), 400

    prompt = f"""你是头条标题创作专家。根据以下主题/内容，生成{count}个不同风格的爆款标题。

{text}

要求：
1. 每个标题必须能引发好奇心或强烈情绪
2. 用数字、反差、悬念、利益点等技巧
3. 标题长度15-30字
4. 5个标题风格各不相同（如：数字型、悬念型、身份标签型、利益承诺型、故事型）

请返回JSON（不要markdown代码块）：
{{
  "titles": [
    {{"text": "标题文字", "style": "风格名", "why": "为什么这个标题能火"}}
  ]
}}"""

    result = deepseek_chat(prompt, system="你是头条标题创作专家，返回纯JSON。", max_tokens=800)
    try:
        result = re.sub(r'```json\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        titles_data = json.loads(result.strip())
    except:
        titles_data = {"titles": []}

    return jsonify({"titles": titles_data.get("titles", []), "keyword": text})


@app.route("/api/rewrite/from-hot", methods=["POST"])
def api_rewrite_from_hot():
    """从热榜标题一键生成文章 — 输入热榜标题+分析，直接出文"""
    data = request.get_json()
    if not data:
        return jsonify({"error": "请提供热榜标题"}), 400

    hot_title = data.get("title", "").strip()
    angle = data.get("angle", "").strip()
    background = data.get("background", "").strip()

    if not hot_title:
        return jsonify({"error": "请提供热榜标题"}), 400

    angle_hint = f"\n切入角度建议：{angle}" if angle else ""
    bg_hint = f"\n背景信息：{background}" if background else ""

    prompt = f"""你是一个资深头条内容创作者。请根据热榜话题，创作一篇头条爆款文章。

热榜话题：{hot_title}{bg_hint}{angle_hint}

要求：
1. 标题要吸引眼球，不要和热榜原标题一样，要有你自己的独特视角
2. 开头30字有冲击力，紧扣热榜话题但给出新信息或新观点
3. 结构清晰：背景铺垫 → 事件分析 → 深度解读 → 读者启示
4. 字数800-1500字
5. 加入你对这个事件的独特见解
6. 结尾引导读者评论互动

请直接输出文章（第一行是标题，第二行开始是正文），不要加任何解释或符号。"""

    result = deepseek_chat(prompt, max_tokens=3000)

    lines = result.strip().split("\n")
    title = lines[0].strip().lstrip("#*- ").strip() if lines else ""
    content = "\n".join(lines[1:]) if len(lines) > 1 else ""

    return jsonify({
        "title": title,
        "content": content,
        "word_count": len(content),
        "hot_topic": hot_title,
    })


@app.route("/api/idea-generator")
def api_idea_generator():
    """AI生成选题建议"""
    category = request.args.get("category", "副业赚钱")

    hot_list = get_hot_board()
    hot_titles = "\n".join([h['title'] for h in hot_list[:10]])

    prompt = f"""你是头条内容策划专家。针对「{category}」领域，结合当前热榜趋势，生成5个爆款选题。

当前热榜：
{hot_titles}

请返回JSON：
{{
  "ideas": [
    {{
      "title": "爆款标题",
      "angle": "切入角度",
      "outline": ["要点1", "要点2", "要点3"],
      "hook": "开头钩子（前30字）",
      "target_audience": "目标读者",
      "estimated_read": "预估阅读量（低/中/高）"
    }}
  ]
}}"""

    result = deepseek_chat(prompt, "你是头条内容策划专家，返回纯JSON。")
    try:
        result = re.sub(r'```json\s*', '', result)
        result = re.sub(r'```\s*', '', result)
        return jsonify({"ideas": json.loads(result.strip()).get("ideas", [])})
    except:
        return jsonify({"ideas": [], "raw": result[:500]})


# ========== 图片搜索 ==========
def load_pexels_key():
    """从配置文件加载 Pexels Key"""
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f).get("pexels", {}).get("api_key", "")
    except:
        return ""

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "") or load_pexels_key()

@app.route("/api/image-search")
def api_image_search():
    """搜索免费可商用图片"""
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return jsonify({"images": []})

    images = []

    # 方案1: Pexels API（需要免费API key）
    if PEXELS_API_KEY:
        try:
            r = requests.get(
                "https://api.pexels.com/v1/search",
                headers={"Authorization": PEXELS_API_KEY},
                params={"query": keyword, "per_page": 8, "locale": "zh-CN"},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                for photo in data.get("photos", []):
                    images.append({
                        "url": photo["src"]["large"],
                        "thumb": photo["src"]["medium"],
                        "alt": photo.get("alt", keyword),
                        "photographer": photo.get("photographer", ""),
                        "source": "pexels",
                    })
        except Exception as e:
            print(f"Pexels error: {e}")

    # 方案2: 没有Pexels key时用 Unsplash Source（免费无需key）
    if not images:
        # Unsplash source URL 返回随机相关图片
        # 生成8张不同尺寸的图片以获取不同结果
        for i in range(8):
            seed = i * 100 + int(time.time()) % 1000
            images.append({
                "url": f"https://source.unsplash.com/800x600/?{keyword}&{seed}",
                "thumb": f"https://source.unsplash.com/400x300/?{keyword}&{seed}",
                "alt": f"{keyword} 图片 {i+1}",
                "photographer": "Unsplash",
                "source": "unsplash",
            })

    return jsonify({"images": images})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Creator AI Toolbox 启动在 http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)


# ========== 调试端点 ==========
@app.route("/api/debug")
def api_debug():
    """诊断端点：检查密钥和 Cookie 状态"""
    ds_key = load_deepseek_key()
    cookie = load_toutiao_cookies()
    return jsonify({
        "deepseek_key": f"len={len(ds_key)}, preview={ds_key[:10] if ds_key else 'EMPTY'}...{ds_key[-4:] if len(ds_key) > 4 else ds_key}",
        "toutiao_cookies": f"len={len(cookie)}, preview={cookie[:80] if cookie else 'EMPTY'}...",
        "env": {
            "DEEPSEEK_API_KEY": f"set={bool(os.environ.get('DEEPSEEK_API_KEY'))}, len={len(os.environ.get('DEEPSEEK_API_KEY',''))}",
            "TOUTIAO_COOKIES": f"set={bool(os.environ.get('TOUTIAO_COOKIES'))}, len={len(os.environ.get('TOUTIAO_COOKIES',''))}",
        }
    })
