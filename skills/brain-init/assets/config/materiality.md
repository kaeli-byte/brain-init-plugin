# Materiality

A finding updates canonical knowledge when it can materially change:

- **Industry structure** — value chain position, consolidation, entry/exit barriers
- **Value capture** — who profits, margin structure, pricing power
- **Demand** — volume, growth rate, substitution risk, customer concentration
- **Product content** — what goes into the product, specifications, bill of materials
- **Growth mechanisms** — what drives adoption, what constrains it
- **Competitive position** — market share, differentiation, switching costs
- **Technical architecture** — system design, component choices, performance envelopes
- **Manufacturing economics** — process cost, yield, scale requirements, capital intensity
- **Qualification** — customer/safety/regulatory approval status and timelines
- **An active thesis** — evidence that strengthens or weakens a live investigation
- **A recommendation** — anything that would change what we advise
- **Confidence** — evidence that materially raises or lowers confidence in an existing claim

## Non-Material

Do not create a standalone claim merely because extraction found a sentence. Non-material details remain discoverable in the source record. Examples of typically non-material findings:

- Minor year-over-year fluctuations within normal range
- Routine operational updates without strategic implication
- Boilerplate risk factors (unless a specific risk materializes)
- Background industry descriptions that repeat public knowledge
- Organizational changes below C-suite unless tied to strategic shift

## Borderline Cases

When unsure: create the claim with `confidence: low` and `review_state: needs_review`. The human curator decides. It is cheaper to demote a weak claim later than to re-discover a missed signal.
