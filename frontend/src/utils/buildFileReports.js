import { countIncidentsByPriority } from './reviewScore'

export const FILE_STATUS = {
  REVIEWED: 'reviewed',
  FAILED: 'failed',
  RUNNING: 'running',
  PENDING: 'pending',
  EXCLUDED: 'excluded',
}

const SKIP_REASON_LABELS = {
  test_file_context_only: 'Used as test context only — never rated on its own',
  agent_execution_failed: 'An agent call failed; this file was dropped from the review',
  exceeded_pr_file_cap: 'Beyond this submission’s file cap',
  file_too_large: 'Too large to review',
  raw_character_limit_exceeded: 'Too large to review',
  intake_rejected: 'Rejected at intake: not reviewable source code',
  migration_file: 'Migration file — out of scope',
  lock_file: 'Lock file — out of scope',
  vendored_file: 'Vendored code — out of scope',
}

export function describeSkipReason(reason) {
  return SKIP_REASON_LABELS[reason] ?? reason ?? 'Not reviewed'
}

/**
 * Merges the finished report with whatever the live stream has reported so far
 * into one per-file view. Live agent events win over the aggregated result:
 * they are the only source carrying a per-agent rating.
 */
export function buildFileReports({ job, agentProgress, reviewedFiles, failedFiles }) {
  const resultEntries = new Map((job.result?.review ?? []).map((entry) => [entry.file_path, entry]))
  const skipReasons = new Map(
    (job.result?.meta?.skipped_files ?? []).map((skipped) => [skipped.file_path, skipped.reason])
  )
  const agentsRun = job.result?.meta?.agents_run ?? []
  const isSettled = job.status === 'completed' || job.status === 'failed'

  return job.file_paths.map((filePath) => {
    const liveAgents = agentProgress[filePath] ?? {}
    const resultEntry = resultEntries.get(filePath)
    const agents = mergeAgents(liveAgents, resultEntry, agentsRun)
    const incidents = agents.flatMap((agent) => agent.incidents)
    return {
      filePath,
      status: fileStatus({ filePath, reviewedFiles, failedFiles, liveAgents, skipReasons, isSettled }),
      skipReason: skipReasons.has(filePath) ? describeSkipReason(skipReasons.get(filePath)) : null,
      rating: resultEntry?.rating ?? null,
      fileLines: resultEntry?.file_lines ?? null,
      sizeStatus: resultEntry?.size_status ?? null,
      agentsReported: Object.keys(liveAgents).length,
      agentsSkipped: resultEntry?.agents_skipped ?? [],
      incidentCounts: countIncidentsByPriority(incidents),
      agents,
    }
  })
}

function fileStatus({ filePath, reviewedFiles, failedFiles, liveAgents, skipReasons, isSettled }) {
  if (failedFiles.has(filePath)) {
    return FILE_STATUS.FAILED
  }
  if (reviewedFiles.has(filePath)) {
    return FILE_STATUS.REVIEWED
  }
  if (skipReasons.has(filePath)) {
    return FILE_STATUS.EXCLUDED
  }
  if (Object.keys(liveAgents).length > 0) {
    return FILE_STATUS.RUNNING
  }
  // A file the run finished without ever settling was never dispatched at all:
  // claiming it is still processing is what used to leave it spinning forever.
  return isSettled ? FILE_STATUS.EXCLUDED : FILE_STATUS.PENDING
}

function mergeAgents(liveAgents, resultEntry, agentsRun) {
  const byCodeKey = new Map()
  for (const [codeKey, entry] of Object.entries(liveAgents)) {
    byCodeKey.set(codeKey, { codeKey, rating: entry.rating, incidents: withCodeKey(entry.incidents, codeKey) })
  }
  const reportedLive = new Set(byCodeKey.keys())
  for (const incident of resultEntry?.incidents ?? []) {
    const codeKey = incident.code_key
    if (reportedLive.has(codeKey)) {
      continue
    }
    const agent = byCodeKey.get(codeKey) ?? { codeKey, rating: null, incidents: [] }
    agent.incidents.push(incident)
    byCodeKey.set(codeKey, agent)
  }
  if (resultEntry) {
    for (const codeKey of agentsRun) {
      if (!byCodeKey.has(codeKey)) {
        byCodeKey.set(codeKey, { codeKey, rating: null, incidents: [] })
      }
    }
  }
  return [...byCodeKey.values()]
}

function withCodeKey(incidents, codeKey) {
  return incidents.map((incident) => ({ ...incident, code_key: incident.code_key ?? codeKey }))
}
