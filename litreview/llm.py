# -*- coding: utf-8 -*-
"""LLM 客户端：OpenAI 兼容协议 / Mock，带指数退避重试。"""
from __future__ import annotations

import hashlib
import json
import os
import time

RETRY_DELAYS = [2, 5, 10]  # 秒


class LLMClient:
    """OpenAI 兼容接口客户端（火山方Ark/DeepSeek/OpenAI/Qwen/GLM 等均适用）。

    structured: auto（默认）= 优先 response_format JSON 模式，失败由调用方回退文本；
                text = 仅用文本协议。
    """

    def __init__(self, spec: dict):
        self.provider = spec["provider"]
        self.model = spec["model"]
        self.base_url = spec.get("base_url")
        key = os.environ.get(spec.get("api_key_env", ""), "")
        if not key:
            raise RuntimeError(f"环境变量 {spec.get('api_key_env')} 未设置，无法调用 {self.model}")
        self.structured = spec.get("structured", "auto")
        from openai import OpenAI
        self._client = OpenAI(base_url=self.base_url, api_key=key, timeout=180)

    def complete(self, system: str, user: str) -> str:
        last_err = None
        for delay in [0] + RETRY_DELAYS:
            if delay:
                time.sleep(delay)
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    temperature=0,
                )
                return resp.choices[0].message.content or ""
            except Exception as e:  # 限流/网络错误，退避重试
                last_err = e
        raise RuntimeError(f"LLM 调用失败（{self.model}）: {last_err}")

    def complete_json(self, system: str, user: str) -> dict:
        """response_format JSON 模式，单次尝试；失败抛异常，由调用方回退文本路径。
        不做退避重试：参数不支持/返回非 JSON 时快速失败，网络类错误交给文本路径的重试。"""
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content or "")
        if not isinstance(data, dict):
            raise ValueError("模型输出不是 JSON 对象")
        return data


class MockAgent:
    """确定性 Mock：模拟评审/仲裁输出，按 prompt 哈希制造约 1/3 分歧，用于无 key 验证流程。

    role 取配置键: reviewer_1 / reviewer_2 / arbiter。
    通过环境变量 LITREVIEW_MOCK_FAIL=1 可让 reviewer_2 模拟解析失败输出。
    """

    def __init__(self, spec: dict):
        self.model = spec.get("model", "mock")
        self.role = spec.get("role", "reviewer_1")
        self.structured = "text"  # Mock 始终走文本协议，用于验证文本解析路径

    def complete(self, system: str, user: str) -> str:
        fail = (os.environ.get("LITREVIEW_MOCK_FAIL") == "1"
                and self.role == "reviewer_2")
        if fail:
            return "抱歉，我无法按照指定格式回答。"
        # 从 prompt 中提取判据 id（形如 [T1] 的行）
        import re
        cids = re.findall(r"^\[(\w+)\]", user, re.M)
        h = int(hashlib.md5(user[:4000].encode()).hexdigest(), 16)
        overall = "Yes" if h % 3 else "No"
        if self.role == "arbiter":
            # 仲裁输出 Final 格式；裁定沿用哈希结果（验证解析与流程用）
            lines = [f"Final {cid}: {overall}" for cid in cids]
            lines.append(f"Final Overall: {overall}")
            lines.append("Disagreement Root: Mock arbitration analysis.")
            return "\n".join(lines)
        # reviewer_2 在部分记录上整体判定与 reviewer_1 相反，制造分歧触发仲裁
        my_overall = overall
        if self.role == "reviewer_2" and h % 3 == 1:
            my_overall = "No" if overall == "Yes" else "Yes"
        lines = []
        for cid in cids:
            lines.append(f"Response {cid}: {my_overall}")
            lines.append(f"Reasoning {cid}: Mock reasoning for {cid} based on title/abstract.")
        lines.append(f"Overall Response: {my_overall}")
        lines.append("Reasoning: Mock overall reasoning.")
        return "\n".join(lines)


def make_agent(spec: dict) -> LLMClient | MockAgent:
    """spec.provider == 'mock' 时返回 MockAgent；spec 里可带 role 供 Mock 使用。"""
    if spec.get("provider") == "mock":
        return MockAgent(spec)
    return LLMClient(spec)
