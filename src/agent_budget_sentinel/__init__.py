"""agent-budget-sentinel

Autonomous zero-dependency spending guardrail and token cost circuit breaker for AI agents.
Engineered by Neal Frazier Tech (@1nc0gn30) • NullAI Platform.
"""

from .calculator import CostCalculator, ModelPricing, MODEL_PRICING
from .bpe_tokenizer import BPETokenizer, count_tokens
from .breaker import CircuitBreaker, BreakerState, BudgetPolicy
from .storage import BudgetStorage, TransactionRecord
from .proxy import BudgetProxyServer, BudgetProxyHandler
from .server import BudgetWebServer, WebDeckHandler

__version__ = "1.0.0"
__all__ = [
    "CostCalculator",
    "BPETokenizer",
    "count_tokens",
    "ModelPricing",
    "MODEL_PRICING",
    "CircuitBreaker",
    "BreakerState",
    "BudgetPolicy",
    "BudgetStorage",
    "TransactionRecord",
    "BudgetProxyServer",
    "BudgetProxyHandler",
    "BudgetWebServer",
    "WebDeckHandler",
]
