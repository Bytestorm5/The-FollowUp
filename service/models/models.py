from typing import List, Literal, Optional, Union
from pydantic import BaseModel, Field
import datetime
from bson import ObjectId

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
    title: str = Field(..., description="Title of the news article")
    date: datetime.date = Field(..., description="Date of the news article")
    inserted_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow, description="Timestamp of when the article was inserted into the database")
    link: str = Field(..., description="Link to the news article")
    tags: List[str] = Field(..., description="Tags associated with the news article")
    raw_content: str = Field(..., description="Raw content of the news article")
    process_posturing: bool = False
    claim_processed: Optional[bool] = Field(None, description="Flag indicating if claims have been extracted from the article.")
    
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
    
class ClaimProcessingStep(BaseModel):
    claim: str = Field(..., description="The claim being processed")
    verbatim_claim: str = Field(..., description="The verbatim version of the claim")
    type: Literal["goal", "promise", "statement"] = Field(..., description="Type of the claim. It can be 'goal', 'promise', or 'statement'. Goals are general objectives, promises are specific commitments with a deadline and a measurable outcome, and statements are factual assertions.")
    completion_condition: str = Field(..., description="Condition(s) that must be met to consider the claim true / goal achieved / promise fulfilled")
    completion_condition_date: Optional[Union[datetime.date, Date_Delta]] = Field(..., description="Date by which the completion condition must be met. Only fill in if the claim specifies a deadline or specific time window (e.g. '90 days', 'in March', etc).")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if isinstance(self.completion_condition_date, str):
            self.completion_condition_date = datetime.date.fromisoformat(self.completion_condition_date)
        elif isinstance(self.completion_condition_date, Date_Delta):
            self.completion_condition_date = self.completion_condition_date._resolve_date()
    
class ClaimProcessingResult(BaseModel):
    steps: List[ClaimProcessingStep] = Field(..., description="List of claim processing steps")
    
    @classmethod
    def from_steps(cls, steps: List[ClaimProcessingStep]):
        return cls(steps=steps)    
    
    
class MongoClaim(BaseModel):
    claim: str = Field(..., description="The claim being processed")
    verbatim_claim: str = Field(..., description="The verbatim version of the claim")
    type: Literal["goal", "promise", "statement"] = Field(..., description="Type of the claim. It can be 'goal', 'promise', or 'statement'. Goals are general objectives, promises are specific commitments with a deadline and a measurable outcome, and statements are factual assertions.")
    completion_condition: str = Field(..., description="Condition(s) that must be met to consider the claim true / goal achieved / promise fulfilled")
    completion_condition_date: Optional[Union[datetime.date, Date_Delta]] = Field(..., description="Date by which the completion condition must be met. Only fill in if the claim specifies a deadline or specific time window (e.g. '90 days', 'in March', etc).")
    # Date of the article where the claim was found
    article_date: datetime.date = Field(..., description="Date of the article where the claim was found")
    article_id: str = Field(..., description="The ID of the article where the claim was found")
    article_link: str = Field(..., description="The link to the article where the claim was found")
    date_past: bool = Field(..., description="Flag indicating if the claim completion date has passed.")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if isinstance(self.completion_condition_date, str):
            self.completion_condition_date = datetime.date.fromisoformat(self.completion_condition_date)
        elif isinstance(self.completion_condition_date, Date_Delta):
            self.completion_condition_date = self.completion_condition_date._resolve_date()


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


class SilverUpdate(BaseModel):
    claim_id: Union[ObjectId, str] = Field(..., description="The DB id of the claim")
    claim_text: str = Field(..., description="The text of the claim")
    article_id: Union[ObjectId, str] = Field(..., description="The DB id of the article")
    article_link: str = Field(..., description="Link to the article")
    article_date: Optional[datetime.date] = Field(None, description="Date of the article")
    model_output: Union[ModelResponseOutput, str] = Field(..., description="Structured model output or raw text output from the model")
    verdict: Literal["complete", "in_progress", "failed"] = Field(..., description="Verdict about claim status")
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

    class Config:
        arbitrary_types_allowed = True


class SilverFollowup(BaseModel):
    claim_id: Union[ObjectId, str] = Field(..., description="The DB id of the claim")
    claim_text: str = Field(..., description="The text of the claim")
    follow_up_date: datetime.date = Field(..., description="Date to follow up on this claim/topic")
    article_id: Union[ObjectId, str] = Field(..., description="The DB id of the article")
    article_link: str = Field(..., description="Link to the article")
    model_output: Union[ModelResponseOutput, str] = Field(..., description="Structured model output or raw text output from the model")
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    # When processed by the followup pipeline, these fields will be populated
    processed_at: Optional[datetime.datetime] = Field(None, description="When the followup was processed")
    processed_update_id: Optional[Union[ObjectId, str]] = Field(None, description="ID of the SilverUpdate created when processing this followup")

    class Config:
        arbitrary_types_allowed = True