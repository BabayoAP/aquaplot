"""Live model readings on a demo that pays for them.

A public test of AquaPlot with a real Claude key has no accounts, so the key is protected
by counting live photo readings, not people. One reading is one check whose photos went to
the paid model; the sample photos are answered from their recording and a review never calls
the model again, so neither uses one. Three limits apply, all counted in the store so that a
restart does not reset them:

* **per tester**: ``AQUAPLOT_LIVE_PER_TESTER`` (default 2), ever. A tester is the browser's
  own id (``X-AquaPlot-Contributor``), or its network address when it sends none.
* **per network per day**: ``AQUAPLOT_LIVE_PER_NETWORK`` (default 10), so clearing the
  browser's storage does not buy unlimited readings, with room for a class on one Wi-Fi.
* **whole server per day**: ``AQUAPLOT_LIVE_PER_DAY`` (default 40). No visitor can get round
  this one, whatever headers they send.

``0`` turns a limit off. Only the paid backend is limited; a local Ollama model is free.
When a limit is reached the check still runs, without the model, and says why: a citizen
who walked to a stream has done the real work either way. The spending limit set on the
key in the Anthropic console remains the backstop behind all three.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime

PAID_OBSERVERS = {"claude"}


@dataclass(frozen=True)
class LiveLimits:
    per_tester: int = 2
    per_network: int = 10
    per_day: int = 40

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> LiveLimits:
        env = os.environ if env is None else env
        return cls(
            per_tester=int(env.get("AQUAPLOT_LIVE_PER_TESTER", cls.per_tester)),
            per_network=int(env.get("AQUAPLOT_LIVE_PER_NETWORK", cls.per_network)),
            per_day=int(env.get("AQUAPLOT_LIVE_PER_DAY", cls.per_day)),
        )

    def as_counts(self) -> dict[str, int]:
        """In the shape Store.claim_live_reading takes."""
        return {"tester": self.per_tester, "network": self.per_network, "day": self.per_day}


def today() -> str:
    return datetime.now(UTC).date().isoformat()


def is_paid(observer: object) -> bool:
    return getattr(observer, "name", None) in PAID_OBSERVERS


def status(counts: dict[str, int], limits: LiveLimits) -> dict:
    """What a tester needs to know: how many live readings they have left, and if none, why.

    ``left`` is the smallest of the three limits, because any one of them stops a reading.
    The reason names the most personal limit that ran out, since that is the one the tester
    can make sense of.
    """
    remaining = {
        k: (limit - counts[k]) if limit > 0 else None
        for k, limit in limits.as_counts().items()
    }
    finite = [r for r in remaining.values() if r is not None]
    left = max(0, min(finite)) if finite else None
    reason = None
    if left == 0:
        if remaining["tester"] is not None and remaining["tester"] <= 0:
            n = limits.per_tester
            reason = f"you have used the {n} live photo reading{'s' if n != 1 else ''} this test gives each tester"
        elif remaining["network"] is not None and remaining["network"] <= 0:
            reason = f"this network has used today's {limits.per_network} live photo readings"
        else:
            reason = f"today's {limits.per_day} live photo readings for this test are used up"
    return {"limited": True, "per_tester": limits.per_tester, "used": counts["tester"], "left": left, "reason": reason}
