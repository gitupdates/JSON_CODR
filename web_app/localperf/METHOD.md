# LocalPerf-Core-v1 method

Run one unmeasured warmup, then execute all 12 prompts in fixed order for three Quick or seven Thorough repetitions. Record generation tokens/second, streaming time-to-first-token in milliseconds, peak VRAM in MiB, duration, token counts, completion status, and bounded quality outcomes for prompts lp-07 through lp-10.

A configuration conforms only when every expected sample succeeds, all required metrics exist, and all required quality validators execute. Compare only identical prompt/repetition pairs. JSON_CODR uses a seeded 10,000-resample stratified paired bootstrap with BCa intervals and reports probability of superiority. Imported results are reference evidence and never automatically qualify as a local hardware baseline.

Identifiers follow `lp-NN`; package files use `json-codr-localperf-core-v1-1.0-YYYYMMDDTHHMMSSZ.localperf.zip`.
