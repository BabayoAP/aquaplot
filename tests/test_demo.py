"""The demo dataset: an empty deployment must never greet a visitor with an empty dashboard."""

from datetime import UTC, datetime, timedelta

from aquaplot import demo
from aquaplot.assess import StreamAssessor
from aquaplot.observe import NullObserver
from aquaplot.store import Store

NOW = datetime(2026, 9, 28, 12, tzinfo=UTC)


async def test_an_empty_store_is_filled_with_labelled_dated_series():
    store = Store(":memory:")
    now = datetime.now(UTC)  # the alert feed looks back from today
    stored = await demo.seed(StreamAssessor(observer=NullObserver()), store, now=now)
    assert stored == len(demo.VISITS)
    sites = {s["name"]: s for s in store.sites()}
    assert all("(demo data)" in name for name in sites)
    coimbra = sites["Ribeira da Fonte, Coimbra (demo data)"]
    assert coimbra["assessments"] == 3 and coimbra["trend"]["direction"] == "declining"
    assert sites["Leie side channel, Ghent (demo data)"]["trend"]["direction"] == "improving"
    history = store.history(coimbra["site_key"])
    assert history[-1]["created_at"][:10] == (now - timedelta(days=120)).date().isoformat()  # the chart spans months
    assert store.alerts(days=30), "the declining site should be in the early-warning feed"


async def test_a_store_that_already_has_data_is_left_alone():
    store = Store(":memory:")
    assessor = StreamAssessor(observer=NullObserver())
    await demo.seed(assessor, store, now=NOW)
    assert await demo.seed(assessor, store, now=NOW) == 0
    assert store.summary()["assessments"] == len(demo.VISITS)
