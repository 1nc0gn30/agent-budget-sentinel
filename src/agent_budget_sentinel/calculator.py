"""Cost calculation and heuristic token estimation engine.

100% Python Standard Library — Zero External Dependencies.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class ModelPricing:
    """Pricing rates per 1,000,000 tokens in USD."""
    model_id: str
    input_rate: float
    output_rate: float
    family: str


# Comprehensive pricing table (Rates per 1M tokens)
MODEL_PRICING: Dict[str, ModelPricing] = {
    # OpenAI
    "gpt-4o": ModelPricing("gpt-4o", 2.50, 10.00, "openai"),
    "gpt-4o-2024-08-06": ModelPricing("gpt-4o-2024-08-06", 2.50, 10.00, "openai"),
    "gpt-4o-mini": ModelPricing("gpt-4o-mini", 0.15, 0.60, "openai"),
    "gpt-4o-mini-2024-07-18": ModelPricing("gpt-4o-mini-2024-07-18", 0.15, 0.60, "openai"),
    "o1": ModelPricing("o1", 15.00, 60.00, "openai"),
    "o1-preview": ModelPricing("o1-preview", 15.00, 60.00, "openai"),
    "o1-mini": ModelPricing("o1-mini", 3.00, 12.00, "openai"),
    "gpt-4-turbo": ModelPricing("gpt-4-turbo", 10.00, 30.00, "openai"),
    "gpt-3.5-turbo": ModelPricing("gpt-3.5-turbo", 0.50, 1.50, "openai"),
    
    # Anthropic
    "claude-3-5-sonnet-20241022": ModelPricing("claude-3-5-sonnet-20241022", 3.00, 15.00, "anthropic"),
    "claude-3-5-sonnet-20240620": ModelPricing("claude-3-5-sonnet-20240620", 3.00, 15.00, "anthropic"),
    "claude-3-5-sonnet": ModelPricing("claude-3-5-sonnet", 3.00, 15.00, "anthropic"),
    "claude-3-5-haiku-20241022": ModelPricing("claude-3-5-haiku-20241022", 0.80, 4.00, "anthropic"),
    "claude-3-5-haiku": ModelPricing("claude-3-5-haiku", 0.80, 4.00, "anthropic"),
    "claude-3-opus-20240229": ModelPricing("claude-3-opus-20240229", 15.00, 75.00, "anthropic"),
    "claude-3-opus": ModelPricing("claude-3-opus", 15.00, 75.00, "anthropic"),
    "claude-3-haiku": ModelPricing("claude-3-haiku", 0.25, 1.25, "anthropic"),
    
    # Google Gemini
    "gemini-1.5-pro": ModelPricing("gemini-1.5-pro", 1.25, 5.00, "google"),
    "gemini-1.5-flash": ModelPricing("gemini-1.5-flash", 0.075, 0.30, "google"),
    "gemini-2.0-flash": ModelPricing("gemini-2.0-flash", 0.10, 0.40, "google"),
    "gemini-2.0-flash-exp": ModelPricing("gemini-2.0-flash-exp", 0.10, 0.40, "google"),
    
    # DeepSeek
    "deepseek-chat": ModelPricing("deepseek-chat", 0.14, 0.28, "deepseek"),
    "deepseek-v3": ModelPricing("deepseek-v3", 0.14, 0.28, "deepseek"),
    "deepseek-reasoner": ModelPricing("deepseek-reasoner", 0.55, 2.19, "deepseek"),
    "deepseek-r1": ModelPricing("deepseek-r1", 0.55, 2.19, "deepseek"),
    
    # Meta / Open Source
    "meta-llama/llama-3.3-70b-instruct": ModelPricing("meta-llama/llama-3.3-70b-instruct", 0.40, 0.40, "open-weights"),
    "meta-llama/llama-3.1-8b-instruct": ModelPricing("meta-llama/llama-3.1-8b-instruct", 0.08, 0.08, "open-weights"),
    "meta-llama/llama-3.1-405b-instruct": ModelPricing("meta-llama/llama-3.1-405b-instruct", 2.00, 2.00, "open-weights"),
    
    # Fallback default
    "default": ModelPricing("default", 2.00, 8.00, "general"),
}


class CostResult(dict):
    """Dictionary holding cost breakdown that also evaluates to float."""
    @property
    def total_cost(self) -> float:
        return self["total_cost"]

    def __float__(self) -> float:
        return float(self["total_cost"])


class CostCalculator:
    """Calculates LLM token counts and dollar costs with zero external dependencies."""

    @staticmethod
    def get_pricing(model_name: str) -> ModelPricing:
        """Resolve model pricing with robust prefix and fuzzy matching."""
        if not model_name:
            return MODEL_PRICING["default"]
        
        normalized = model_name.strip().lower()
        if normalized in MODEL_PRICING:
            return MODEL_PRICING[normalized]
        
        # Check sub-string matches
        for key, pricing in MODEL_PRICING.items():
            if key != "default" and (key in normalized or normalized in key):
                return pricing
                
        # Family heuristics
        if "deepseek-reasoner" in normalized or "deepseek-r1" in normalized:
            return MODEL_PRICING["deepseek-reasoner"]
        if "deepseek" in normalized:
            return MODEL_PRICING["deepseek-chat"]
        if "gpt-4o-mini" in normalized:
            return MODEL_PRICING["gpt-4o-mini"]
        if "gpt-4o" in normalized:
            return MODEL_PRICING["gpt-4o"]
        if "o1-mini" in normalized:
            return MODEL_PRICING["o1-mini"]
        if "o1" in normalized:
            return MODEL_PRICING["o1"]
        if "haiku" in normalized:
            return MODEL_PRICING["claude-3-5-haiku"]
        if "sonnet" in normalized:
            return MODEL_PRICING["claude-3-5-sonnet"]
        if "opus" in normalized:
            return MODEL_PRICING["claude-3-opus"]
        if "claude" in normalized:
            return MODEL_PRICING["claude-3-5-sonnet"]
        if "flash" in normalized:
            return MODEL_PRICING["gemini-1.5-flash"]
        if "gemini" in normalized:
            return MODEL_PRICING["gemini-1.5-pro"]
            
        return MODEL_PRICING["default"]

    @staticmethod
    def estimate_text_tokens(text: str) -> int:
        """Heuristic BPE token estimator based on whitespace, punctuation, and character length.
        
        Averages ~4 characters per token for English text and code.
        """
        if not text:
            return 0
        
        char_count = len(text)
        punct_count = len(re.findall(r"[\{\}\[\]\(\)\<\>\:\,\.\;\\\"\'\=\+\-\_\/\*\&\^%\$#@!~`|]", text))
        
        # Blend character length and punctuation
        est = (char_count / 3.8) + (punct_count * 0.25)
        return max(1, int(round(est)))

    @classmethod
    def estimate_payload_tokens(cls, payload: Dict[str, Any]) -> int:
        """Estimate total prompt tokens from standard OpenAI or Anthropic payload."""
        if not isinstance(payload, dict):
            return 0
        
        total = 0
        
        # System prompt
        if "system" in payload:
            sys_val = payload["system"]
            if isinstance(sys_val, str):
                total += cls.estimate_text_tokens(sys_val)
            elif isinstance(sys_val, list):
                for item in sys_val:
                    if isinstance(item, dict) and "text" in item:
                        total += cls.estimate_text_tokens(item["text"])
                    elif isinstance(item, str):
                        total += cls.estimate_text_tokens(item)

        # Messages list (OpenAI / Anthropic format)
        messages = payload.get("messages", [])
        if isinstance(messages, list):
            for msg in messages:
                total += 3  # Per-message overhead (role, formatting tokens)
                if isinstance(msg, dict):
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        total += cls.estimate_text_tokens(content)
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict):
                                if "text" in block:
                                    total += cls.estimate_text_tokens(block["text"])
                                elif "image_url" in block:
                                    total += 85  # Low-res tile heuristic
                    # Tool calls / Function calls
                    if "tool_calls" in msg and isinstance(msg["tool_calls"], list):
                        for tc in msg["tool_calls"]:
                            if isinstance(tc, dict) and "function" in tc:
                                fn = tc["function"]
                                total += cls.estimate_text_tokens(fn.get("name", ""))
                                total += cls.estimate_text_tokens(fn.get("arguments", ""))

        # Prompt string (legacy completions)
        if "prompt" in payload:
            p_val = payload["prompt"]
            if isinstance(p_val, str):
                total += cls.estimate_text_tokens(p_val)
            elif isinstance(p_val, list):
                for p in p_val:
                    if isinstance(p, str):
                        total += cls.estimate_text_tokens(p)

        # Tools / Functions definitions
        tools = payload.get("tools", [])
        if isinstance(tools, list):
            for tool in tools:
                if isinstance(tool, dict):
                    total += cls.estimate_text_tokens(json.dumps(tool))

        return max(1, total)

    @classmethod
    def calculate_cost(
        cls,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int = 0
    ) -> CostResult:
        """Return rich dictionary with breakdown and total cost."""
        pricing = cls.get_pricing(model_name)
        in_cost = (prompt_tokens * pricing.input_rate) / 1_000_000.0
        out_cost = (completion_tokens * pricing.output_rate) / 1_000_000.0
        total = round(in_cost + out_cost, 6)
        return CostResult({
            "model": model_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "input_rate_1m": pricing.input_rate,
            "output_rate_1m": pricing.output_rate,
            "input_cost": round(in_cost, 6),
            "output_cost": round(out_cost, 6),
            "total_cost": total,
        })

    @classmethod
    def calculate_cost_details(
        cls,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int = 0
    ) -> CostResult:
        """Alias returning rich dictionary with breakdown and total cost."""
        return cls.calculate_cost(model_name, prompt_tokens, completion_tokens)

    @classmethod
    def calculate_cost_usd(
        cls,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int = 0
    ) -> float:
        """Calculate total dollar cost in USD as a raw float."""
        pricing = cls.get_pricing(model_name)
        in_cost = (prompt_tokens * pricing.input_rate) / 1_000_000.0
        out_cost = (completion_tokens * pricing.output_rate) / 1_000_000.0
        return round(in_cost + out_cost, 6)

    @staticmethod
    def extract_actual_usage(response_data: Any) -> Optional[Tuple[int, int]]:
        """Extract (prompt_tokens, completion_tokens) from upstream LLM response."""
        if not isinstance(response_data, dict):
            return None
            
        # OpenAI style: { "usage": { "prompt_tokens": 120, "completion_tokens": 45 } }
        if "usage" in response_data and isinstance(response_data["usage"], dict):
            u = response_data["usage"]
            prompt_tokens = u.get("prompt_tokens") or u.get("input_tokens") or 0
            completion_tokens = u.get("completion_tokens") or u.get("output_tokens") or 0
            if prompt_tokens > 0 or completion_tokens > 0:
                return (int(prompt_tokens), int(completion_tokens))
                
        # Anthropic style top-level usage
        if "input_tokens" in response_data and "output_tokens" in response_data:
            return (int(response_data["input_tokens"]), int(response_data["output_tokens"]))
            
        return None


# Module-level aliases
get_pricing = CostCalculator.get_pricing
estimate_text_tokens = CostCalculator.estimate_text_tokens
estimate_tokens_from_text = CostCalculator.estimate_text_tokens
estimate_payload_tokens = CostCalculator.estimate_payload_tokens
calculate_cost = CostCalculator.calculate_cost
calculate_cost_usd = CostCalculator.calculate_cost_usd
extract_actual_usage = CostCalculator.extract_actual_usage
