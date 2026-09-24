# Authentic offline epoch intake

This directory accepts future **offline**, source-authenticated snapshot files
only after the V4.9 intake checks verify a distinct raw SHA-256, normalized
property-vector SHA-256 and source epoch from the same target family.

Copies, renamed files, metadata-only rewrites, synthetic jitter, bootstrap
samples and resampling must never be placed here as additional epochs.
