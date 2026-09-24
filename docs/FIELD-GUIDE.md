# Field guide — how to check a stream

The guide itself lives at **[`src/aquaplot/data/field_guide.md`](../src/aquaplot/data/field_guide.md)**,
inside the package rather than in `docs/`, because it is not only documentation:
the running app serves it, formatted for printing, at **`/field-guide`**, and a
community group is expected to print it and hand it out. One canonical copy, read
by both the reader and the program, beats two that drift apart.

It covers what to bring, safety (which matters more than the data), how to choose
a spot and why a riffle is the fair place to judge a stream, how to take a kick
sample without a net, how to photograph a tray so the animals are actually
visible, a quick identification table ordered best-news-first, putting everything
back, check-clean-dry, and the two questions only a person standing there can
answer.

| Where | What for |
|---|---|
| [`src/aquaplot/data/field_guide.md`](../src/aquaplot/data/field_guide.md) | Read or edit it here — this is the source of truth |
| `/field-guide` | Printable page served by the app, for handing out |
| `/api/field-guide.md` | The raw Markdown, for anyone who wants to reuse it |

Editing it is editing the product. A test asserts the file is present, non-trivial
and reachable through the running app.
