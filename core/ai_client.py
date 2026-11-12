"""AI 适配层：一套接口接多家视觉大模型。

统一走 OpenAI 兼容的 /chat/completions 协议，各家差异只在三处：
  base_url、图片编码方式、是否需要鉴权头。

支持的 provider：
  qwen    阿里云通义千问 VL（DashScope 兼容模式）
  zhipu   智谱 GLM-4V
  openai  OpenAI 及任何兼容 OpenAI 协议的服务（豆包、Kimi、DeepSeek-VL 等）
  ollama  本地 Ollama（/v1 兼容端点）

所有异常都转成中文提示，避免用户看到一堆英文堆栈。
"""

from __future__ import annotations

import base64
import io
import json
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from PIL import Image

from .config import CATEGORIES, Config

# 上传给模型前把图压到这个宽度，能显著省 token
UPLOAD_MAX_WIDTH = 1024
UPLOAD_JPEG_QUALITY = 75

# 单帧分析只要几十个 token；每日总结要装 200 字中文加两组数组，400 必然截断
MAX_TOKENS_SINGLE = 400
MAX_TOKENS_SUMMARY = 1500

PURPOSE_FRAME = "画面识别"
PURPOSE_SUMMARY = "日终总结"
PURPOSE_TEST = "连接测试"

PROVIDERS: dict[str, dict[str, Any]] = {
    "qwen": {
        "label": "通义千问 VL（阿里云）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-vl-max-latest",
        "models": ["qwen-vl-max-latest", "qwen-vl-plus", "qwen2.5-vl-72b-instruct"],
        "image_style": "data_url",
        "need_key": True,
        "key_hint": "在阿里云百炼控制台创建 DashScope API Key（sk- 开头）",
    },
    "zhipu": {
        "label": "智谱 GLM-4V",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4v-flash",
        "models": ["glm-4v-flash", "glm-4v-plus", "glm-4v"],
        "image_style": "raw_base64",
        "need_key": True,
        "key_hint": "在智谱开放平台创建 API Key；glm-4v-flash 目前免费",
    },
    "openai": {
        "label": "OpenAI 兼容接口",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o-mini", "gpt-4o", "doubao-1.5-vision-pro", "moonshot-v1-8k-vision-preview"],
        "image_style": "data_url",
        "need_key": True,
        "key_hint": "填对应平台的 API Key；base_url 必须带 /v1 之类的版本前缀",
    },
    "ollama": {
        "label": "本地 Ollama",
        "base_url": "http://localhost:11434/v1",
        "default_model": "qwen2.5vl:7b",
        "models": ["qwen2.5vl:7b", "qwen2.5vl:3b", "llava:7b"],
        "image_style": "data_url",
        "need_key": False,
        "key_hint": "无需 Key，先执行 ollama pull qwen2.5vl:7b 拉模型",
    },
}


SYSTEM_PROMPT = """你是一个电脑使用行为分析助手。用户会给你一张电脑屏幕截图，以及当前前台窗口的进程名和窗口标题。你要判断用户此刻在做什么。

严格只输出一个 JSON 对象，不要输出任何解释、不要用 markdown 代码块包裹。

JSON 结构：
{
  "category": "工作|学习|娱乐|沟通|系统|其他",
  "activity": "活动类型，2到6个字",
  "detail": "一句话说清具体在做什么，不超过25个字",
  "focus_score": 1到5的整数,
  "is_productive": true 或 false
}

分类判定规则：
- 工作：写代码、写文档、做设计、处理表格、项目管理、查技术文档
- 学习：看课程视频、读论文、查学习资料、做题
- 娱乐：看视频、玩游戏、听音乐、刷短视频、逛论坛
- 沟通：微信QQ聊天、邮件、会议、协作工具
- 系统：桌面、文件管理器、系统设置、程序安装
- 其他：无法判断或上述都不符合

其他规则：
- focus_score 衡量专注程度：5=全神贯注做单一任务，3=正常，1=明显分心或无所事事
- is_productive 为 true 表示这件事对工作或学习有价值（娱乐、闲聊为 false）
- 结合窗口标题判断，标题里往往有文件名、项目名、网页标题，尽量体现在 detail 里
- 如果截图看不出内容（纯色、锁屏），category 填"其他"，activity 填"无法识别"
- activity 用简洁名词短语，如：编程开发、文档写作、网页浏览、视频观看、即时通讯、数据统计"""


SUMMARY_PROMPT = """你是一个时间管理分析助手。我会给你某一天电脑使用的时间段记录，请你归纳这一天的活动，并给出洞察。

严格只输出一个 JSON 对象，不要输出解释、不要用 markdown 包裹。

JSON 结构：
{
  "summary": "一段 120 到 200 字的中文总结，说明今天主要做了什么、时间怎么分配",
  "highlights": ["今天做得好的 2 到 3 件事，每条不超过 25 字"],
  "suggestions": ["针对性的改进建议 2 到 3 条，每条不超过 30 字，具体可执行"]
}

要求：
- 总结要具体，提到实际做的事（项目名、内容类型），不要空泛地说"你今天很努力"
- 建议要基于实际数据，比如某类活动占比过高就提出来
- 语气像朋友提醒，不要像领导批评"""


@dataclass
class AIResult:
    category: str = "其他"
    activity: str = ""
    detail: str = ""
    focus_score: int = 3
    is_productive: bool = False
    model: str = ""
    raw_text: str = ""
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "activity": self.activity,
            "detail": self.detail,
            "focus_score": self.focus_score,
            "is_productive": self.is_productive,
        }


class AIError(Exception):
    """AI 调用失败的统一异常，message 为中文可读提示。"""


class AIRateLimited(AIError):
    """触发了服务商限流。调用方可以退回队列重试，而不是把记录判死。"""


@dataclass
class AIClient:
    cfg: Config
    _session: requests.Session = field(default_factory=requests.Session, init=False)
    _outbound_ledger: Any = field(default=None, init=False, repr=False)
    _ledger_checked: bool = field(default=False, init=False, repr=False)
    _abort_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    def abort(self) -> None:
        """中止等待中的重试与新请求，并关闭连接池。"""
        self._abort_event.set()
        try:
            self._session.close()
        except Exception:
            pass

    def reset_abort(self) -> None:
        self._abort_event.clear()

    def _ledger(self) -> Any:
        if not self._ledger_checked:
            from .v2_runtime import get_outbound_ledger

            self._outbound_ledger = get_outbound_ledger(self.cfg)
            self._ledger_checked = True
        return self._outbound_ledger

    # ---------- 配置读取 ----------

    @property
    def provider(self) -> str:
        p = (self.cfg.get("ai.provider") or "qwen").strip().lower()
        return p if p in PROVIDERS else "qwen"

    @property
    def provider_meta(self) -> dict[str, Any]:
        return PROVIDERS[self.provider]

    @property
    def base_url(self) -> str:
        custom = (self.cfg.get("ai.base_url") or "").strip()
        return (custom or self.provider_meta["base_url"]).rstrip("/")

    @property
    def model(self) -> str:
        return (self.cfg.get("ai.model") or "").strip() or self.provider_meta["default_model"]

    @property
    def api_key(self) -> str:
        return (self.cfg.get("ai.api_key") or "").strip()

    def ready(self) -> tuple[bool, str]:
        """检查配置是否可用，返回 (是否就绪, 提示)。"""
        if self.provider_meta["need_key"] and not self.api_key:
            return False, f"还没填 {self.provider_meta['label']} 的 API Key"
        return True, ""

    # ---------- 单帧分析 ----------

    def analyze(
        self,
        image_path: str | Path,
        app_name: str = "",
        window_title: str = "",
        ts: datetime | None = None,
    ) -> AIResult:
        ok, msg = self.ready()
        if not ok:
            raise AIError(msg)

        started = time.time()
        b64 = _encode_image(image_path)
        ts = ts or datetime.now()

        hint = (
            f"前台进程：{app_name or '未知'}\n"
            f"窗口标题：{window_title or '（空）'}\n"
            f"截图时间：{ts.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        user_content = [
            {"type": "text", "text": hint},
            {"type": "image_url", "image_url": {"url": self._image_payload(b64)}},
        ]

        raw = self._chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            purpose=PURPOSE_FRAME,
            has_image=True,
        )
        data = _extract_json(raw)
        if not data:
            raise AIError(f"模型返回的不是有效 JSON：{raw[:120]}")

        result = AIResult(
            category=_normalize_category(data.get("category")),
            activity=str(data.get("activity") or "").strip()[:20],
            detail=str(data.get("detail") or "").strip()[:60],
            focus_score=_to_int(data.get("focus_score"), 3, 1, 5),
            is_productive=bool(data.get("is_productive")),
            model=self.model,
            raw_text=raw,
            duration_ms=int((time.time() - started) * 1000),
        )
        return result

    # ---------- 每日总结 ----------

    def summarize_day(self, digest: str) -> dict[str, Any]:
        ok, msg = self.ready()
        if not ok:
            raise AIError(msg)

        raw = self._chat(
            [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": digest},
            ],
            max_tokens=MAX_TOKENS_SUMMARY,
            expect_json=True,
            purpose=PURPOSE_SUMMARY,
        )
        data = _extract_json(raw)
        if not data:
            raise AIError(_bad_json_hint(raw))
        if not str(data.get("summary") or "").strip():
            raise AIError("AI 这次没给出总结正文（可能被截断或触发了内容审核），再点一次「重新生成」试试")

        def _as_list(value: Any, limit: int) -> list[str]:
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list):
                return []
            return [str(v).strip() for v in value if str(v).strip()][:limit]

        return {
            "summary": str(data.get("summary") or "").strip(),
            "highlights": _as_list(data.get("highlights"), 3),
            "suggestions": _as_list(data.get("suggestions"), 3),
            "model": self.model,
        }

    # ---------- 连接测试 ----------

    def test_connection(self) -> str:
        """发一条极小的纯文本请求验证配置，返回成功提示。"""
        ok, msg = self.ready()
        if not ok:
            raise AIError(msg)
        reply = self._chat(
            [{"role": "user", "content": "只回复两个字：正常"}],
            max_tokens=16,
            purpose=PURPOSE_TEST,
        )
        return (reply or "").strip()[:40] or "连接成功"

    # ---------- 底层 HTTP ----------

    def _image_payload(self, b64: str) -> str:
        if self.provider_meta["image_style"] == "raw_base64":
            return b64
        return f"data:image/jpeg;base64,{b64}"

    def _chat(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int = MAX_TOKENS_SINGLE,
        expect_json: bool = False,
        purpose: str = PURPOSE_FRAME,
        has_image: bool = False,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        timeout = int(self.cfg.get("ai.timeout", 90) or 90)
        ledger = self._ledger()
        if ledger is None:
            from .v2_runtime import enforcement_enabled

            if enforcement_enabled(self.cfg):
                raise AIError("外发拦截已开启，但台账无法初始化；为避免无记录外发，本次请求已停止")
        elif not ledger.allow(purpose):
            raise AIError(f"已停止此类外发：{purpose}")
        # 关闭台账时不重复序列化含 base64 图片的请求体，避免无意义开销。
        request_bytes = (
            len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            if ledger is not None
            else 0
        )

        last_error = ""
        rate_limited = False
        connect_timeout = max(2, min(10, timeout))
        for attempt in range(3):
            if self._abort_event.is_set():
                raise AIError("请求已取消")
            if attempt:
                delay = 2 if attempt == 1 else 5
                if self._abort_event.wait(delay):
                    raise AIError("请求已取消")
            try:
                # 记的是“发起了请求”，不是“请求成功”，重试也会如实计数。
                if ledger is not None:
                    recorded = ledger.record(
                        purpose=purpose,
                        provider=self.provider,
                        model=self.model,
                        byte_count=request_bytes,
                        has_thumb=has_image,
                    )
                    if ledger.enforce and not recorded:
                        raise AIError("外发台账写入失败；为防止无记录外发，本次请求已停止")
                resp = self._session.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=(connect_timeout, timeout),
                )
            except requests.Timeout:
                last_error = f"请求超时（{timeout}秒），可能是网络太慢或模型响应卡住"
                continue
            except requests.ConnectionError:
                if self._abort_event.is_set():
                    raise AIError("请求已取消")
                if self.provider == "ollama":
                    last_error = "连不上本地 Ollama，确认它已经启动（ollama serve）"
                else:
                    last_error = "网络连接失败，检查网络或代理设置"
                continue
            except requests.RequestException as exc:
                if self._abort_event.is_set():
                    raise AIError("请求已取消")
                last_error = f"请求异常：{exc.__class__.__name__}"
                continue

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    choice = data["choices"][0]
                    content = (choice.get("message") or {}).get("content") or ""
                    finish = str(choice.get("finish_reason") or "")
                except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                    last_error = "返回内容格式异常，无法解析"
                    continue

                # 输出被长度截断，且拼不出 JSON——这种错误必须说人话，
                # 否则用户只会看到「不是有效 JSON」，根本不知道是 token 不够
                if expect_json and finish == "length" and _extract_json(content) is None:
                    raise AIError(
                        f"模型的回答被截断了（达到 {max_tokens} token 上限），这次内容不完整。"
                        "再点一次「重新生成」，或者把采集间隔调大一些让记录少一点"
                    )
                return content

            detail = _http_error_text(resp)
            if resp.status_code in (401, 403):
                raise AIError(f"API Key 无效或无权限：{detail}")
            if resp.status_code == 404:
                raise AIError(f"模型名或接口地址不对：{detail}")
            if resp.status_code == 429:
                rate_limited = True
                last_error = "触发了服务商限流，请等一会儿再试"
                continue
            if 400 <= resp.status_code < 500:
                raise AIError(f"请求被拒绝（{resp.status_code}）：{detail}")
            last_error = f"服务端错误 {resp.status_code}：{detail}"

        if rate_limited:
            raise AIRateLimited(last_error or "触发了服务商限流，请等一会儿再试")
        raise AIError(last_error or "调用失败，原因不明")


# ---------- 工具函数 ----------


def _encode_image(image_path: str | Path) -> str:
    """读图、压到 1024 宽、转 JPEG、base64。"""
    path = Path(image_path)
    if not path.exists():
        raise AIError(f"截图文件不存在：{path.name}")
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            if im.width > UPLOAD_MAX_WIDTH:
                ratio = UPLOAD_MAX_WIDTH / im.width
                im = im.resize(
                    (UPLOAD_MAX_WIDTH, max(1, int(im.height * ratio))),
                    Image.Resampling.LANCZOS,
                )
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=UPLOAD_JPEG_QUALITY, optimize=True)
    except OSError as exc:
        raise AIError(f"截图读取失败：{exc}") from exc
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _extract_json(text: str) -> dict[str, Any] | None:
    """从模型输出里抠出 JSON，容忍 markdown 代码块和前后废话。"""
    if not text:
        return None
    cleaned = text.strip()
    # 去掉 ```json ... ``` 包裹
    fence = re.search(r"```(?:json)?\s*(.+?)```", cleaned, re.S)
    if fence:
        cleaned = fence.group(1).strip()

    try:
        data = json.loads(cleaned)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start == -1:
        return None

    end = cleaned.rfind("}")
    candidates: list[str] = []
    if end > start:
        candidates.append(cleaned[start : end + 1])
    candidates.append(cleaned[start:])  # 截断场景：根本没有闭合的 }

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            data = _close_truncated_json(candidate)
        if isinstance(data, dict):
            return data
    return None


def _close_truncated_json(text: str) -> dict[str, Any] | None:
    """给被截断的 JSON 补上引号和括号，尽量捞出已经写完的部分。

    只做一轮尝试，修不好就返回 None——绝不猜内容。
    """
    stack: list[str] = []
    in_str = False
    escape = False
    for ch in text:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]" and stack:
            stack.pop()

    repaired = text
    if in_str:
        if repaired.endswith("\\"):
            repaired = repaired[:-1]
        repaired += '"'
    repaired = repaired.rstrip().rstrip(",")
    repaired += "".join(reversed(stack))
    try:
        data = json.loads(repaired)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _bad_json_hint(text: str) -> str:
    """把模型原文的首尾都带上，截断和模型胡说一眼能区分。"""
    body = (text or "").strip()
    if not body:
        return "模型返回了空内容（可能被截断或触发内容审核），稍后重新生成一次"
    head = body[:80].replace("\n", " ")
    tail = body[-80:].replace("\n", " ") if len(body) > 160 else ""
    preview = f"{head} … {tail}" if tail else head
    return f"模型返回的不是有效 JSON，原文首尾：{preview}"


def _normalize_category(value: Any) -> str:
    text = str(value or "").strip()
    for cat in CATEGORIES:
        if cat in text:
            return cat
    # 模型偶尔给英文，做个兜底映射
    mapping = {
        "work": "工作",
        "study": "学习",
        "learn": "学习",
        "entertainment": "娱乐",
        "communication": "沟通",
        "system": "系统",
        "other": "其他",
    }
    low = text.lower()
    for key, cat in mapping.items():
        if key in low:
            return cat
    return "其他"


def _to_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(float(value))))
    except (TypeError, ValueError):
        return default


def _http_error_text(resp: requests.Response) -> str:
    """从各家错误响应里抽出可读信息。"""
    try:
        data = resp.json()
    except ValueError:
        return (resp.text or "")[:160] or resp.reason
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or "")[:160]
        if isinstance(err, str):
            return err[:160]
        for key in ("message", "msg", "detail"):
            if data.get(key):
                return str(data[key])[:160]
    return str(data)[:160]
