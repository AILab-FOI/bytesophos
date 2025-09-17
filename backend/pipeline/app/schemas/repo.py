# app/schemas/repo.py

from typing import List, Optional, Dict, Any,TypedDict
from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

class StatisticsResponse(BaseModel):
    index_status: str
    document_count: int

class DocumentItem(BaseModel):
    id: str
    content: str
    meta: dict

class ListDocumentsResponse(BaseModel):
    documents: List[DocumentItem]

class ContextDoc(BaseModel):
    filename: str
    content: str
    id: Optional[str] = None

class AnswerRequest(BaseModel):
    repo_id: Optional[str] = None
    repoId: Optional[str] = None
    query: Optional[str] = None
    question: Optional[str] = None
    conversation_id: Optional[str] = None
    conversationId: Optional[str] = None
    user_id: Optional[str] = None
    userId: Optional[str] = None

class AnswerResponse(BaseModel):
    answer: str
    contexts: List[ContextDoc] = Field(default_factory=list)

class FileContentResponse(BaseModel):
    content: str

class PhaseState(BaseModel):
    status: Optional[str] = None 
    processed: Optional[int] = None
    total: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None
    startedAt: Optional[float] = None
    finishedAt: Optional[float] = None
    model_config = ConfigDict(extra="ignore")

class RepoStatusResponse(BaseModel):
    repoId: str
    status: str                        
    phases: Dict[str, PhaseState]    
    stats: Dict[str, Any]

from typing import Literal, Optional
from pydantic import BaseModel

class RepoBrief(BaseModel):
    id: str
    label: str
    source_type: Optional[Literal["git", "upload"]] = None