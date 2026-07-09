// Subagent relevance judge for the semantic eval.
//
// Grades the unjudged (query, profile) pairs that eval/semantic/judge.py wrote to
// eval/semantic/to_judge.json, using SUBAGENTS (Claude Code plan) — never a paid
// API call — and merges the grades into eval/semantic/judgments.json (the cache).
//
// Run it with the Workflow tool:
//   Workflow({ scriptPath: "eval/semantic/judge_subagents.js" })
// then re-run `python -m eval.semantic.run` (grades now served from cache).
//
// Design: this orchestration script has no filesystem access, so all I/O is done
// by agents (Read/Write/Bash). A loader agent lists the pending queries (metadata
// only); one grade agent per query reads its own candidates from to_judge.json and
// returns graded results; a writer agent merges them into judgments.json.

export const meta = {
  name: 'judge-subagents',
  description: 'Grade eval/semantic/to_judge.json via subagents (no paid API) and merge into judgments.json',
  phases: [
    { title: 'Load', detail: 'list pending queries' },
    { title: 'Grade', detail: 'one agent per query' },
    { title: 'Write', detail: 'merge into judgments.json' },
  ],
}

const RUBRIC = `Rate how well an alumni profile satisfies the searcher's INTENT:
3 = Ideal (exactly the kind of person wanted); 2 = Relevant; 1 = Marginal (loosely related); 0 = Irrelevant.
Judge by MEANING with world knowledge (XTX/Pinely -> relevant to "HFT"; "Sales Manager" -> relevant to "продажи"; Bocconi -> an Italian university). Weigh job titles, employers, expertise, NES program, pre-NES university & specialty, city, hobbies, and bio. NAME queries: only the actual person(s) named are 3, else 0. Location/employer/title queries: the attribute must actually match to score >= 2. Be strict about 3 vs 2.`

const LOAD_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['groups'],
  properties: {
    groups: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['qid', 'query', 'rationale', 'count'],
        properties: {
          qid: { type: 'string' }, query: { type: 'string' },
          rationale: { type: 'string' }, count: { type: 'integer' },
        },
      },
    },
  },
}

const RESULT_SCHEMA = {
  type: 'object', additionalProperties: false, required: ['results'],
  properties: {
    results: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false,
        required: ['key', 'grade', 'reason'],
        properties: {
          key: { type: 'string' }, grade: { type: 'integer' }, reason: { type: 'string' },
        },
      },
    },
  },
}

phase('Load')
const loaded = await agent(
  `Read eval/semantic/to_judge.json (a JSON array of objects {key, qid, query, rationale, nes_id, card}). ` +
  `Group the entries by qid and return {"groups":[{qid, query, rationale, count}]} — metadata ONLY (do not include cards). ` +
  `If the file is missing or empty, return {"groups":[]}.`,
  { label: 'load-pending', phase: 'Load', schema: LOAD_SCHEMA }
)

const groups = (loaded && loaded.groups) || []
if (!groups.length) {
  log('to_judge.json empty or missing — nothing to grade.')
  return { judged: 0 }
}
log(`grading ${groups.length} queries (${groups.reduce((a, g) => a + g.count, 0)} pairs) via subagents`)

phase('Grade')
const graded = await parallel(groups.map((g) => () =>
  agent(
    `${RUBRIC}\n\n` +
    `Read eval/semantic/to_judge.json and select the entries whose "qid" == ${JSON.stringify(g.qid)} ` +
    `(there are ${g.count}). Each has {key, card}. The search query is ${JSON.stringify(g.query)}; ` +
    `the searcher wants: ${g.rationale}\n\n` +
    `Grade EVERY selected entry 0-3 by how well its profile card satisfies the intent, with a <=12-word reason. ` +
    `Return {"results":[{key, grade, reason}]} — one per entry, echoing its exact "key".`,
    { label: `grade:${g.qid}`, phase: 'Grade', schema: RESULT_SCHEMA }
  )
))

const results = graded.filter(Boolean).flatMap((r) => r.results)
log(`collected ${results.length} graded pairs`)

phase('Write')
await agent(
  `Merge graded relevance judgments into eval/semantic/judgments.json.\n` +
  `1. Read eval/semantic/judgments.json if it exists (an object {key: {grade, reason}}); else start from {}.\n` +
  `2. For each entry below, set judgments[entry.key] = {"grade": entry.grade, "reason": entry.reason}.\n` +
  `3. Write the file back as UTF-8 pretty JSON (ensure_ascii false / keep Cyrillic).\n` +
  `4. Delete eval/semantic/to_judge.json.\n` +
  `Report the total number of keys in judgments.json afterwards.\n\n` +
  `Entries:\n${JSON.stringify(results)}`,
  { label: 'merge-judgments', phase: 'Write' }
)

return { judged: results.length }
