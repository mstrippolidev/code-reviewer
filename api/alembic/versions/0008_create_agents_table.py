"""create agents table and seed the review roster

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-23

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

AGENT_CATEGORY = sa.Enum("file", "chunk", "rag", name="agent_category", schema="api")

# Frozen snapshot of the roster as of this revision: a migration that imported the
# live roster would rewrite history every time a prompt's wording changed.
SEED_ROSTER = [
    {
        "code_key": "SOLID1",
        "name": "SRP + Open/Closed",
        "weight": 2.0,
        "category": "file",
        "summary": "One reason to change per class or module, and extension without modification.",
        "checks": [
            "Classes doing several unrelated jobs",
            "Function-level single responsibility: one conceptual thing, not a line count",
            "Extension points that avoid editing existing code",
            "More than 3 arguments, or flag/boolean arguments",
        ],
    },
    {
        "code_key": "SOLID2",
        "name": "LSP + ISP + DIP",
        "weight": 2.0,
        "category": "file",
        "summary": "Substitution contracts, interface segregation, and depending on abstractions.",
        "checks": [
            "Subtypes that break their parent's contract",
            "Clients forced to depend on methods they never use",
            "Hard dependencies on concrete implementations",
            "Constructor injection versus instantiating collaborators internally",
        ],
    },
    {
        "code_key": "COH",
        "name": "Cohesion",
        "weight": 2.0,
        "category": "file",
        "summary": "Things that change together stay together.",
        "checks": [
            "Class methods that share no data or purpose",
            "Modules grouping unrelated functionality",
            "Classes mixing concerns, such as CRUD plus email plus reporting",
            "Where a low-cohesion class should be split",
        ],
    },
    {
        "code_key": "COUP",
        "name": "Coupling",
        "weight": 2.0,
        "category": "file",
        "summary": "Dependencies stay minimal and pointed in one direction.",
        "checks": [
            "Circular dependencies",
            "Feature envy: a class using another class more than itself",
            "Inappropriate intimacy with another class's internals",
            "God objects, and dependency chains that run too deep",
        ],
    },
    {
        "code_key": "TEST",
        "name": "Testability",
        "weight": 2.0,
        "category": "chunk",
        "summary": "Whether this code can be tested in isolation at all.",
        "checks": [
            "Dependencies constructed inside functions rather than injected",
            "Hidden global state",
            "Static methods carrying complex logic that cannot be mocked",
            "Units with too many dependencies to set up",
        ],
    },
    {
        "code_key": "TCASE",
        "name": "Test Cases",
        "weight": 1.5,
        "category": "chunk",
        "summary": "Reads the paired tests statically and names only the coverage gaps.",
        "checks": [
            "Paths and edge cases nothing currently asserts",
            "Concurrent test cases wherever shared mutable state is involved",
            "Tests that would need I/O, network, or a database to run",
            "States plainly when no test file was submitted alongside the source",
        ],
    },
    {
        "code_key": "CONC",
        "name": "Concurrency Safety",
        "weight": 1.5,
        "category": "chunk",
        "summary": "Dangerous concurrent behaviour, with a concrete fix proposed for each.",
        "checks": [
            "Shared mutable state with no protection",
            "Race-condition-prone patterns",
            "async/await misuse",
            "Non-atomic operations on shared resources",
        ],
    },
    {
        "code_key": "CMPLX",
        "name": "Complexity",
        "weight": 1.5,
        "category": "chunk",
        "summary": "Cognitive load: how hard this code is to hold in your head.",
        "checks": [
            "Nesting more than two levels deep",
            "Boolean conditions with more than three parts",
            "Functions with more than three exit points",
            "Whether the logic reads top to bottom",
            "Files in the 500-750 line soft-limit band",
        ],
    },
    {
        "code_key": "ARCH",
        "name": "Architecture",
        "weight": 1.5,
        "category": "rag",
        "summary": "Layer boundaries and dependency direction across the codebase.",
        "checks": [
            "Layer violations, such as domain importing from infrastructure",
            "Dependency direction correctness",
            "Pattern consistency with the rest of the repo",
            "Separation of construction from use",
            "May fetch a referenced module's real code before confirming a finding",
        ],
    },
    {
        "code_key": "BOUND",
        "name": "Boundaries",
        "weight": 1.5,
        "category": "file",
        "summary": "Encapsulation and how much of a module is public.",
        "checks": [
            "What is public versus private",
            "Information hiding",
            "A public API surface that is wider than it needs to be",
            "External library types leaking into domain logic",
        ],
    },
    {
        "code_key": "VAR",
        "name": "Naming",
        "weight": 1.0,
        "category": "chunk",
        "summary": "Names that reveal intent without needing a comment.",
        "checks": [
            "Names that do not reveal intent",
            "Abbreviations",
            "Vocabulary that drifts between one part of the file and another",
        ],
    },
    {
        "code_key": "DRY",
        "name": "Duplication",
        "weight": 1.0,
        "category": "rag",
        "summary": "Real duplication against this repo's indexed history and the rest of this submission.",
        "checks": [
            "Exact structural clones, proven by fingerprint rather than judged",
            "Near-duplicates confirmed by a judge that sees both real code fragments",
            "Duplication inside this submission, before anything is merged",
            "Warns when merging two lookalikes would be the wrong abstraction",
        ],
    },
    {
        "code_key": "ERR",
        "name": "Error Handling",
        "weight": 1.0,
        "category": "chunk",
        "summary": "Failures are raised and named, never returned as codes.",
        "checks": [
            "Generic exceptions where a custom one belongs",
            "Returning None or an error code instead of raising",
            "Swallowed exceptions",
            "Dead code on error paths",
        ],
    },
    {
        "code_key": "CMT",
        "name": "Comments",
        "weight": 0.5,
        "category": "chunk",
        "summary": "Code explains itself; comments carry only the non-obvious why.",
        "checks": [
            "Comments that restate what the code already says",
            "Ambiguous or stale comments",
            "Commented-out code",
            "Docstrings describing implementation rather than the interface",
        ],
    },
]


def upgrade() -> None:
    agents_table = op.create_table(
        "agents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code_key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("category", AGENT_CATEGORY, nullable=False),
        sa.Column("summary", sa.String(), nullable=False),
        sa.Column("checks", sa.JSON(), nullable=False),
        sa.UniqueConstraint("code_key"),
        schema="api",
    )
    op.create_index("ix_api_agents_code_key", "agents", ["code_key"], schema="api")
    op.bulk_insert(agents_table, SEED_ROSTER)


def downgrade() -> None:
    op.drop_index("ix_api_agents_code_key", table_name="agents", schema="api")
    op.drop_table("agents", schema="api")
    AGENT_CATEGORY.drop(op.get_bind(), checkfirst=True)
