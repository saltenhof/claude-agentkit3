# Bound tokenizer asset provenance (FK-13 §13.2, PO decision D5)

This directory ships the **versioned, immutable package asset** that the FK-13
retrieval engine uses for deterministic, embedding-model-aligned chunk sizing.

- Model / tokenizer: `sentence-transformers/all-MiniLM-L6-v2`
- Pinned revision: `e4ce9877abf3edfe10b0d82785e83bdcb973e22e`
- Runtime library pin: `tokenizers==0.21.0` (declared in `pyproject.toml`)

## Asset list

| File | Kind | Bound SHA-256 digest |
|------|------|----------------------|
| `tokenizer.json` | HuggingFace fast tokenizer | `tokenizer.json.sha256` |
| `vocab.txt` | WordPiece vocabulary (companion) | `vocab.txt.sha256` |

## License

`sentence-transformers/all-MiniLM-L6-v2` is distributed under the
**Apache License 2.0** (declared in the model card `license: apache-2.0`).
The full Apache-2.0 text is reproduced in `LICENSE.apache-2.0.txt`.

## Fail-closed contract

The loader (`agentkit.concepts.tokenizer.load_bound_tokenizer`) verifies the
SHA-256 digest of `tokenizer.json` against `tokenizer.json.sha256` **before**
parsing. On a missing asset, a divergent digest, or a structurally/semantically
incompatible asset it raises a hard error -- there is **no** runtime network
fetch and **no** character-based fallback (DR 2026-07-21 Rand 3 / FK-13 §13.2).
