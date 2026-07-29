"""
    Represents one file as it arrives in a PR submission, before file
    selection and the per-file pipeline run on it.
"""
from pydantic import BaseModel


class SubmittedFile(BaseModel):
    file_path: str
    content: str
