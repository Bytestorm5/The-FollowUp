from typing import Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field
import datetime
from bson import ObjectId
try:  # Pydantic v2
    from pydantic import RootModel
except Exception:  # pragma: no cover
    RootModel = None

class ArticleLink(BaseModel):
    title: str = Field(..., description="Title of the news article")
    date: datetime.date = Field(..., description="Date of the news article")
    link: str = Field(..., description="Link to the news article")
    tags: List[str] = Field(..., description="Tags associated with the news article")
    raw_content: str = Field(..., description="Raw content of the news article")
    process_posturing: bool = False

class LinkAggregationStep(BaseModel):
    articles: List[ArticleLink] = Field(..., description="List of article links")
    look_further: bool = Field(..., description="Flag indicating if further links should be explored")
    
class LinkAggregationResult(BaseModel):
    articles: List[ArticleLink] = Field(..., description="List of article links")
    
    @classmethod
    def from_steps(cls, steps: List[LinkAggregationStep]):
        articles = []
        for step in steps:
            articles.extend(step.articles)
        articles = sorted(articles, key=lambda x: x.date, reverse=True)
        return cls(articles=articles)

class MongoArticle(BaseModel):
    id: Optional[ObjectId] = Field(None, description="MongoDB ID of the article")
    slug: Optional[str] = Field(None, description="URL-friendly unique slug for the article")
    title: str = Field(..., description="Title of the news article")
    date: datetime.date = Field(..., description="Date of the news article")
    inserted_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, description="Timestamp of when the article was inserted into the database")
    link: str = Field(..., description="Link to the news article")
    tags: List[str] = Field(..., description="Tags associated with the news article")
    raw_content: str = Field(..., description="Raw content of the news article")
    process_posturing: bool = False
    claim_processed: Optional[bool] = Field(None, description="Flag indicating if claims have been extracted from the article.")
    # Enrichment fields (generated in preprocessing step)
    clean_markdown: Optional[str] = Field(None, description="Verbatim clean text of the article, formatted as Markdown")
    summary_paragraph: Optional[str] = Field(None, description="One-paragraph summary of the article")
    key_takeaways: Optional[List[str]] = Field(None, description="Bullet point key takeaways from the article")
    priority: Optional[int] = Field(None, description="Article priority score: 1 (Active Emergency) .. 5 (Operational Updates)")
    
    def __init__(self, **kwargs):
        if "_id" in kwargs:
            kwargs["id"] = ObjectId(kwargs["id"]) if isinstance(kwargs["_id"], str) else kwargs["_id"]
        super().__init__(**kwargs)
        if isinstance(self.date, str):
            self.date = datetime.date.fromisoformat(self.date)
        if isinstance(self.inserted_at, str):
            self.inserted_at = datetime.datetime.fromisoformat(self.inserted_at)
    
    class Config:
        arbitrary_types_allowed = True
        extra = 'allow'

class Date_Delta(BaseModel):
    from_date: datetime.date = Field(..., description="Start date")
    days_delta: Optional[int] = Field(..., description="Number of days to add to the start date")
    weeks_delta: Optional[int] = Field(..., description="Number of weeks to add to the start date")
    months_delta: Optional[int] = Field(..., description="Number of months to add to the start date")
    years_delta: Optional[int] = Field(..., description="Number of years to add to the start date")
    
    def _resolve_date(self) -> datetime.date:
        new_date = self.from_date
        if self.days_delta:
            new_date += datetime.timedelta(days=self.days_delta)
        if self.weeks_delta:
            new_date += datetime.timedelta(weeks=self.weeks_delta)
        if self.months_delta:
            new_date = new_date.replace(month=new_date.month + self.months_delta)
        if self.years_delta:
            new_date = new_date.replace(year=new_date.year + self.years_delta)
        return new_date
    
Mechanism = Literal[
    "direct_action",     # executed under the actor's own authority immediately (EO signed, rule issued, funds released, etc.)
    "directive",         # actor directs another entity to act (EO directs agency, memo instructs office, etc.)
    "enforcement",       # investigations, prosecutions, penalties, inspections, compliance actions
    "funding",           # grants, disbursements, appropriations execution, contracts
    "rulemaking",        # proposed/final rules, guidance updates, regulatory processes
    "litigation",        # lawsuit filed, settlement, consent decree, court motion
    "oversight",         # audits, reports, inspector general, hearings, reviews
    "other",
]

Priority = Literal["high", "medium", "low"]

class ClaimProcessingStep(BaseModel):
    claim: str = Field(..., description="Canonical short description of the extracted claim (may be lightly normalized).")
    verbatim_claim: str = Field(..., description="Exact excerpt from the article supporting the claim (no paraphrase).")

    type: Literal["goal", "promise", "statement"] = Field(
        ...,
        description=(
            "Classification axis for downstream scheduling. "
            "statement = operationally meaningful verifiable claim about what is/was done or is true; "
            "goal = vague/aspirational objective not verifiable as complete; "
            "promise = future deliverable with an explicit deadline/time window and a measurable outcome."
        ),
    )

    completion_condition: str = Field(
        ...,
        description="Condition(s) that must be met to consider the claim true / goal achieved / promise fulfilled.",
    )

    # DEADLINE (not event date)
    completion_condition_date: Optional[Union[datetime.date, "Date_Delta"]] = Field(
        ...,
        description=(
            "Deadline/time window by which the completion condition must be met. "
            "PROMISE ONLY. Must be explicitly stated in the text (e.g., 'within 90 days', 'by March 2026'). "
            "Never set to the article date or 'today' unless the text explicitly sets that deadline."
        ),
    )

    # EVENT/EFFECTIVE DATE (not deadline)
    event_date: Optional[Union[datetime.date, "Date_Delta"]] = Field(
        ...,
        description=(
            "For already-taken actions (statements), the date the action occurred or became effective, "
            "ONLY if explicitly stated in the text. Never use for promises/deadlines."
        ),
    )

    follow_up_worthy: bool = Field(
        ...,
        description=(
            "Whether this step should be queued for follow-up checks. "
            "Almost always true for promises. For goals, true only if material and checkable later."
            "For statements, this indicates if this statement is worth performing a fact-check on."
        ),
    )

    priority: Priority = Field(
        ...,
        description=(
            "Operational priority for UI/pipeline. "
            "high = material policy/enforcement/funding/regulatory actions or time-bound promises; "
            "medium = meaningful but smaller-scope; "
            "low = background/context or record-only (prefer to omit these entirely)."
        ),
    )

    mechanism: Optional[Mechanism] = Field(
        None,
        description="Optional routing hint: how the claim is executed (directive, rulemaking, enforcement, etc.).",
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Resolve ISO dates + deltas for both date fields
        for field_name in ("completion_condition_date", "event_date"):
            val = getattr(self, field_name)
            if isinstance(val, str):
                setattr(self, field_name, datetime.date.fromisoformat(val))
            elif val is not None and hasattr(val, "_resolve_date"):
                setattr(self, field_name, val._resolve_date())

        # Normalize semantics: deadlines are promise-only; event dates are statement-only
        if self.type != "promise":
            self.completion_condition_date = None
        if self.type != "statement":
            self.event_date = None

        # Optional consistency nudge
        if not self.follow_up_worthy and self.priority == "high":
            self.priority = "medium"
    
class ClaimProcessingResult(BaseModel):
    steps: List[ClaimProcessingStep] = Field(..., description="List of claim processing steps")
    
    @classmethod
    def from_steps(cls, steps: List[ClaimProcessingStep]):
        return cls(steps=steps)    


class FollowupAnswer(BaseModel):
    text: str = Field(..., description="Concise answer to the question")
    sources: List[str] = Field(default_factory=list, description="List of source URLs used for this answer")


# Map of question index -> FollowupAnswer
# Use RootModel in Pydantic v2 for a dict-root schema; fall back to __root__ for v1
if RootModel is not None:
    class FollowupAnswerMap(RootModel[Dict[int, FollowupAnswer]]):  # type: ignore[type-arg]
        pass
else:  # Pydantic v1 compatibility
    class FollowupAnswerMap(BaseModel):  # type: ignore[type-arg]
        __root__: Dict[int, FollowupAnswer]

# Alternative list-based format for strict JSON schema consumers
class FollowupAnswerItem(BaseModel):
    index: int = Field(..., description="0-based question index")
    text: str = Field(..., description="Concise answer to the question")
    sources: List[str] = Field(..., description="List of source URLs used for this answer")

class FollowupAnswersList(BaseModel):
    answers: List[FollowupAnswerItem] = Field(..., description="List of answers keyed by 'index'")

class ArticleEnrichment(BaseModel):
    clean_markdown: str = Field(..., description="Verbatim clean text formatted as Markdown")
    summary_paragraph: str = Field(..., description="A concise one-paragraph summary")
    key_takeaways: List[str] = Field(..., description="Bullet point key takeaways")
    priority: Literal[5, 4, 3, 2, 1] = Field(..., description="Priority 1..5 where 1=Active Emergency, 2=Breaking News, 3=Important News, 4=Niche News, 5=Operational Updates")
    follow_up_questions: List[str] = Field(..., description="Follow-up questions that would help a layperson understand jargon, organizations, or context in the article")
    follow_up_question_groups: Union[List[List[int]], Literal['single', 'individual']] = Field(
        ...,
        description="Grouping of related follow-up questions using 0-based indexes into follow_up_questions. "
                    "'single' means all questions belong to one group; 'individual' means one group per question.",
    )
    
    
class MongoClaim(BaseModel):
    slug: Optional[str] = Field(None, description="URL-friendly unique slug for the claim")
    claim: str = Field(..., description="The claim being processed")
    verbatim_claim: str = Field(..., description="The verbatim version of the claim")
    type: Literal["goal", "promise", "statement"] = Field(..., description="Type of the claim. It can be 'goal', 'promise', or 'statement'. Goals are general objectives, promises are specific commitments with a deadline and a measurable outcome, and statements are factual assertions.")
    completion_condition: str = Field(..., description="Condition(s) that must be met to consider the claim true / goal achieved / promise fulfilled")
    completion_condition_date: Optional[Union[datetime.date, Date_Delta]] = Field(..., description="Date by which the completion condition must be met. Only fill in if the claim specifies a deadline or specific time window (e.g. '90 days', 'in March', etc).")
    # For statements: optional event/effective date
    event_date: Optional[Union[datetime.date, Date_Delta]] = Field(None, description="For statements, the date the action occurred/became effective if explicitly stated.")
    # Date of the article where the claim was found
    article_date: datetime.date = Field(..., description="Date of the article where the claim was found")
    article_id: str = Field(..., description="The ID of the article where the claim was found")
    article_link: str = Field(..., description="The link to the article where the claim was found")
    date_past: bool = Field(..., description="Flag indicating if the claim completion date has passed.")
    # Optional scheduling/ops hints from processing step
    follow_up_worthy: Optional[bool] = Field(None, description="Whether this claim should be queued for follow-up checks.")
    priority: Optional[Priority] = Field(None, description="Operational priority for UI/pipeline.")
    mechanism: Optional[Mechanism] = Field(None, description="Routing hint on how the claim is executed.")
    lm_log: Optional["LMLogEntry"] = Field(None, description="Log metadata for the LLM call that produced this claim")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if isinstance(self.completion_condition_date, str):
            self.completion_condition_date = datetime.date.fromisoformat(self.completion_condition_date)
        elif isinstance(self.completion_condition_date, Date_Delta):
            self.completion_condition_date = self.completion_condition_date._resolve_date()
        if isinstance(self.event_date, str):
            self.event_date = datetime.date.fromisoformat(self.event_date)
        elif isinstance(self.event_date, Date_Delta):
            self.event_date = self.event_date._resolve_date()


class ModelResponseOutput(BaseModel):
    """Structured output we expect from the Responses model for promise updates.

    Example expected JSON from the model:
        {"verdict": "in_progress", "text": "Some human readable summary", "sources": ["https://..."]}
    """
    verdict: Literal["complete", "in_progress", "failed"] = Field(..., description="Verdict about claim status")
    text: Optional[str] = Field(None, description="Optional human-readable text from the model")
    sources: Optional[List[str]] = Field(None, description="Optional list of source URLs referenced by the model output")
    follow_up_date: Optional[datetime.date] = Field(None, description="Optional date the model requests a follow-up on this topic (ISO date)")

    class Config:
        arbitrary_types_allowed = True


class FactCheckResponseOutput(BaseModel):
        """Structured output for fact checks.

        verdict categories:
            - True
            - False
            - Tech Error
            - Close
            - Misleading
            - Unverifiable
            - Unclear
        """
        verdict: Literal["True", "False", "Tech Error", "Close", "Misleading", "Unverifiable", "Unclear"] = Field(..., description="Fact check verdict")
        text: Optional[str] = Field(None, description="Concise explanation with evidence")
        sources: Optional[List[str]] = Field(None, description="Source URLs used in the fact check")
        follow_up_date: Optional[datetime.date] = Field(None, description="Optional follow-up date for developing items")

        class Config:
                arbitrary_types_allowed = True


class SilverUpdate(BaseModel):
    claim_id: Union[ObjectId, str] = Field(..., description="The DB id of the claim")
    claim_text: str = Field(..., description="The text of the claim")
    article_id: Union[ObjectId, str] = Field(..., description="The DB id of the article")
    article_link: str = Field(..., description="Link to the article")
    article_date: Optional[datetime.date] = Field(None, description="Date of the article")
    model_output: Union[ModelResponseOutput, FactCheckResponseOutput, dict, str] = Field(..., description="Structured model output or raw text output from the model")
    verdict: str = Field(..., description="Verdict about claim status (supports legacy and detailed categories)")
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    lm_log: Optional["LMLogEntry"] = Field(None, description="Log metadata for the LLM call producing this update")

    class Config:
        arbitrary_types_allowed = True


class SilverFollowup(BaseModel):
    claim_id: Union[ObjectId, str] = Field(..., description="The DB id of the claim")
    claim_text: str = Field(..., description="The text of the claim")
    follow_up_date: datetime.date = Field(..., description="Date to follow up on this claim/topic")
    article_id: Union[ObjectId, str] = Field(..., description="The DB id of the article")
    article_link: str = Field(..., description="Link to the article")
    model_output: Union[ModelResponseOutput, FactCheckResponseOutput, dict, str] = Field(..., description="Structured model output or raw text output from the model")
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    lm_log: Optional["LMLogEntry"] = Field(None, description="Log metadata for the LLM call proposing this follow-up")
    # When processed by the followup pipeline, these fields will be populated
    processed_at: Optional[datetime.datetime] = Field(None, description="When the followup was processed")
    processed_update_id: Optional[Union[ObjectId, str]] = Field(None, description="ID of the SilverUpdate created when processing this followup")

    class Config:
        arbitrary_types_allowed = True

class LMLogEntry(BaseModel):
    api_type: Literal['completions', 'responses'] = Field(..., description="Type of API call made to the language model")
    call_id: str = Field(..., description="Unique identifier for the API call")
    called_from: Optional[str] = Field(None, description="Module or function from which the API was called")
    model_name: str = Field(..., description="Name of the language model used")
    system_tokens: int = Field(..., description="Number of tokens in the system prompt")
    user_tokens: int = Field(..., description="Number of tokens in the user prompt")
    response_tokens: int = Field(..., description="Number of tokens in the model response")


RoundupKind = Literal["daily", "weekly", "monthly", "yearly"]


class RoundupSeedArticle(BaseModel):
    article_id: Union[ObjectId, str] = Field(...)
    title: str = Field(...)
    link: Optional[str] = Field(None)
    score: int = Field(..., description="Heuristic score used to select this article")
    key_takeaways: Optional[List[str]] = Field(None)
    claims: Optional[List[str]] = Field(None, description="Claim texts that reference this article")
    
    class Config:
        arbitrary_types_allowed = True


class RoundupResponseOutput(BaseModel):
    title: str = Field(..., description="Title for the roundup")
    text: str = Field(..., description="Markdown-formatted roundup body")
    sources: Optional[List[str]] = Field(None, description="Optional list of source URLs referenced")


class SilverRoundup(BaseModel):
    roundup_type: RoundupKind = Field(...)
    slug: Optional[str] = Field(None, description="URL-friendly unique slug for the roundup")
    period_start: datetime.date = Field(...)
    period_end: datetime.date = Field(...)
    title: str = Field(...)
    summary_markdown: str = Field(...)
    sources: Optional[List[str]] = Field(None, description="List of source URLs referenced by the roundup")
    seed_articles: List[RoundupSeedArticle] = Field(default_factory=list)
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    lm_log: Optional[LMLogEntry] = Field(None)

    class Config:
        arbitrary_types_allowed = True
    
    
