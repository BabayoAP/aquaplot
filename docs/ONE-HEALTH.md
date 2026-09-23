# The One Health rules

Every determination AquaPlot makes about people or animals comes from a rule in
`src/aquaplot/onehealth.py`. This document lists all of them so that someone with domain
knowledge — a public-health officer, a freshwater ecologist, a vector biologist — can read
the logic and tell us where it is wrong. That is the point of using rules rather than a model
for this part of the system.

## Why rules, here

An LLM is the right tool for turning a photograph into structured observations and the wrong
tool for deciding whether to warn a parent. A health-adjacent claim has to be traceable to
"the observer reported a blue-green surface bloom", not to a weight in a network. Published
public-health practice can be written down and corrected; a fine-tune cannot be read.

## Levels

`ok` < `watch` < `concern` < `alert`. **Alert means a person should change what they do
today.** It is reserved for rules with a direct exposure pathway, and the engine refuses to
raise one on model output no human has confirmed — it downgrades to `concern`, appends
*"held below alert level because no person has confirmed the observation behind it"* to the
evidence, and adds *"Confirm the observation in the app to raise this to a full alert"* to the
action. `assess.py` then puts that exact observation at the top of the confirmation queue.

## Human health

| Rule | Fires when | Level | The action it gives |
|---|---|---|---|
| `human.cyanobacteria` | A surface bloom, scum or paint-like mat is recorded | `alert` with contact, else `concern` | Keep out, keep children and dogs out including from spray, report it — only a laboratory can confirm toxin-producing cyanobacteria |
| `human.faecal_contamination` | Sewage smell, sanitary waste on the banks, grey or black water, or persistent white foam | `concern` on one sign, `alert` on two or with contact | Do not enter, wash hands, report to the water company *and* the regulator today with the date and photo |
| `human.vector_breeding` | Mosquito larvae identified, or water slow or standing | `concern` when larvae + stagnant + warm season, else `watch` | Remove water-holding litter, report standing water; restoring flow is the durable fix, insecticide is not |
| `human.chemical_exposure` | Rainbow sheen, chemical smell, or orange water | `concern`, `alert` with contact | Keep out, do not disturb the sediment, report it — a fresh sheen is traceable upstream, a weathered one is not |
| `human.wellbeing` | Band High or Good *and* pressure under 25 | `ok` | Keep recording it; evidence that a stretch is in good condition is what protects it from the next development proposal |

`human.wellbeing` exists because One Health is not only a list of hazards. A clean, accessible
urban stream lowers heat stress, supports recreation and improves mental wellbeing, and a tool
that only ever reports what is wrong teaches people that nothing they do helps.

## Animal health

| Rule | Fires when | Level | The action it gives |
|---|---|---|---|
| `animal.drinking_water` | A bloom, sewage signs, or discoloured/chemically smelling water | `alert` when animals drink or enter, else `concern` | Keep dogs on a lead past this stretch, carry water, warn other owners |
| `animal.parasite_hosts` | Snail families that host flukes, *and* people or animals enter the water | `watch` | Not a reason to avoid the stream; do not graze livestock on the wet margin, rinse off after wading |
| `animal.invasive_species` | A species on an invasive list was identified here | `concern` | Do not move animals, plants or wet gear between water bodies; check, clean and dry; record the sighting — early detection is the only cheap stage of an invasion |

## Ecosystem

| Rule | Fires when | Level | The action it gives |
|---|---|---|---|
| `ecosystem.biological_condition` | Always | From the band; capped at `concern` when the sample is provisional | Repeat seasonally when healthy; when not, repeat upstream and downstream — where the invertebrates change is where the problem enters |
| `ecosystem.habitat_degradation` | Concrete channel, artificial bed, or no vegetated buffer | `concern` on two signs, else `watch` | Water quality alone will not fix this; ask about de-culverting, softening banks, and leaving a margin unmown — the cheapest of those is mowing less |
| `ecosystem.thermal_resilience` | Fully sun-exposed, or flow stopped or dry | `concern` when dry or stagnant, else `watch` | Date every dry or stagnant finding; bankside trees hold summer temperature down by several degrees |
| `ecosystem.sedimentation` | Heavy silt or sludge, or turbid water | `concern` on sludge, else `watch` | Look upstream for bare soil, construction or a direct road drain; note whether it rained yesterday — storm turbidity and constant turbidity have different causes |

## Exposure changes the finding

The same water quality produces different levels depending on who touches it. `access` — is
this fenced off, is there a path, do people and dogs get in, do children play in it or animals
drink from it — never enters the pressure score and always enters the rules. A degraded stream
nobody touches is an ecological problem; a degraded stream children paddle in is also a public
health one, and the tool should not say the same thing about both.

## Actions are split by who can take them

- **You, now** — every action from a finding at concern or above.
- **Your community** — repeat the check (a trend moves a municipality when one complaint does
  not), ask for an unmown margin, tell other users, organise a litter pick, run a check-clean-dry
  reminder.
- **Your authority** — trace the sewer network upstream, sample for cyanotoxins and sign the
  access points, inspect surface-water outfalls, commission a standardised kick sample, add the
  reach to riparian shading and de-culverting programmes, add the point to the vector round.

## The disclaimer travels with every result

> AquaPlot is a citizen-science screening tool. It is not a medical, water-quality or regulatory
> determination. If a finding concerns you, report it to your local water authority or
> environmental agency, who can sample and test.

## Adding or changing a rule

A rule is a function decorated with `@rule` that takes a `Context` and returns a `Finding` or
`None`. It must carry a stable id, the evidence in the words the observer used, and an action.
If it can reach `alert`, list the habitat answers it rests on in `assess.RULE_EVIDENCE` so the
confirmation queue knows what to ask for. `tests/test_onehealth.py` covers each rule's trigger
and its escalation, and a test asserts every rule id in the code appears in this document.
