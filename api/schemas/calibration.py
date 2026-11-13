from pydantic import BaseModel


class PairSideRead(BaseModel):
    file_path: str
    chunk_name: str
    start_line: int
    end_line: int
    code: str


class CalibrationPairRead(BaseModel):
    """One pair to label, with the caller's existing answer when there is one; carries no score and no judge verdict."""

    pair_id: str
    left: PairSideRead
    right: PairSideRead
    is_duplicate: bool | None
    note: str | None


class LabelWrite(BaseModel):
    is_duplicate: bool
    note: str | None = None


class CalibrationProgress(BaseModel):
    labeled: int
    total: int


class LabelExport(BaseModel):
    pair_id: str
    is_duplicate: bool
    note: str | None
