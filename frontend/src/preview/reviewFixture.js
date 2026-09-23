/* Hardcoded review data for the dev-only /reviews/preview route: the dashboard is
   otherwise only visible after a real multi-minute review run. Never imported by
   anything on a real code path. */

const incident = (priority, line_position, code_key, description, advice) => ({
  priority,
  line_position,
  code_key,
  description,
  advice,
})

export const PREVIEW_SOURCE = [
  'import logging',
  '',
  'from fastapi import APIRouter, Depends, HTTPException',
  '',
  'logger = logging.getLogger(__name__)',
  'router = APIRouter(prefix="/api/repos")',
  '',
  '',
  'class RepoService:',
  '    def __init__(self, session, github, cache, mailer, billing):',
  '        self.session = session',
  '        self.github = github',
  '        self.cache = cache',
  '        self.mailer = mailer',
  '        self.billing = billing',
  '',
  '    def register(self, repo_id, full_name, branch, notify=True):',
  '        repo = self.github.fetch(full_name)',
  '        if repo is None:',
  '            return None',
  '        if repo.pct < 25:',
  '            return None',
  '        self.session.add(repo)',
  '        self.cache.drop(repo_id)',
  '        if notify:',
  '            self.mailer.send(repo.owner_email, "registered")',
  '            self.billing.charge(repo.owner_id, 1)',
  '        return repo',
  '',
  '    def d(self, r):',
  '        try:',
  '            self.session.delete(r)',
  '        except Exception:',
  '            pass',
  '',
].join('\n')

export const PREVIEW_JOB = {
  review_id: 'preview',
  repo_id: 1,
  status: 'running',
  status_reason: null,
  file_paths: [
    'api/routers/repos.py',
    'api/services/billing.py',
    'api/services/legacy_sync.py',
    'api/services/indexing.py',
    'tests/test_repos.py',
  ],
  result: {
    meta: {
      total_files_in_pr: 5,
      total_files_reviewed: 2,
      overall_rating: 63.4,
      critical_incidents: 1,
      high_incidents: 3,
      medium_incidents: 4,
      low_incidents: 6,
      agents_run: ['SOLID1', 'SOLID2', 'COH', 'COUP', 'TEST', 'TCASE', 'CONC', 'CMPLX', 'ARCH', 'BOUND', 'VAR', 'DRY', 'ERR', 'CMT'],
      pr_recommendation: 'NEEDS_WORK',
      rejection_reason: null,
      skipped_files: [{ file_path: 'tests/test_repos.py', reason: 'test_file_context_only' }],
    },
    review: [
      {
        file_path: 'api/routers/repos.py',
        rating: 48,
        code_key: ['SOLID1', 'ERR', 'VAR'],
        file_lines: '1-34',
        size_status: 'normal',
        agents_skipped: [],
        skip_reason: null,
        incidents: [
          incident(
            'critical',
            '30-34',
            'ERR',
            'RepoService.d swallows every exception from session.delete, so a failed delete reports success to the caller.',
            'Let the exception propagate, or catch the specific database error and raise a RepoDeletionError that names the repo.'
          ),
          incident(
            'high',
            '9-15',
            'SOLID1',
            'RepoService takes five collaborators and mixes registration, caching, email and billing in one class.',
            'Split billing and notification out into their own services and have the router compose them.'
          ),
          incident(
            'high',
            '17-27',
            'SOLID1',
            'register() takes a boolean notify flag that switches on two unrelated side effects.',
            'Drop the flag and expose register() and register_and_notify() so each call site says what it means.'
          ),
          incident(
            'medium',
            '19-22',
            'ERR',
            'register() returns None both for "repo not found" and for "not enough Python", so the caller cannot tell them apart.',
            'Raise RepoNotFoundError and InsufficientPythonError instead of returning None.'
          ),
          incident(
            'low',
            '30-30',
            'VAR',
            'Method d() and parameter r give no clue what they hold.',
            'Rename to delete_repo(self, repo).'
          ),
        ],
      },
      {
        file_path: 'api/services/billing.py',
        rating: 79,
        code_key: ['CMPLX'],
        file_lines: '1-210',
        size_status: 'normal',
        agents_skipped: [],
        skip_reason: null,
        incidents: [
          incident(
            'medium',
            '88-140',
            'CMPLX',
            'charge() nests four levels deep across currency, proration and retry branches.',
            'Extract the proration branch into its own function and return early on the invalid-currency case.'
          ),
        ],
      },
    ],
  },
}

export const PREVIEW_PROGRESS = {
  'api/services/indexing.py': {
    VAR: { rating: 100, incidents: [] },
    CMT: { rating: 94, incidents: [incident('low', '12-12', 'CMT', 'Comment restates the line below it.', 'Delete it.')] },
    ERR: { rating: 85, incidents: [] },
    COH: { rating: 70, incidents: [incident('medium', '40-75', 'COH', 'Indexer mixes walking and persistence.', 'Split the walk out.')] },
  },
}

const agent = (code_key, name, weight, category, summary, checks) => ({
  code_key,
  name,
  weight,
  category,
  summary,
  checks,
})

const ROSTER = [
  agent('SOLID1', 'SRP + Open/Closed', 2.0, 'file', 'One reason to change per class or module.', ['Classes doing several unrelated jobs', 'Flag arguments']),
  agent('SOLID2', 'LSP + ISP + DIP', 2.0, 'file', 'Substitution contracts and depending on abstractions.', ['Hard dependencies on concretions']),
  agent('COH', 'Cohesion', 2.0, 'file', 'Things that change together stay together.', ['Methods that share no data']),
  agent('COUP', 'Coupling', 2.0, 'file', 'Dependencies stay minimal and directed.', ['Feature envy', 'God objects']),
  agent('TEST', 'Testability', 2.0, 'chunk', 'Whether this can be tested in isolation.', ['Hidden global state']),
  agent('TCASE', 'Test Cases', 1.5, 'chunk', 'Names only the coverage gaps.', ['Paths nothing asserts']),
  agent('CONC', 'Concurrency Safety', 1.5, 'chunk', 'Dangerous concurrent behaviour.', ['Shared mutable state']),
  agent('CMPLX', 'Complexity', 1.5, 'chunk', 'Cognitive load.', ['Nesting deeper than two levels']),
  agent('ARCH', 'Architecture', 1.5, 'rag', 'Layer boundaries and dependency direction.', ['Layer violations']),
  agent('BOUND', 'Boundaries', 1.5, 'file', 'Encapsulation and public surface.', ['Leaking library types']),
  agent('VAR', 'Naming', 1.0, 'chunk', 'Names that reveal intent.', ['Abbreviations']),
  agent('DRY', 'Duplication', 1.0, 'rag', 'Real duplication against indexed history.', ['Exact structural clones']),
  agent('ERR', 'Error Handling', 1.0, 'chunk', 'Failures are raised and named.', ['Swallowed exceptions']),
  agent('CMT', 'Comments', 0.5, 'chunk', 'Code explains itself.', ['Comments that restate the code']),
]

export const PREVIEW_AGENT_CATALOG = {
  agentsByCodeKey: Object.fromEntries(ROSTER.map((entry) => [entry.code_key, entry])),
  order: ROSTER.map((entry) => entry.code_key),
}
