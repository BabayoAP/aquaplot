# Devpost submission text

Paste each section into the matching Devpost field. Replace the bracketed note under
*Inspiration* with your own words: judges can tell a real reason from a written one, and only
you have it.

---

## Tagline

Volunteers name what lives in their stream, an AI double-checks them without seeing their answers, and published rules turn it into a health reading.

## Track alignment

**Primary: Track 3, AI-Supported Assessment.** Also serves Track 1 (Citizen Science UX), Track 2
(Data-to-Insight), Track 6 (Resilience Informatics) and Track 7 (Digital Health Standards).
Detail: [docs/HACKATHON.md](HACKATHON.md#track-alignment).

**Try it:** [open it in GitHub Codespaces](https://codespaces.new/BabayoAP/aquaplot?quickstart=1)
to run it in your browser with nothing to install, or run it on your own machine
([README, Run](https://github.com/BabayoAP/aquaplot#run)). Then open `/try` (90 seconds, real
photos pre-loaded, no account) and `/about` (the two-minute tour). **No API key is needed:** the
model's reading of the sample photos was recorded once and is replayed, labelled as a recording.
To see live readings of your own photos, paste a Claude key on `/developers`: it is kept in your
browser and sent only with your own checks. Source: https://github.com/BabayoAP/aquaplot

## Inspiration

The animals that live in a stream are the best evidence of its health. A flat-headed mayfly
means clean, oxygen-rich water; a tray of bloodworms and sludge worms means the opposite. They
are also the hardest thing for a volunteer to name, and Track 3 describes the problem exactly:
*citizen observations can be inconsistent and error-prone.*

The obvious answer, letting an AI identify the animals, felt wrong to us. The volunteer learns
nothing, nobody can tell when the AI is mistaken, and a machine's guess ends up in a record
that is supposed to protect people's health. OneAquaHealth's own Citizen Science App records the
channel, banks and flow of a site, but does not ask what lives in the water. We wanted to build
that missing half without taking the person out of it.

[Add one or two sentences of your own here: why this problem, why you.]

## What it does

A volunteer at an urban stream photographs the stream, scoops gravel from a shallow fast patch
into a pale tray, and **identifies what lives there** from a guide organised by shape ("three
tails", "a case made of sand").

A vision model looks at the same tray photo **without seeing their answers**, and only raises
questions where it saw something different: *"You marked some kind of stonefly. The model thinks
this may be Mayfly (flat-headed). Count the tails."* Questions are ranked by whether the answer
would change the stream's reading. The person decides.

Then published indices (BMWP, or the Iberian IBMWP in Portugal and Spain, chosen from the
coordinates) and a readable rule engine produce:

- a Water Framework Directive **screening band**, a visual pressure score, and **One Health
  findings** for the ecosystem, people and animals, each naming its rule, its evidence and an
  action, split between what you can do now, what your community can do, and what to ask the
  authority for;
- a **health alert that waits for a human**: evidence only the model saw is held at "concern"
  until a person confirms the observation it rests on;
- the **weather either side of the visit** (Open-Meteo): sewage signs after heavy rain point the
  authority at storm-overflow records, and in dry weather at misconnected drains;
- a **dated report** the citizen can send to the water authority;
- exports in **OneAquaHealth's own formats**: a FHIR R4 Bundle conforming to the project's IG
  (`hl7-eu/oah`), which passes the HL7 validator with no errors and no warnings, and the
  project's Citizen Science App submission in the app's own answer codes. A check at one of the
  project's 106 research sites carries the project's site code.

Repeat visits to the same spot become a **trend**, the dashboard flags declining sites, and a
**48-hour outlook** re-runs every site's latest reading against the forecast, because an
overflow is most likely to run when heavy rain falls where sewage has been seen. It works
**offline** (riverbanks often have no signal) and it works **with no AI at all**.

## How we built it

- **Python and FastAPI**, SQLite, and plain HTML and JavaScript with no build step, so it runs
  on a free tier and anyone can read it.
- **Claude** as the vision model, behind a fixed schema: `observe.py` may only return
  observations in a vocabulary generated from the field form, each with a confidence, and it
  is explicitly allowed to say "I cannot tell from this photo". Every determination lives in
  `bioindex.py` and `onehealth.py`, where it can be read, tested and argued with.
- **One JSON file** defines the field form, and generates the model's prompt, the server's
  validator, the questions on screen, the pressure scoring and the FHIR CodeSystem.
- **FHIR R4** against the OneAquaHealth IG, built from source with SUSHI and validated with the
  official HL7 validator.
- **The OneAquaHealth public API** (`api.enora-oah.eu`) for the 106 research sites and the
  app's answer codes, snapshotted so the app never depends on it at run time.
- **Open-Meteo** for weather, **iNaturalist** for taxonomy and places, Leaflet for the map.
- **313 automated tests**, none of which touch the network or a model: every network call goes
  through an injectable function.

## Challenges we ran into

- **Making the AI useful without letting it decide.** Our first version had the model identify
  the animals and the person confirm. We changed the order: the person identifies, and the model
  is asked blind, because the model agreeing only counts as evidence if it never saw the answer.
- **Getting a clean validation.** Our first FHIR export failed the HL7 validator: invalid
  `fullUrl`s, undefined extensions, empty arrays. We only found them by running the validator
  against the project's own profiles.
- **Being honest about thin evidence.** A tray with three animals cannot prove a stream is
  healthy or dead. The index caps the band a small sample can reach, and says so on screen.
- **A demo without a stream or an API key.** Judges rarely stand in a river. The sample check
  ships two openly licensed photos whose model reading was recorded once and is replayed,
  labelled as a recording everywhere it appears.

## Accomplishments that we're proud of

- The blind second opinion: an AI that asks a volunteer the right question instead of replacing
  their judgement.
- A FHIR export that conforms to OneAquaHealth's own IG with zero validator errors and warnings.
- Every finding explains itself, with the rule behind it, its evidence and an action.
- Missing inputs don't break it. No model, no signal, no coordinates or no photo each lower the
  certainty, with a sentence saying why, but none of them stops the result.

## What we learned

[Replace or edit with your own.] That "human in the loop" only means something once there is a
mechanism and a test behind it: an alert that will not fire without a person's confirmation, a
review that never calls the model again, and a record that says when a person took the AI's
answer rather than agreeing with it. And that the fastest way to find out whether an interoperability claim is true
is to run the official validator against it.

## What's next for AquaPlot

- **Measure the second opinion on real trays.** The evaluation harness is built
  ([EVALUATION.md](EVALUATION.md)); running it on labelled volunteer photos is the first step.
- National indices beyond BMWP and IBMWP (Portugal's IPtI, Italy's IBE): one score column each.
- Sending the Citizen Science App submission directly, with an app account.
- Mapping to the project's expert macroinvertebrate codes once they are documented.
- A pilot with a OneAquaHealth research city, comparing citizen readings with the project's own
  laboratory samples at the same site codes.

## Built with

python · fastapi · sqlite · javascript · html · claude · anthropic · fhir · hl7 · leaflet ·
inaturalist · open-meteo · three.js · playwright · pytest

## Prior work (required disclosure)

AquaPlot is a fork of the author's earlier project SpeciesGuard (github.com/BabayoAP/nativeview),
built for NextStep Hacks 2026; its code was written on Sep 16–17, 2026, inside this hackathon's
Sep 16–30 window. The freshwater domain and everything described above are new. Details and a
build timeline: [docs/HACKATHON.md](HACKATHON.md#build-timeline-and-prior-work). Claude Code was
used as a pair programmer throughout.
