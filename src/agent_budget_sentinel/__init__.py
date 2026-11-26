"""agent-budget-sentinel

Autonomous zero-dependency spending guardrail and token cost circuit breaker for AI agents.
Engineered by 1nc0gn30 (@1nc0gn30) • NullAI Platform.
"""

from .calculator import CostCalculator, ModelPricing, MODEL_PRICING
from .bpe_tokenizer import BPETokenizer, count_tokens
from .breaker import CircuitBreaker, BreakerState, BudgetPolicy
from .storage import BudgetStorage, TransactionRecord
from .net_guard import is_local_origin, validate_upstream_url
from .proxy import BudgetProxyServer, BudgetProxyHandler
from .server import BudgetWebServer, WebDeckHandler
from .mcp_server import handle_jsonrpc_message, run_stdio_mcp

__version__ = "2.6.0"
VERSION = __version__
__all__ = [
    "__version__",
    "VERSION",
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
    "is_local_origin",
    "validate_upstream_url",
    "BudgetProxyServer",
    "BudgetProxyHandler",
    "BudgetWebServer",
    "WebDeckHandler",
    "handle_jsonrpc_message",
    "run_stdio_mcp",
]
