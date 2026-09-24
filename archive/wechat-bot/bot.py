# -*- coding: utf-8 -*-
"""
微信 × Jev 判断机器人

一条微信消息 → 结构化判断（意图 / 紧迫 / 情绪）→ 回一张判断卡。

后端按环境变量自动选，优先级从高到低：
    TYPESAFE_API_KEY   → Jev（System One），快且便宜
    ARK_API_KEY        → 豆包 / 火山方舟（还要填 ARK_MODEL）
    OPENAI_API_KEY     → 任意 OpenAI 兼容接口（OpenRouter / Vercel / 自建）
    都没有              → 本地关键词模拟，只用来验证微信通道

key 不用配到系统里，直接写同目录的 .env 就行（已存在的环境变量优先）。

用法：
    python bot.py                              启动微信机器人
    python bot.py --demo "帮我改个文件，挺急的"   本地试一条，不连微信
    python bot.py --demo                       进入交互模式，随便打
"""

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

from pathlib import Path


# ---------------- 读 .env ----------------
# 把 key 写在同目录的 .env 里就行，不用去折腾系统环境变量。
# 已经存在的环境变量优先，.env 只做兜底。


def _load_env_file():
    path = Path(__file__).with_name(".env")
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and not os.environ.get(key):
            os.environ[key] = value


_load_env_file()

# ---------------- 配置 ----------------

TYPESAFE_KEY = os.environ.get("TYPESAFE_API_KEY", "").strip()
TYPESAFE_URL = os.environ.get("TYPESAFE_API_URL", "https://api.typesafe.ai/v1/systemone")
TYPESAFE_MODEL = os.environ.get("TYPESAFE_MODEL", "jev-latest")

# 火山方舟 —— 豆包大模型的 API 平台（注意：不是豆包 App）
ARK_KEY = os.environ.get("ARK_API_KEY", "").strip()
ARK_URL = os.environ.get("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
ARK_MODEL = os.environ.get("ARK_MODEL", "").strip()

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_URL = os.environ.get("OPENAI_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "openai/gpt-4o-mini")

CRED_FILE = os.environ.get("WECHAT_CRED_FILE", "creds.json")

# ---------------- 判断维度 ----------------
# Jev 的三种题型：
#   choice —— 从几个选项里挑一个
#   score  —— 按有序量表打分
#   noul   —— 是 / 否（返回 true 的概率，0~1）
#
# 想换成你自己的判断维度，改这里就行。

QUESTIONS = {
    "intent": {
        "type": "choice",
        "instructions": "这条消息的主要意图是什么？",
        "criteria": {
            "question": "在提问，想获取信息或答案",
            "task": "在派活，希望对方帮忙做事",
            "chat": "闲聊、寒暄、分享日常",
            "emotion": "在表达情绪，吐槽或抱怨",
        },
    },
    "urgent": {
        "type": "noul",
        "instructions": "这条消息是否带有紧迫性，需要马上处理？",
    },
    "mood": {
        "type": "score",
        "instructions": "发信人当前的情绪状态如何？",
        "criteria": ["很差", "偏低", "一般", "不错", "很好"],
    },
}

INTENT_LABEL = {
    "question": "提问",
    "task": "派活",
    "chat": "闲聊",
    "emotion": "情绪表达",
}
INTENT_ORDER = ["question", "task", "chat", "emotion"]
MOOD_SCALE = QUESTIONS["mood"]["criteria"]


# ---------------- 统一入口 ----------------


_ark_pick = None  # 已经试通的豆包模型，之后直接用，不再一个个试


def _ark_candidates():
    return [m.strip() for m in ARK_MODEL.split(",") if m.strip()]


def _call_ark(text, user_prompt=None, system_prompt=None):
    """豆包：ARK_MODEL 可以写多个候选（逗号隔开），挑第一个开通了的用。"""
    global _ark_pick

    cands = _ark_candidates()
    if not cands:
        raise RuntimeError("填了 ARK_API_KEY，但 ARK_MODEL 还空着，去 .env 里补一个")
    if _ark_pick and _ark_pick in cands:
        cands = [_ark_pick] + [m for m in cands if m != _ark_pick]

    last = None
    for model in cands:
        try:
            result = _call_openai(text, ARK_KEY, ARK_URL, model, user_prompt, system_prompt)
        except RuntimeError as exc:
            last = exc
            if "ModelNotOpen" in str(exc) or "NotFound" in str(exc):
                continue
            raise
        _ark_pick = model
        return result

    if last is None:
        raise RuntimeError("豆包没有可用模型")
    if "ModelNotOpen" in str(last) or "NotFound" in str(last):
        raise RuntimeError(
            f"{last}\n  → key 本身没问题，是候选模型一个都没开通。"
            "去火山方舟控制台「开通管理」里开通一个，模型名填回 .env 的 ARK_MODEL"
        )
    raise last


def _backend_name():
    if TYPESAFE_KEY:
        return f"Jev（{TYPESAFE_MODEL}）"
    if ARK_KEY:
        cands = _ark_candidates()
        return f"豆包 / 火山方舟（{_ark_pick or (cands[0] if cands else '未填模型名')}）"
    if OPENAI_KEY:
        return f"OpenAI 兼容接口（{OPENAI_MODEL} @ {OPENAI_URL}）"
    return "本地模拟"


def decide(text):
    """返回 (标准化的判断结果 dict, 后端名)。"""
    if TYPESAFE_KEY:
        return _normalize(_call_typesafe(text)), "typesafe"
    if ARK_KEY:
        return _normalize(_call_ark(text)), "ark"
    if OPENAI_KEY:
        return _normalize(_call_openai(text, OPENAI_KEY, OPENAI_URL, OPENAI_MODEL)), "openai"
    return _normalize(mock_answers(text)), "mock"


def run_model(text, user_prompt, system_prompt=None):
    """给别的程序用：拿当前配好的后端跑一段自定义 prompt，返回解析后的 JSON。"""
    if ARK_KEY:
        return _call_ark(text, user_prompt, system_prompt)
    if OPENAI_KEY:
        return _call_openai(text, OPENAI_KEY, OPENAI_URL, OPENAI_MODEL, user_prompt, system_prompt)
    raise RuntimeError("没配可用的模型后端，先在 .env 里填 ARK_API_KEY 或 OPENAI_API_KEY")


# ---------------- 后端 1：Jev ----------------


def _call_typesafe(text):
    payload = {"model": TYPESAFE_MODEL, "state": text, "questions": QUESTIONS}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(TYPESAFE_URL, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {TYPESAFE_KEY}")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    return _post_json(req, "Jev")


# ---------------- 后端 2：任意 OpenAI 兼容接口 ----------------

_OPENAI_SYSTEM = (
    "你是一个结构化判断引擎。只输出 JSON 对象，不要任何解释、不要代码块标记。"
)

_OPENAI_USER = """对下面这条微信消息做三项判断，只返回 JSON：

{{
  "intent": {{"choice": "question | task | chat | emotion", "confidence": 0.0-1.0}},
  "urgent": {{"noul": 0.0-1.0}},
  "mood":   {{"score": 0.0-4.0}}
}}

判定标准：
- intent  question=提问要答案 / task=派活要人做事 / chat=闲聊分享 / emotion=表达情绪吐槽
- urgent  是否急到需要马上处理
- mood    0=很差 1=偏低 2=一般 3=不错 4=很好

消息：{text}"""

_ok_variant = {}  # base_url -> 上次试通的参数变体下标，之后直接用它，不再每次试错


def _call_openai(text, key, base_url, model, user_prompt=None, system_prompt=None):
    """OpenAI 兼容接口。参数各家支持度不一样，所以准备了几个变体挨个试。"""
    url = f"{base_url}/chat/completions"
    base = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt or _OPENAI_SYSTEM},
            {"role": "user", "content": user_prompt or _OPENAI_USER.format(text=text)},
        ],
        "temperature": 0,
    }

    # 关掉思考（判断类任务用不上，开着又慢又贵）、强制 JSON 输出，个别模型不认就退一档
    variants = [
        {"thinking": {"type": "disabled"}, "response_format": {"type": "json_object"}},
        {"thinking": {"type": "disabled"}},
        {"response_format": {"type": "json_object"}},
        {},
    ]

    tried = _ok_variant.get(base_url, 0)
    order = [tried] + [i for i in range(len(variants)) if i != tried]

    last = None
    for idx in order:
        body = json.dumps({**base, **variants[idx]}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Authorization", f"Bearer {key}")
        req.add_header("Content-Type", "application/json; charset=utf-8")
        try:
            raw = _post_json(req, "模型接口")
        except RuntimeError as exc:
            last = exc
            if "HTTP 400" in str(exc):  # 参数不认，换下一个变体
                continue
            raise
        content = raw["choices"][0]["message"].get("content") or ""
        if not content.strip():
            last = RuntimeError("模型返回空内容")
            continue
        _ok_variant[base_url] = idx
        return _extract_json(content)

    raise last if last else RuntimeError("模型接口调用失败")


def _extract_json(text):
    """从可能带 ``` 包裹的回复里抠出 JSON。"""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise RuntimeError(f"模型没返回 JSON：{text[:120]}")
        return json.loads(match.group(0))


def _post_json(req, who):
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"HTTP {exc.code} —— {detail}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"连不上{who}：{exc.reason}") from None


# ---------------- 结果归一化 ----------------


def _normalize(raw):
    """把各家返回统一成 {intent:{choice,confidence}, urgent:{noul}, mood:{score}}。"""
    if not isinstance(raw, dict):
        raise RuntimeError(f"返回格式不对：{raw!r}")
    src = raw.get("answers") if isinstance(raw.get("answers"), dict) else raw

    out = {}

    intent = src.get("intent") or {}
    if isinstance(intent, str):
        intent = {"choice": intent}
    choice = intent.get("choice") or intent.get("label")
    if choice:
        conf = intent.get("confidence")
        if not isinstance(conf, (int, float)):
            probs = intent.get("probabilities") or {}
            conf = max(probs.values()) if probs else None
        out["intent"] = {
            "choice": str(choice).strip().lower(),
            "confidence": float(conf) if isinstance(conf, (int, float)) else None,
        }

    urgent = src.get("urgent") or {}
    if isinstance(urgent, (int, float, bool)):
        urgent = {"noul": float(urgent)}
    prob = urgent.get("noul", urgent.get("probability"))
    if isinstance(prob, (int, float, bool)):
        out["urgent"] = {"noul": max(0.0, min(1.0, float(prob)))}

    mood = src.get("mood") or {}
    if isinstance(mood, (int, float)):
        mood = {"score": mood}
    score = mood.get("score", mood.get("value"))
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        out["mood"] = {"score": max(0.0, min(4.0, float(score)))}

    if not out:
        raise RuntimeError(f"没解析出任何判断：{raw!r}")
    return out


# ---------------- 本地模拟 ----------------

_TASK_WORDS = [
    "帮我", "帮忙", "麻烦", "请", "给我", "整理", "归纳", "写个", "写一份", "写一篇",
    "做个", "做一个", "查一下", "查查", "搜一下", "翻译", "总结", "生成", "导出",
    "列个", "列一下", "排个", "改一下", "改改", "优化", "润色", "算一下", "看一下",
    "弄个", "搞个", "画个", "校对", "排版", "处理", "分析", "对比",
    "记得", "别忘", "提醒", "确认一下", "回一下",
]
_GREETING_WORDS = [
    "在吗", "在么", "在不在", "你好", "您好", "哈喽", "hi", "hello",
    "早上好", "中午好", "晚上好", "早安", "晚安", "早啊", "睡了没", "干嘛呢",
]
_QUESTION_WORDS = [
    "怎么", "为什么", "为啥", "啥", "什么", "多少", "哪", "吗", "呢", "能不能",
    "可不可以", "是不是", "如何", "哪种", "哪个", "几点", "哪儿", "谁", "有没有",
]
_NEG_WORDS = [
    "烦", "累", "难受", "崩溃", "气死", "郁闷", "委屈", "焦虑", "压力", "头疼",
    "不想", "难过", "哭了", "呜呜", "唉", "无语", "麻了", "服了", "糟心", "emo",
    "破防", "烦死", "心累", "痛苦", "难受死", "倒霉", "惨", "扛不住",
]
_POS_WORDS = [
    "开心", "哈哈", "嘿嘿", "好耶", "爽", "棒", "太好了", "喜欢", "爱", "不错",
    "舒服", "美滋滋", "值了", "笑死", "nice", "牛", "给力", "幸福", "满足",
]
_URGENT_WORDS = [
    "急", "马上", "尽快", "立刻", "赶紧", "催", "来不及", "截止", "deadline",
    "速度", "抓紧", "现在就", "立马",
]


def _count(text, words):
    hits = [w for w in words if w in text]
    return len(hits), hits


def mock_answers(text):
    """关键词版判断。比纯 if-else 多几层信号，至少别一眼看出是硬猜。"""
    text = (text or "").strip()
    low = text.lower()

    task_n, _ = _count(low, _TASK_WORDS)
    ques_n, _ = _count(low, _QUESTION_WORDS)
    neg_n, _ = _count(low, _NEG_WORDS)
    pos_n, _ = _count(low, _POS_WORDS)
    bang = low.count("!") + low.count("！")
    if "?" in low or "？" in low:
        ques_n += 2

    scores = {
        "task": task_n * 2.2,
        "question": ques_n * 1.8,
        "emotion": (neg_n + pos_n) * 2.0 + (0.6 if bang >= 2 else 0.0),
        "chat": 1.0,
    }
    # 短消息里的招呼语，别被"吗"当成提问
    if len(low) <= 8 and any(w in low for w in _GREETING_WORDS):
        scores["chat"] += 3.0
    # 平手时按这个优先级取
    for key in ("task", "question", "emotion", "chat"):
        scores[key] += {"task": 0.30, "question": 0.20, "emotion": 0.10, "chat": 0.0}[key]

    choice = max(scores, key=lambda k: scores[k])
    total = sum(scores.values()) or 1.0
    probs = {k: round(v / total, 3) for k, v in scores.items()}

    signal = max(scores.values())
    conf = min(0.94, 0.52 + signal * 0.08)
    probs[choice] = max(probs[choice], conf)
    s = sum(probs.values())
    probs = {k: round(v / s, 3) for k, v in probs.items()}

    urgent_n, _ = _count(low, _URGENT_WORDS)
    if urgent_n:
        noul = min(0.95, 0.60 + 0.10 * (urgent_n - 1) + (0.08 if bang else 0.0))
    else:
        noul = min(0.40, 0.10 + 0.05 * bang)

    mood = 2.0
    mood -= min(2.0, neg_n * 0.55)
    mood += min(1.8, pos_n * 0.55)
    if bang >= 3 and neg_n:
        mood -= 0.25
    if "?" in low or "？" in low:
        mood -= 0.1
    mood = max(0.0, min(4.0, mood))

    return {
        "model": "mock",
        "answers": {
            "intent": {
                "type": "choice",
                "choice": choice,
                "probabilities": probs,
                "confidence": round(conf, 3),
            },
            "urgent": {"type": "noul", "noul": round(noul, 3)},
            "mood": {"type": "score", "score": round(mood, 2)},
        },
    }


# ---------------- 排版 ----------------


def _mood_label(score):
    idx = max(0, min(len(MOOD_SCALE) - 1, int(round(score))))
    return MOOD_SCALE[idx]


def suggest(answers):
    """判断结果 → 一句人话建议。Jev 本身不生成文本，这句在本地拼。"""
    intent = (answers.get("intent") or {}).get("choice")
    urgent = (answers.get("urgent") or {}).get("noul")
    mood = (answers.get("mood") or {}).get("score")

    tips = []
    if intent == "task":
        tips.append("先应一声再动手，别让人干等")
    elif intent == "question":
        tips.append("能直接答就直接答，拿不准先问清背景")
    elif intent == "emotion":
        tips.append("先接住情绪，别急着讲道理")
    elif intent == "chat":
        tips.append("随便聊两句就行，不用当任务办")

    if isinstance(urgent, (int, float)) and urgent >= 0.5:
        tips.append("这条带急事，优先处理")
    if isinstance(mood, (int, float)) and mood < 1.5:
        tips.append("对方状态不太好，语气软一点")
    elif isinstance(mood, (int, float)) and mood >= 3.0:
        tips.append("对方心情不错，可以放开聊")

    return "；".join(tips) + "。"


def render(answers, source="mock"):
    intent = (answers.get("intent") or {}).get("choice")
    conf = (answers.get("intent") or {}).get("confidence")
    urgent = (answers.get("urgent") or {}).get("noul")
    mood = (answers.get("mood") or {}).get("score")

    head = [INTENT_LABEL.get(intent, "未知")]
    if isinstance(urgent, (int, float)):
        head.append("急" if urgent >= 0.5 else "不急")
    if isinstance(mood, (int, float)):
        head.append(f"情绪{_mood_label(mood)}")

    lines = ["【判断】" + " · ".join(head), ""]
    if intent:
        tail = f"（{conf:.2f}）" if isinstance(conf, (int, float)) else ""
        lines.append(f"· 意图　{INTENT_LABEL.get(intent, intent)}{tail}")
    if isinstance(urgent, (int, float)):
        lines.append(f"· 紧迫　{'是' if urgent >= 0.5 else '否'}（{urgent:.2f}）")
    if isinstance(mood, (int, float)):
        lines.append(f"· 情绪　{_mood_label(mood)}（{mood:.2f}）")

    lines += ["", "建议：" + suggest(answers)]

    if source == "mock":
        lines += ["", "（模拟判断 · 关键词版）"]
    return "\n".join(lines)


# ---------------- 机器人本体 ----------------


def show_qr(url):
    """二维码：终端打一份，同时存成图片自动打开，双保险。"""
    print("\n二维码链接（也能复制到浏览器打开）：")
    print(url)
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make()
        qr.print_ascii(invert=True)

        img_path = Path(__file__).with_name("qrcode.png")
        qrcode.make(url).save(img_path)
        print(f"\n二维码图片已保存：{img_path}")
        if hasattr(os, "startfile"):
            os.startfile(img_path)
    except Exception as exc:  # noqa: BLE001
        print(f"（二维码渲染失败：{exc}）")


def _demo_once(text):
    try:
        answers, source = decide(text)
        return render(answers, source)
    except Exception as exc:  # noqa: BLE001
        answers = _normalize(mock_answers(text))
        return render(answers, "mock") + f"\n\n（模型没调通，退回本地模拟：{exc}）"


def run_demo(argv):
    """本地试判断，不连微信。"""
    if argv:
        for text in argv:
            print(f"\n>>> {text}\n")
            print(_demo_once(text))
        return

    print(f"交互模式（后端：{_backend_name()}）：打一句话回车看判断，输入 q 退出。")
    while True:
        try:
            text = input("\n>>> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in ("q", "quit", "exit"):
            break
        if not text:
            continue
        print(_demo_once(text))


def main():
    from weixin_ilink import WeixinBot, login

    if Path(CRED_FILE).exists():
        print(f"用已保存的凭据登录：{CRED_FILE}")
        bot = WeixinBot(credentials_file=CRED_FILE)
    else:
        info = login(save_to=CRED_FILE, on_qrcode=show_qr)
        bot = WeixinBot(credentials=info)

    if TYPESAFE_KEY or OPENAI_KEY:
        name = _backend_name()
        try:
            decide("连通性测试")
            print(f"后端：{name} ✓ 调用正常")
        except Exception as exc:  # noqa: BLE001
            print(f"后端：{name}")
            print(f"  ⚠️ 试调用失败：{exc}")
            print("  → 收到消息时会自动退回本地模拟，先检查 key 有没有写错")
    else:
        print("后端：本地模拟（没配任何 key）")

    @bot.on_text
    def handle(msg):
        try:
            answers, source = decide(msg.text)
            reply = render(answers, source)
        except Exception as exc:  # noqa: BLE001
            answers = _normalize(mock_answers(msg.text))
            reply = render(answers, "mock")
            reply += f"\n\n（模型没调通，已退回本地模拟：{exc}）"
        msg.reply_text(reply)

    print("机器人已启动，微信里给它发消息试试（Ctrl-C 退出）")
    bot.run()


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--demo":
        run_demo(args[1:])
    else:
        main()
