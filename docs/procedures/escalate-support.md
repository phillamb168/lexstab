# Escalate a support incident

Source material for `lexstab procedure add --operation ESCALATE_INCIDENT
--input docs/procedures/escalate-support.md` (spec §42.9). Each non-heading
line becomes one procedure step; the artifact is reviewed and frozen before
benchmark use. A procedure says how to carry out a resolved operation; it must
never redefine which operation the user requested or add facts unavailable to
comparison conditions (spec §15.4).

- Confirm that the incident is open and the destination tier exceeds the current tier.
- Propose ESCALATE_INCIDENT using the resolved entity and destination without changing unrelated state.
