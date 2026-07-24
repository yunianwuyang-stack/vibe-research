# ADR-G0-011: Decode percent-encoded local artifact file URIs

- Date: 2026-07-18
- Status: Accepted for local regression repair; G0 remains BLOCKED for independent external reasons
- Scope: ArtifactIndex URI verification under Unicode workspace paths

## Context

The affected full unit regression ran under the product workspace path D:\科研软件制作\Vibe-research源码. Artifact registration records a file URI using Path.as_uri(), which percent-encodes Unicode path segments. The previous verifier removed only the file:/// prefix and passed the percent-encoded text directly to Path, producing a non-existent path on Windows.

## Decision

Parse file URIs with urlsplit, reject non-local or malformed URI forms, percent-decode the path, normalize the Windows drive slash, and only then hash the target. A direct Unicode test now covers register to verify.

## Consequences

The prior unit failure is real red evidence, not a skipped environment condition. The repair retains tamper detection: changing file contents still raises ArtifactIntegrityError.
