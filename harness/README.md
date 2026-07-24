# Vibe Research Qualification Harness

This directory implements the frozen, evidence-derived execution contract from
`开发指导.md`. It deliberately separates engineering assurance, external
validation, and release qualification. A successful command or generated file
is never sufficient evidence of scientific capability.

Authoritative state is `events.jsonl`. `state.json` is an atomic projection that
must be reproducible from the journal. `phase-contract.lock` is instantiated
from the external bootstrap contract and must not be weakened to make an
implementation pass.

The external Day 0 recovery snapshot is stored at
`D:\科研软件制作\Vibe-research源码-Day0Baseline`; reports in this repository
contain hashes and counts, not copied secrets.
