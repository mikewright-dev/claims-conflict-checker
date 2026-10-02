# Known limitations

Limits found while building Phases 1 to 4. Each is a fact about the current behavior.

## Extraction (Phase 2)
- Each extraction field holds one fact per document. The policy's revision line (6 months changed to 3 months) and the surgeon note's "denies current nicotine use" are not captured.
- Null extraction fields are not covered by any test. The answer key does not say which fields a document leaves unstated, so only values the key lists are asserted.
- The MRI report's fusion level was not extracted (the field came back null).
- The live tests accept one cited page per expectation. A correct value cited from another page that the key also lists would fail them.
- Quote grounding ignores whitespace and case only. A paraphrased quote counts as ungrounded.
- The extractor has no retry logic. During the Phase 2 live run the model returned repeated 503 (high demand) errors.
- The example extraction run is a single run, so run-to-run variation is not yet measured.

## Normalization (Phase 3)
- Strength normalizes to the lowest grade stated in the text. This is a heuristic. Plus or minus grades such as "4+/5" are left unparsed.
- Numeric dates are read month/day/year. Two-digit years, impossible dates, ranges and text with two different dates are left unparsed.
- Text with two different levels, durations or counts is left unparsed rather than reduced to one.
- "Denies current nicotine use" is left unparsed, because it does not say whether the person is a former or a never smoker.
- Durations keep their units. Weeks and months are never converted.

## Comparison (Phase 4)
- Durations in different units are uncomparable rather than converted. If any document in a field uses a different unit, the whole field is uncomparable, not just the odd one out. The raw text is kept in `uncomparable`.
- A field present in only one document is reported nowhere.
- Decoy D2 (level notation, L4-5 vs L4-L5) is verified at the parser level and with a value injected from the answer key into the MRI report's extraction. It is not verified end to end on live model output, because the MRI level was not extracted.
- The comparison reports disagreement only. It does not say which side is right, how severe the conflict is, or whether it helps or hurts the appeal. That is Phase 5.
