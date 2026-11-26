"""Token usage per model (each API response counted once) and the estimated cost."""
import json
import os

PRICES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline-dashboard-prices.json")
RATE_KEYS = ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read")


class Usage(object):
    FIELDS = ("input", "output", "cache_write_5m", "cache_write_1h", "cache_read")

    def __init__(self, input=0, output=0, cache_write_5m=0, cache_write_1h=0, cache_read=0):
        self.input = input
        self.output = output
        self.cache_write_5m = cache_write_5m
        self.cache_write_1h = cache_write_1h
        self.cache_read = cache_read

    @property
    def cache_write(self):
        return self.cache_write_5m + self.cache_write_1h

    @property
    def total(self):
        return self.input + self.output + self.cache_write + self.cache_read

    def add(self, other):
        for name in self.FIELDS:
            setattr(self, name, getattr(self, name) + getattr(other, name))
        return self

    def copy(self):
        return Usage(*[getattr(self, name) for name in self.FIELDS])

    def to_dict(self):
        return {"input": self.input, "output": self.output, "cache_write": self.cache_write,
                "cache_read": self.cache_read, "total": self.total}


def _int(source, key):
    value = source.get(key) if isinstance(source, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def usage_of(raw):
    """Usage from one message.usage dict. Cache writes without a TTL split count as 5-minute."""
    split = raw.get("cache_creation") if isinstance(raw, dict) else None
    if isinstance(split, dict) and ("ephemeral_5m_input_tokens" in split or "ephemeral_1h_input_tokens" in split):
        write_5m = _int(split, "ephemeral_5m_input_tokens")
        write_1h = _int(split, "ephemeral_1h_input_tokens")
    else:
        write_5m, write_1h = _int(raw, "cache_creation_input_tokens"), 0
    return Usage(_int(raw, "input_tokens"), _int(raw, "output_tokens"), write_5m, write_1h,
                 _int(raw, "cache_read_input_tokens"))


def usage_by_model(entries):
    """{model: Usage} over assistant entries. A response written on several lines shares one
    message.id and repeats the same usage, so each id is counted once."""
    seen = set()
    out = {}
    for entry in entries:
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
            continue
        message_id = message.get("id")
        if message_id:
            if message_id in seen:
                continue
            seen.add(message_id)
        model = message.get("model") if isinstance(message.get("model"), str) else "unknown"
        out.setdefault(model, Usage()).add(usage_of(message["usage"]))
    return out


def merge(by_models):
    out = {}
    for by_model in by_models:
        for model, value in by_model.items():
            if model in out:
                out[model].add(value)
            else:
                out[model] = value.copy()
    return out


def total(by_model):
    result = Usage()
    for value in by_model.values():
        result.add(value)
    return result


def load_prices(path=None):
    try:
        with open(path or PRICES_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, dict):
        return {}
    return {name: rates for name, rates in models.items()
            if isinstance(rates, dict) and all(isinstance(rates.get(k), (int, float)) for k in RATE_KEYS)}


def price_for(model, prices):
    """Exact match, else the longest price key that the model id starts with."""
    if model in prices:
        return prices[model]
    best = None
    for key in prices:
        if model.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return prices[best] if best else None


def estimate_cost(by_model, prices):
    """(usd, complete): complete is False when some tokens have no price (e.g. '<synthetic>')."""
    amount = 0.0
    complete = True
    for model, value in by_model.items():
        if value.total == 0:
            continue
        rates = price_for(model, prices)
        if rates is None:
            complete = False
            continue
        amount += (value.input * rates["input"] + value.output * rates["output"]
                   + value.cache_write_5m * rates["cache_write_5m"]
                   + value.cache_write_1h * rates["cache_write_1h"]
                   + value.cache_read * rates["cache_read"]) / 1000000.0
    return amount, complete
