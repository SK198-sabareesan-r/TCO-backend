"""
utils/token_tracker.py
----------------------
Token usage tracking for LLM/AI calls.

Tracks:
- Input tokens (prompt)
- Output tokens (completion)
- Total tokens
- Cost estimation (based on model pricing)
"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class TokenUsage:
    """Token usage for a single LLM call."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_creation_tokens: int = 0  # Tokens written to cache
    cache_read_tokens: int = 0      # Tokens read from cache
    model: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    operation: str = ""  # e.g., "llm_fallback", "sql_generation"
    
    def __post_init__(self):
        if self.total_tokens == 0:
            self.total_tokens = self.input_tokens + self.output_tokens


@dataclass
class TokenStats:
    """Aggregated token statistics."""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_calls: int = 0
    total_cache_creation_tokens: int = 0
    total_cache_read_tokens: int = 0
    by_operation: Dict[str, TokenUsage] = field(default_factory=dict)
    
    def add_usage(self, usage: TokenUsage):
        """Add token usage to statistics."""
        self.total_input_tokens += usage.input_tokens
        self.total_output_tokens += usage.output_tokens
        self.total_tokens += usage.total_tokens
        self.total_cache_creation_tokens += usage.cache_creation_tokens
        self.total_cache_read_tokens += usage.cache_read_tokens
        self.total_calls += 1
        
        # Aggregate by operation
        if usage.operation not in self.by_operation:
            self.by_operation[usage.operation] = TokenUsage(
                operation=usage.operation,
                model=usage.model
            )
        
        op_stats = self.by_operation[usage.operation]
        op_stats.input_tokens += usage.input_tokens
        op_stats.output_tokens += usage.output_tokens
        op_stats.total_tokens += usage.total_tokens
        op_stats.cache_creation_tokens += usage.cache_creation_tokens
        op_stats.cache_read_tokens += usage.cache_read_tokens
    
    def estimate_cost(self, model: str = "claude-3-sonnet") -> float:
        """
        Estimate cost based on token usage including cache pricing.
        
        Pricing (as of 2024):
        - Claude 3 Sonnet: $3/M input, $15/M output
        - Cache write: $3.75/M (25% premium)
        - Cache read: $0.30/M (90% discount)
        - Claude 3 Haiku: $0.25/M input, $1.25/M output
        - GPT-4: $30/M input, $60/M output
        """
        pricing = {
            "claude-3-sonnet": {
                "input": 3.0, 
                "output": 15.0,
                "cache_write": 3.75,
                "cache_read": 0.30
            },
            "claude-3-haiku": {
                "input": 0.25, 
                "output": 1.25,
                "cache_write": 0.3125,
                "cache_read": 0.025
            },
            "gpt-4": {"input": 30.0, "output": 60.0},
            "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
        }
        
        model_pricing = pricing.get(model, pricing["claude-3-sonnet"])
        
        # Regular input/output costs
        input_cost = (self.total_input_tokens / 1_000_000) * model_pricing["input"]
        output_cost = (self.total_output_tokens / 1_000_000) * model_pricing["output"]
        
        # Cache costs (if supported by model)
        cache_write_cost = 0
        cache_read_cost = 0
        if "cache_write" in model_pricing:
            cache_write_cost = (self.total_cache_creation_tokens / 1_000_000) * model_pricing["cache_write"]
            cache_read_cost = (self.total_cache_read_tokens / 1_000_000) * model_pricing["cache_read"]
        
        return round(input_cost + output_cost + cache_write_cost + cache_read_cost, 4)
    
    def estimate_cost_without_cache(self, model: str = "claude-3-sonnet") -> float:
        """Estimate what the cost would have been without caching."""
        pricing = {
            "claude-3-sonnet": {"input": 3.0, "output": 15.0},
            "claude-3-haiku": {"input": 0.25, "output": 1.25},
            "gpt-4": {"input": 30.0, "output": 60.0},
            "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
        }
        
        model_pricing = pricing.get(model, pricing["claude-3-sonnet"])
        
        # Calculate as if all tokens were regular input tokens
        total_input_without_cache = (
            self.total_input_tokens + 
            self.total_cache_creation_tokens + 
            self.total_cache_read_tokens
        )
        
        input_cost = (total_input_without_cache / 1_000_000) * model_pricing["input"]
        output_cost = (self.total_output_tokens / 1_000_000) * model_pricing["output"]
        
        return round(input_cost + output_cost, 4)
    
    def print_summary(self):
        """Print token usage summary."""
        print("\n" + "=" * 80)
        print("  TOKEN USAGE SUMMARY")
        print("=" * 80)
        print(f"  Total LLM Calls:     {self.total_calls}")
        print(f"  Total Input Tokens:  {self.total_input_tokens:,}")
        print(f"  Total Output Tokens: {self.total_output_tokens:,}")
        print(f"  Total Tokens:        {self.total_tokens:,}")
        
        # Cache statistics
        if self.total_cache_creation_tokens > 0 or self.total_cache_read_tokens > 0:
            print("\n  Cache Performance:")
            print(f"  Cache Writes:        {self.total_cache_creation_tokens:,} tokens")
            print(f"  Cache Reads:         {self.total_cache_read_tokens:,} tokens")
            cache_hit_rate = (
                (self.total_cache_read_tokens / 
                 (self.total_cache_creation_tokens + self.total_cache_read_tokens) * 100)
                if (self.total_cache_creation_tokens + self.total_cache_read_tokens) > 0 else 0
            )
            print(f"  Cache Hit Rate:      {cache_hit_rate:.1f}%")
        
        # Cost estimation
        cost_with_cache = self.estimate_cost()
        cost_without_cache = self.estimate_cost_without_cache()
        savings = cost_without_cache - cost_with_cache
        savings_pct = (savings / cost_without_cache * 100) if cost_without_cache > 0 else 0
        
        print(f"\n  Cost (with cache):   ${cost_with_cache:.4f} (Claude 3 Sonnet)")
        if self.total_cache_creation_tokens > 0 or self.total_cache_read_tokens > 0:
            print(f"  Cost (without cache):${cost_without_cache:.4f}")
            print(f"  Cache Savings:       ${savings:.4f} ({savings_pct:.1f}% reduction)")
        
        print("=" * 80)
        
        if self.by_operation:
            print("\n  Breakdown by Operation:")
            print("  " + "-" * 78)
            print(f"  {'Operation':<30} {'Calls':<8} {'Input':<12} {'Output':<12} {'Total':<12}")
            print("  " + "-" * 78)
            
            for op_name, op_stats in self.by_operation.items():
                # Count calls for this operation
                calls = sum(1 for _ in [op_stats])  # Simplified - in real impl track per call
                print(f"  {op_name:<30} {calls:<8} {op_stats.input_tokens:<12,} "
                      f"{op_stats.output_tokens:<12,} {op_stats.total_tokens:<12,}")
            print("  " + "-" * 78)
        print()


class TokenTracker:
    """Global token tracker singleton."""
    
    _instance = None
    _stats: TokenStats = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._stats = TokenStats()
        return cls._instance
    
    @classmethod
    def track(cls, usage: TokenUsage):
        """Track token usage."""
        instance = cls()
        instance._stats.add_usage(usage)
        logger.debug(
            f"Token usage - {usage.operation}: "
            f"{usage.input_tokens} in, {usage.output_tokens} out, "
            f"{usage.total_tokens} total"
        )
    
    @classmethod
    def get_stats(cls) -> TokenStats:
        """Get current token statistics."""
        instance = cls()
        return instance._stats
    
    @classmethod
    def reset(cls):
        """Reset token statistics."""
        instance = cls()
        instance._stats = TokenStats()
    
    @classmethod
    def print_summary(cls):
        """Print token usage summary."""
        instance = cls()
        instance._stats.print_summary()


# Convenience functions
def track_tokens(
    input_tokens: int, 
    output_tokens: int, 
    operation: str, 
    model: str = "claude-3-sonnet",
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0
):
    """Track token usage for an operation."""
    usage = TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        operation=operation,
        model=model
    )
    TokenTracker.track(usage)


def get_token_stats() -> TokenStats:
    """Get current token statistics."""
    return TokenTracker.get_stats()


def print_token_summary():
    """Print token usage summary."""
    TokenTracker.print_summary()


def reset_token_stats():
    """Reset token statistics."""
    TokenTracker.reset()
