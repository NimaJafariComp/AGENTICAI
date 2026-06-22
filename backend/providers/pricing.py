from __future__ import annotations

# Per-million-token prices (USD) as of 2025-06.
# Format: model_name -> (input_price_per_million, output_price_per_million)
# Source: official pricing pages for each provider.
# Update these when prices change; None means price is unknown → cost not computed.

OPENAI_PRICES: dict[str, tuple[float, float]] = {
    # GPT-4o family
    "gpt-4o":               (2.50,  10.00),
    "gpt-4o-2024-11-20":   (2.50,  10.00),
    "gpt-4o-2024-08-06":   (2.50,  10.00),
    "gpt-4o-mini":         (0.15,   0.60),
    "gpt-4o-mini-2024-07-18": (0.15, 0.60),
    # o1 family
    "o1":                   (15.00, 60.00),
    "o1-2024-12-17":       (15.00, 60.00),
    "o1-mini":              (1.10,   4.40),
    "o1-mini-2024-09-12":  (1.10,   4.40),
    "o3-mini":              (1.10,   4.40),
    # GPT-4 Turbo
    "gpt-4-turbo":          (10.00, 30.00),
    "gpt-4-turbo-2024-04-09": (10.00, 30.00),
    # GPT-3.5
    "gpt-3.5-turbo":        (0.50,   1.50),
    "gpt-3.5-turbo-0125":  (0.50,   1.50),
}

ANTHROPIC_PRICES: dict[str, tuple[float, float]] = {
    # Claude 4 family
    "claude-opus-4-8":                  (15.00, 75.00),
    "claude-sonnet-4-6":               (3.00,  15.00),
    "claude-haiku-4-5":                (0.80,   4.00),
    "claude-haiku-4-5-20251001":       (0.80,   4.00),
    # Claude 3.5 family
    "claude-3-5-sonnet-20241022":      (3.00,  15.00),
    "claude-3-5-sonnet-20240620":      (3.00,  15.00),
    "claude-3-5-haiku-20241022":       (0.80,   4.00),
    # Claude 3 family
    "claude-3-opus-20240229":          (15.00, 75.00),
    "claude-3-sonnet-20240229":        (3.00,  15.00),
    "claude-3-haiku-20240307":         (0.25,   1.25),
}


def compute_cost(
    prices: dict[str, tuple[float, float]],
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float | None:
    """Return cost in USD, or None if model is not in the pricing table."""
    entry = prices.get(model)
    if entry is None:
        return None
    input_price, output_price = entry
    return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000
