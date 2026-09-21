import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    name: str
    input_cost_per_m: float
    output_cost_per_m: float


JEV_MODEL_SPEC = ModelSpec("jev-latest", input_cost_per_m=0.042, output_cost_per_m=0.0)
GEMINI_MODEL = os.getenv("EVAL_GEMINI_MODEL", "gemini/gemini-3.1-flash-lite")
LUNA_MODEL = os.getenv("EVAL_LUNA_MODEL", "gpt-5.6-luna")
