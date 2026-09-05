# Adaptive follow-up questions

## Goal
After a candidate confirms a transcript, the system may ask a focused follow-up question when the current answer leaves a material uncertainty about technical depth or correctness. A root interview question may have at most **2** follow-ups. Then the interview always continues with the next planned root question.

## Product rules
- Follow-ups are only for technical competencies. Motivation questions are never probed automatically.
- A follow-up is optional: the LLM should ask one only when it can materially improve the assessment, not merely because an answer is imperfect.
- `possible_extra_questions` from the question bank are hints, not a mandatory script. The LLM may use one verbatim or generate a better focused question.
- Maximum: `2` follow-ups per root question, enforced by backend code independently of the LLM response.
- Candidate sees only the follow-up question and its `1/2` or `2/2` label. Internal reasoning (`reason`, `focus`) is visible only in the HR/manager report.
- LLM/probing failures are fail-open: the interview continues to the next planned question.

## State machine
For each planned root question:

1. Ask root question.
2. Candidate records answer and confirms transcript.
3. Score the answer with the existing per-answer scorer.
4. Build the whole root chain so far: root answer + already answered follow-ups.
5. Ask the adaptive-probe LLM for two things:
   - cumulative root-question assessment (`resolved_root_score_0_10`);
   - whether one more follow-up is useful and, if yes, the next question.
6. Backend validates the decision.
   - if follow-up count is already `2` => force `ask_follow_up=false`;
   - reject empty/duplicate questions;
   - reject low-confidence probe decisions;
   - classify source as `possible_extra_questions` or `generated` server-side.
7. If probing is requested, create exactly one follow-up turn and ask it immediately.
8. Otherwise move to the next planned root question.

A repeated `correct-transcript` request for the same answer is idempotent and must return the already persisted decision instead of creating another follow-up.

## Data model
New tables are additive, so existing SQLite databases do not require destructive migrations.

### `question_probe_configs`
One-to-one with `questions`.
- `question_id`
- `possible_extra_questions` JSON

The bundled `questions.json` backfills this metadata for existing bank questions only when no config exists; it never overwrites HR edits.

### `interview_question_probe_configs`
Frozen one-to-one snapshot for a candidate's planned `InterviewQuestion`.
- `interview_question_id`
- `possible_extra_questions` JSON

This prevents later question-bank edits from changing an already created candidate interview.

### `answer_question_links`
Explicit mapping from an `Answer` to the concrete `InterviewQuestion` shown to the candidate.
- `answer_id`
- `interview_question_id`

This removes ambiguity from text-based matching, especially for generated follow-ups.

### `adaptive_probe_decisions`
Audit record for every adaptive decision after a confirmed answer.
- root question
- triggering answer
- current follow-up count
- whether a follow-up was requested
- generated follow-up `InterviewQuestion` (nullable)
- `reason`, `focus`, `source`
- cumulative `resolved_root_score_0_10`
- decision confidence

The unique `trigger_answer_id` makes decision creation idempotent.

## LLM contract
A dedicated `follow_up_decision.md` prompt is separate from `score_question.md`.

Input includes:
- original root question and scoring criteria;
- `possible_extra_questions`;
- all Q/A turns already collected for this root question;
- already asked question texts;
- current follow-up count and maximum.

Output:
```json
{
  "ask_follow_up": false,
  "follow_up_question": null,
  "reason": "string",
  "focus": "string",
  "source": "possible_extra_questions | generated | none",
  "resolved_root_score_0_10": 0.0,
  "confidence_0_1": 0.0
}
```

Backend normalizes all enum/range fields and never trusts the model to enforce the two-question limit.

## Scoring fairness
Follow-up answers must **not** increase the weight of a topic simply because more turns were asked.

The final technical average therefore contains one score per planned root technical question:
- if no adaptive decision exists, use the root answer score;
- otherwise use the latest cumulative `resolved_root_score_0_10` for that root chain;
- follow-up answer scores are preserved as evidence but are not counted as additional independent root questions;
- motivation remains excluded from the technical average.

This keeps two candidates comparable even when one receives more probing.

## Report
The report keeps the existing flat answer list for backward compatibility and adds an explicit `adaptive_follow_ups` section. Each chain shows:
- root question;
- number of follow-ups;
- latest resolved root score;
- each follow-up question;
- why it was asked (`reason` / `focus`);
- whether it came from the configured hints or was generated;
- candidate transcript and per-answer analysis.

The final LLM receives follow-up relationship metadata and is instructed to treat follow-ups as evidence for their root question, not as separately weighted interview questions.

## Failure and abuse guards
- max 2 enforced server-side;
- duplicate/near-empty follow-up questions are dropped;
- low-confidence probe decision does not interrupt the interview;
- motivation questions are excluded;
- candidate never receives internal score/reason during the interview;
- no proctoring, face, gaze, voice style, demographics or other non-technical signals are included in follow-up generation or scoring;
- if LLM/API parsing fails, continue with the next planned question.
