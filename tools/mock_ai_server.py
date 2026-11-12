"""本地 mock AI 服务，用来在没有真实 API Key 时跑通整条链路。

模拟 OpenAI 兼容的 /v1/chat/completions 接口，按窗口标题返回不同的分析结果。

单独跑：
    .venv/Scripts/python.exe tools/mock_ai_server.py
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 窗口标题关键词 -> 分析结果，让 mock 结果看起来像真的
RULES = [
    ("Code.exe", "工作", "编程开发", "在 VS Code 里写代码", 5, True),
    ("chrome", "学习", "查阅资料", "在浏览器里查技术文档", 4, True),
    ("微信", "沟通", "即时通讯", "在微信上回复消息", 3, False),
    ("Word", "工作", "文档写作", "在 Word 里写文档", 4, True),
    ("B站", "娱乐", "视频观看", "在B站看视频", 2, False),
    ("哔哩哔哩", "娱乐", "视频观看", "在B站看视频", 2, False),
    ("Terminal", "工作", "程序调试", "在终端执行命令", 4, True),
    ("explorer", "系统", "文件管理", "在整理文件", 3, True),
]

DEFAULT = ("其他", "无法识别", "看不清在做什么", 3, False)


SUMMARY_MARKERS = ("时间管理分析助手", "highlights", "suggestions")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass  # 静音

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}

        # 总结请求返回总结格式，单帧分析请求返回分析格式
        if any(marker in json.dumps(payload, ensure_ascii=False) for marker in SUMMARY_MARKERS):
            content = json.dumps(
                {
                    "summary": "今天主要在写代码和查资料，上午专注度比较高，"
                    "下午有一段较长的视频时间。整体节奏偏稳，有效产出集中在上午。",
                    "highlights": ["连续 1 小时专注写代码", "当天有 3 个完整的专注时段"],
                    "suggestions": ["下午的视频时间可以拆成两段，中间插入一次短休息"],
                },
                ensure_ascii=False,
            )
        else:
            content = json.dumps(self._analyze(payload), ensure_ascii=False)

        body = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": content}}]},
            ensure_ascii=False,
        ).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _analyze(self, payload: dict) -> dict:
        """只根据「前台进程 / 窗口标题」两行做匹配，避免命中提示词里的示例词。"""
        hint = ""
        for msg in payload.get("messages", []):
            content = msg.get("content")
            if isinstance(content, str) and "前台进程" in content:
                hint = content
                break
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text = part.get("text", "")
                        if "前台进程" in text:
                            hint = text
                            break

        category, activity, detail, focus, productive = DEFAULT
        for keyword, cat, act, det, foc, prod in RULES:
            if keyword.lower() in hint.lower():
                category, activity, detail, focus, productive = cat, act, det, foc, prod
                break

        return {
            "category": category,
            "activity": activity,
            "detail": detail,
            "focus_score": focus,
            "is_productive": productive,
        }


def start(port: int = 18080) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    srv = start()
    print("Mock AI 服务已启动：http://127.0.0.1:18080/v1")
    print("把设置里的「接口地址」填成上面这个，「API Key」随便填，就能跑通全流程。")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.shutdown()
