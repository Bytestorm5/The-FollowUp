from typing import Dict, Literal, Tuple
from openai import OpenAI
import os, sys

from pydantic import BaseModel

_HERE = os.path.dirname(__file__)
_SERVICE_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(_SERVICE_ROOT, '.env'))    
_CLIENT = OpenAI()


# Mapping of task type and difficulty to model and reasoning effort
MODEL_TABLE: Dict[str, Dict[Literal['high', 'medium', 'low'], Tuple[str, str]]] = {
    "agent": {
        "high": ("gpt-5-mini", "high"),
        "medium": ("gpt-5-mini", "medium"),
        "low": ("gpt-5-nano", "low")
    },
    "process": {
        "high": ("gpt-5-mini", "low"),
        "medium": ("gpt-5-mini", "none"),
        "low": ("gpt-5-nano", "none")
    }
}
SELECTOR_MODEL = "gpt-5-nano"

class SelectorResponse(BaseModel):
    quality: Literal['high', 'medium', 'low']

def select_model(task_type: Literal['agent', 'process'], prompt: str) -> Tuple[str, str]:
    response = _CLIENT.responses.parse(
        model=SELECTOR_MODEL,
        text_format=SelectorResponse,
        input=[
            {
                "role": "system",
                "content": f"You are a model selection assistant. Given a task description, you will select the appropriate model quality level for the task from the following options: high, medium, low. Respond with only one of these options."
            },
            {
                "role": "user",
                "content": f"Task description: {prompt}\n\nBased on the above task description, select the appropriate model quality level (high, medium, low) for a {task_type} task."
            }
        ],
        
    )
    if not response.output_parsed or not hasattr(response.output_parsed, 'quality'):
        # Fallback to medium if parsing fails
        choice = "medium"
    else:
        choice = response.output_parsed.quality
        if choice not in MODEL_TABLE[task_type]:
            choice = "medium"
    return MODEL_TABLE[task_type][choice]