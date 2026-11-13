"""
    Records every incident of a review as a database row and writes the row's id into the incident, so clients can name it.
"""
import copy
import hashlib
import logging
from typing import Any

from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.review_incident import CONTENT_CONSTRAINT, ReviewIncident

logger = logging.getLogger(__name__)

Target = tuple["IncidentLocation", dict[str, Any]]


class IncidentLocation(BaseModel):
    review_job_id: int
    file_path: str
    code_key: str


class IncidentRecorder:
    """Stamps the incidents of dumped reviews with their row ids; the caller commits the session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def stamp_entry(self, review_job_id: int, file_path: str, entry: dict[str, Any]) -> dict[str, Any]:
        """A copy of one agent's entry for one file with every incident stamped, or the entry unchanged if recording failed."""
        stamped = copy.deepcopy(entry)
        location = IncidentLocation(review_job_id=review_job_id, file_path=file_path, code_key=_plain(entry["code_key"]))
        targets = [(location, incident) for incident in stamped["incidents"]]
        return await self._stamped(stamped, entry, targets)

    async def stamp_result(self, review_job_id: int, result: dict[str, Any]) -> dict[str, Any]:
        """A copy of a merged result with every incident stamped, or the result unchanged if recording failed."""
        stamped = copy.deepcopy(result)
        targets = [
            (
                IncidentLocation(
                    review_job_id=review_job_id, file_path=file_review["file_path"], code_key=_plain(incident["code_key"])
                ),
                incident,
            )
            for file_review in stamped["review"]
            for incident in file_review["incidents"]
        ]
        return await self._stamped(stamped, result, targets)

    async def _stamped(self, stamped: dict[str, Any], original: dict[str, Any], targets: list[Target]) -> dict[str, Any]:
        """Recording runs in a savepoint and never raises: incidents without ids only cost the thumbs, not the review."""
        try:
            async with self._session.begin_nested():
                for location, incident in targets:
                    incident["incident_id"] = await self._id_of(location, incident)
        except Exception:
            logger.exception("Could not record incidents; they are sent without ids")
            return original
        return stamped

    async def _id_of(self, location: IncidentLocation, incident: dict[str, Any]) -> int:
        """Inserts the incident, or finds the row an earlier attempt of the same review already made, and returns its id."""
        statement = insert(ReviewIncident).values(
            review_job_id=location.review_job_id,
            file_path=location.file_path,
            code_key=location.code_key,
            priority=_plain(incident["priority"]),
            line_position=incident["line_position"],
            description=incident["description"],
            advice=incident["advice"],
            content_digest=content_digest_of(incident),
        )
        statement = statement.on_conflict_do_update(
            constraint=CONTENT_CONSTRAINT, set_={"advice": statement.excluded.advice}
        ).returning(ReviewIncident.id)
        return await self._session.scalar(statement)


def content_digest_of(incident: dict[str, Any]) -> str:
    """Recognises the same incident when a review runs again; never shown to clients."""
    return hashlib.sha1(f"{incident['line_position']}\x00{incident['description']}".encode()).hexdigest()


def _plain(value: Any) -> str:
    return getattr(value, "value", str(value))
